"""Booking lifecycle operations.

DRAFT is never persisted — a booking row is created only at Confirm, in
PENDING_PAYMENT, which is the moment the slot becomes reserved.

    PENDING_PAYMENT --(I've Paid)--> AWAITING_VERIFICATION --(staff)--> CONFIRMED
           |                                    |
           |--(hold expires)--> EXPIRED         |--(patient)--> CANCELLED
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from clinic_bot.clinic_config import ClinicConfig
from clinic_bot.db.models import (
    BLOCKING_STATUSES,
    Booking,
    BookingStatus,
    Doctor,
    Patient,
    Service,
)
from clinic_bot.scheduling import clock
from clinic_bot.scheduling.slots import booking_end, slot_is_free

log = logging.getLogger(__name__)

# Ambiguous characters removed so refs survive being read aloud over the phone.
_REF_ALPHABET = "ACDEFGHJKLMNPQRTUVWXY3479"
_REF_LENGTH = 5


class SlotTakenError(RuntimeError):
    """The slot was claimed between listing it and confirming it."""


def _clinic_prefix(cfg: ClinicConfig) -> str:
    initials = "".join(w[0] for w in cfg.clinic.name.split() if w and w[0].isalnum())
    return (initials[:3] or "CLN").upper()


def generate_ref(session: Session, cfg: ClinicConfig) -> str:
    prefix = _clinic_prefix(cfg)
    for _ in range(12):
        body = "".join(secrets.choice(_REF_ALPHABET) for _ in range(_REF_LENGTH))
        ref = f"{prefix}-{body}"
        if session.scalar(select(Booking.id).where(Booking.ref == ref)) is None:
            return ref
    # 25^5 keyspace; twelve collisions means something is badly wrong.
    raise RuntimeError("could not generate a unique booking reference")


def get_or_create_patient(session: Session, wa_id: str, name: str = "") -> Patient:
    patient = session.scalar(select(Patient).where(Patient.wa_id == wa_id))
    if patient is None:
        patient = Patient(wa_id=wa_id, name=name)
        session.add(patient)
        session.flush()
    elif name and patient.name != name:
        patient.name = name
    return patient


def create_hold(
    session: Session,
    *,
    cfg: ClinicConfig,
    patient: Patient,
    doctor: Doctor,
    service: Service,
    start: dt.datetime,
    patient_name: str,
) -> Booking:
    """Reserve a slot. Raises SlotTakenError if it is no longer free.

    The availability re-check closes the common case (slot listed, then taken
    while the patient was reading the summary). The DB unique index closes the
    concurrent case, surfacing as IntegrityError.
    """
    if not slot_is_free(session, doctor=doctor, service=service, start=start, cfg=cfg):
        raise SlotTakenError(f"{doctor.code} @ {start} is no longer available")

    booking = Booking(
        ref=generate_ref(session, cfg),
        patient_id=patient.id,
        doctor_id=doctor.id,
        service_id=service.id,
        starts_at=start,
        ends_at=booking_end(start, service, cfg),
        status=BookingStatus.PENDING_PAYMENT,
        amount=cfg.payment.advance_amount,
        patient_name=patient_name or patient.name,
        hold_expires_at=clock.now() + dt.timedelta(minutes=cfg.booking.hold_minutes),
    )
    session.add(booking)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise SlotTakenError(f"{doctor.code} @ {start} was taken concurrently") from exc
    return booking


def declare_paid(session: Session, booking: Booking) -> Booking:
    """Patient tapped 'I've Paid'. Payment is verified by clinic staff, not by us."""
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = BookingStatus.AWAITING_VERIFICATION
        booking.paid_declared_at = clock.now()
        booking.hold_expires_at = None
        session.flush()
    return booking


def cancel_booking(session: Session, booking: Booking, reason: str = "patient") -> Booking:
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_reason = reason[:200]
    booking.hold_expires_at = None
    session.flush()
    return booking


def reschedule_booking(
    session: Session,
    *,
    cfg: ClinicConfig,
    booking: Booking,
    doctor: Doctor,
    service: Service,
    new_start: dt.datetime,
) -> Booking:
    """Move a booking in place, keeping its reference."""
    if not slot_is_free(
        session,
        doctor=doctor,
        service=service,
        start=new_start,
        cfg=cfg,
        exclude_booking_id=booking.id,
    ):
        raise SlotTakenError(f"{doctor.code} @ {new_start} is no longer available")

    booking.doctor_id = doctor.id
    booking.service_id = service.id
    booking.starts_at = new_start
    booking.ends_at = booking_end(new_start, service, cfg)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise SlotTakenError("slot taken concurrently during reschedule") from exc
    return booking


def upcoming_bookings(session: Session, patient: Patient, limit: int = 9) -> list[Booking]:
    """Future, slot-occupying bookings for a patient, soonest first."""
    return list(
        session.scalars(
            select(Booking)
            .where(
                Booking.patient_id == patient.id,
                Booking.status.in_(BLOCKING_STATUSES),
                Booking.starts_at >= clock.now(),
            )
            .order_by(Booking.starts_at.asc())
            .limit(limit)
        )
    )


def booking_by_ref(session: Session, ref: str) -> Booking | None:
    return session.scalar(select(Booking).where(Booking.ref == ref))


def expire_stale_holds(session: Session) -> int:
    """Release slots whose payment window lapsed. Returns how many were released."""
    now = clock.now()
    stale = list(
        session.scalars(
            select(Booking).where(
                Booking.status == BookingStatus.PENDING_PAYMENT,
                Booking.hold_expires_at.is_not(None),
                Booking.hold_expires_at < now,
            )
        )
    )
    for booking in stale:
        booking.status = BookingStatus.EXPIRED
        booking.hold_expires_at = None
    if stale:
        session.flush()
        log.info("Released %d expired slot hold(s)", len(stale))
    return len(stale)
