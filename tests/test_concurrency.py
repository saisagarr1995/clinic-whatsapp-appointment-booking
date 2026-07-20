"""Double-booking must be impossible. This is the guarantee a clinic cares about most."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from clinic_bot import booking_service as bookings
from clinic_bot.booking_service import SlotTakenError
from clinic_bot.db.models import Booking, BookingStatus, Doctor, Service
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids

from .test_flow_booking import book_fully


def _first(model):
    with session_scope() as db:
        return db.scalar(select(model))


def test_two_patients_cannot_hold_the_same_slot(bot, bot2):
    book_fully(bot)
    taken = _first(Booking).starts_at

    bot2.say("Hi")
    bot2.tap(ids.BTN_BOOK)
    bot2.tap(ids.BTN_BOOK_NEW)
    bot2.say("Second Patient")
    bot2.tap(ids.BTN_VIEW_SERVICES)
    bot2.pick_row(ids.P_SERVICE)
    bot2.pick_row(ids.P_DOCTOR)
    out = bot2.pick_row(ids.P_DATE)

    taken_id = ids.make(ids.P_SLOT, taken.strftime("%Y-%m-%dT%H:%M"))
    assert taken_id not in set(out.row_ids()), "a held slot must not be offered again"


def test_confirming_a_slot_taken_meanwhile_re_offers_the_list(bot, bot2):
    """Patient A reaches the summary; patient B books that slot first."""
    from .test_flow_booking import book_to_summary

    book_to_summary(bot)
    with session_scope() as db:
        pass

    # B books the same doctor/date/slot combination before A taps Confirm.
    bot2.say("Hi")
    bot2.tap(ids.BTN_BOOK)
    bot2.tap(ids.BTN_BOOK_NEW)
    bot2.say("Faster Patient")
    bot2.tap(ids.BTN_VIEW_SERVICES)
    bot2.pick_row(ids.P_SERVICE)
    bot2.pick_row(ids.P_DOCTOR)
    bot2.pick_row(ids.P_DATE)
    bot2.pick_row(ids.P_SLOT)
    bot2.tap(ids.BTN_CONFIRM)

    out = bot.tap(ids.BTN_CONFIRM)

    assert out.contains("just booked by someone else")
    assert out.has_row_prefix(ids.P_SLOT), "must re-offer the remaining slots"

    with session_scope() as db:
        active = list(
            db.scalars(
                select(Booking).where(Booking.status == BookingStatus.PENDING_PAYMENT)
            )
        )
        assert len(active) == 1, "exactly one patient may hold the slot"


def test_database_rejects_a_duplicate_active_slot(cfg):
    """The unique index is the last line of defence, below application logic."""
    with session_scope() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.code == "dr_ramesh"))
        service = db.scalar(select(Service).where(Service.code == "consultation"))
        start = dt.datetime(2026, 8, 3, 11, 0)

        p1 = bookings.get_or_create_patient(db, "911111111111", "One")
        bookings.create_hold(
            db, cfg=cfg, patient=p1, doctor=doctor, service=service,
            start=start, patient_name="One",
        )

        p2 = bookings.get_or_create_patient(db, "922222222222", "Two")
        with pytest.raises(SlotTakenError):
            bookings.create_hold(
                db, cfg=cfg, patient=p2, doctor=doctor, service=service,
                start=start, patient_name="Two",
            )


def test_cancelled_bookings_do_not_block_the_slot(cfg):
    """The unique index is partial — only active statuses occupy a slot."""
    start = dt.datetime(2026, 8, 3, 11, 30)
    with session_scope() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.code == "dr_ramesh"))
        service = db.scalar(select(Service).where(Service.code == "consultation"))

        p1 = bookings.get_or_create_patient(db, "911111111111", "One")
        first = bookings.create_hold(
            db, cfg=cfg, patient=p1, doctor=doctor, service=service,
            start=start, patient_name="One",
        )
        bookings.cancel_booking(db, first)

        p2 = bookings.get_or_create_patient(db, "922222222222", "Two")
        second = bookings.create_hold(
            db, cfg=cfg, patient=p2, doctor=doctor, service=service,
            start=start, patient_name="Two",
        )
        assert second.id != first.id
        assert second.status is BookingStatus.PENDING_PAYMENT


def test_a_long_appointment_blocks_the_overlapping_grid_slot(cfg):
    """A 60-minute service on a 30-minute grid must consume two slots."""
    from clinic_bot.scheduling.slots import available_slots

    start = dt.datetime(2026, 8, 3, 11, 0)
    with session_scope() as db:
        doctor = db.scalar(select(Doctor).where(Doctor.code == "dr_priya"))
        root_canal = db.scalar(select(Service).where(Service.code == "root_canal"))
        assert root_canal.duration_minutes == 60

        patient = bookings.get_or_create_patient(db, "911111111111", "One")
        bookings.create_hold(
            db, cfg=cfg, patient=patient, doctor=doctor, service=root_canal,
            start=start, patient_name="One",
        )

        free = available_slots(
            db, doctor=doctor, service=root_canal, day=start.date(), cfg=cfg
        )
        assert start not in free
        assert start + dt.timedelta(minutes=30) not in free, (
            "the second half of a 60-minute appointment must also be blocked"
        )
        assert start - dt.timedelta(minutes=30) not in free, (
            "a 60-minute booking starting 30 minutes earlier would overlap"
        )
