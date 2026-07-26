"""Booking lifecycle operations.

DRAFT is never persisted — a booking row is created only at Confirm, in
PENDING_PAYMENT, which is the moment the slot becomes reserved.

    PENDING_PAYMENT --(I've Paid)--> AWAITING_VERIFICATION --(staff confirms)--> CONFIRMED
           |                                    |
           |--(hold expires)--> EXPIRED         |--(staff rejects)--> CANCELLED
                                                |--(patient cancels)--> CANCELLED

"I've Paid" is a patient CLAIM, not a payment. UPI here is peer-to-peer with no
gateway (PROJECT_PLAN.md §1 non-goals), so no code in this project can observe
that money moved. Only a human comparing the clinic's bank statement can, which
is what `confirm_booking` / `reject_payment` and the `clinic_admin.py payments`
command exist for. Nothing else may ever set CONFIRMED.
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
    """Patient tapped 'I've Paid'.

    This is a CLAIM, not a payment. There is no payment gateway (PROJECT_PLAN.md
    §1 non-goals), so nothing here can prove money moved. The booking therefore
    goes to AWAITING_VERIFICATION and stays there until a human at the clinic
    confirms or rejects it via `scripts/clinic_admin.py`.

    The hold is cleared deliberately: a patient who has genuinely paid must not
    lose their slot to a 15-minute timer. The cost is that a false claim occupies
    a slot until staff review it, which is why `pending_verification()` exists
    and why the CLI sorts oldest-first.
    """
    if booking.status == BookingStatus.PENDING_PAYMENT:
        booking.status = BookingStatus.AWAITING_VERIFICATION
        booking.paid_declared_at = clock.now()
        booking.hold_expires_at = None
        session.flush()
    return booking


def record_payment_ref(session: Session, booking: Booking, payment_ref: str) -> Booking:
    """Store the UPI reference the patient typed. Self-declared, never proof."""
    booking.payment_ref = payment_ref.strip()[:32]
    session.flush()
    return booking


def pending_verification(session: Session, limit: int = 200) -> list[Booking]:
    """Bookings a human still has to check, oldest declaration first."""
    return list(
        session.scalars(
            select(Booking)
            .where(Booking.status == BookingStatus.AWAITING_VERIFICATION)
            .order_by(Booking.paid_declared_at.asc())
            .limit(limit)
        )
    )


def confirm_booking(session: Session, booking: Booking, verified_by: str = "staff") -> Booking:
    """Staff matched the payment against the clinic's own statement."""
    if booking.status is not BookingStatus.AWAITING_VERIFICATION:
        raise ValueError(
            f"{booking.ref} is {booking.status.value}, not AWAITING_VERIFICATION — "
            f"only a booking awaiting verification can be confirmed"
        )
    booking.status = BookingStatus.CONFIRMED
    booking.verified_at = clock.now()
    booking.verified_by = (verified_by or "staff")[:64]
    booking.hold_expires_at = None
    session.flush()
    log.info("Booking %s confirmed by %s", booking.ref, booking.verified_by)
    return booking


def reject_payment(
    session: Session,
    booking: Booking,
    verified_by: str = "staff",
    reason: str = "payment not received",
) -> Booking:
    """Staff could not find the payment. Frees the slot for someone else."""
    if booking.status is not BookingStatus.AWAITING_VERIFICATION:
        raise ValueError(
            f"{booking.ref} is {booking.status.value}, not AWAITING_VERIFICATION — "
            f"only a booking awaiting verification can be rejected"
        )
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_reason = reason[:200]
    booking.verified_at = clock.now()
    booking.verified_by = (verified_by or "staff")[:64]
    booking.hold_expires_at = None
    session.flush()
    log.info("Booking %s rejected by %s: %s", booking.ref, booking.verified_by, reason)
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
