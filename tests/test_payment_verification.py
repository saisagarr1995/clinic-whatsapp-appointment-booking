"""Staff payment verification — the only path to CONFIRMED.

There is no payment gateway, so no code here can observe that money moved.
"I've Paid" is a patient claim. These tests pin down the consequences of that:
a claim must never confirm a booking by itself, a human must be able to confirm
or reject it, and rejecting must free the slot.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from clinic_bot import booking_service as bookings
from clinic_bot.db.models import BLOCKING_STATUSES, Booking, BookingStatus
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids
from clinic_bot.scheduling import clock

from .test_flow_booking import book_fully


def _booking() -> Booking:
    with session_scope() as db:
        return db.scalar(select(Booking))


def _declare(bot, utr: str = "123456789012"):
    """Drive a patient all the way through declaring payment."""
    book_fully(bot)
    bot.tap(ids.BTN_PAID)
    bot.say(utr)


# --------------------------------------------------------------------------
# A claim is not a payment
# --------------------------------------------------------------------------


def test_declaring_payment_does_not_confirm_the_booking(bot):
    _declare(bot)
    assert _booking().status is BookingStatus.AWAITING_VERIFICATION


def test_nothing_in_the_patient_flow_can_reach_confirmed(bot):
    """CONFIRMED must be unreachable from WhatsApp, whatever the patient taps."""
    _declare(bot)
    for payload in (ids.BTN_PAID, ids.BTN_SKIP_UTR, ids.BTN_CONFIRM, ids.BTN_HELP):
        bot.tap(payload)
        assert _booking().status is not BookingStatus.CONFIRMED


def test_an_unverified_claim_still_holds_the_slot(bot):
    """Deliberate: a patient who really paid must not lose their slot."""
    _declare(bot)
    booking = _booking()
    assert booking.status in BLOCKING_STATUSES
    assert booking.hold_expires_at is None


def test_an_unverified_claim_is_not_swept_away_by_the_hold_expiry(bot):
    _declare(bot)
    with session_scope() as db:
        clock.freeze(clock.now() + dt.timedelta(days=2))
        released = bookings.expire_stale_holds(db)
    assert released == 0
    assert _booking().status is BookingStatus.AWAITING_VERIFICATION


# --------------------------------------------------------------------------
# The staff queue
# --------------------------------------------------------------------------


def test_pending_verification_lists_the_declared_booking(bot):
    _declare(bot)
    with session_scope() as db:
        pending = bookings.pending_verification(db)
        assert len(pending) == 1
        assert pending[0].payment_ref == "123456789012"


def test_pending_verification_is_oldest_first(bot, bot2):
    _declare(bot, "111111111111")
    clock.freeze(clock.now() + dt.timedelta(hours=1))
    _declare(bot2, "222222222222")

    with session_scope() as db:
        refs = [b.payment_ref for b in bookings.pending_verification(db)]
    assert refs == ["111111111111", "222222222222"], "the longest wait must come first"


def test_a_paid_booking_leaves_the_queue_once_confirmed(bot):
    _declare(bot)
    with session_scope() as db:
        bookings.confirm_booking(db, bookings.pending_verification(db)[0], verified_by="reception")
    with session_scope() as db:
        assert bookings.pending_verification(db) == []


# --------------------------------------------------------------------------
# Confirm
# --------------------------------------------------------------------------


def test_confirming_records_who_and_when(bot):
    _declare(bot)
    with session_scope() as db:
        bookings.confirm_booking(db, db.scalar(select(Booking)), verified_by="reception")

    booking = _booking()
    assert booking.status is BookingStatus.CONFIRMED
    assert booking.verified_by == "reception"
    assert booking.verified_at is not None


def test_a_confirmed_booking_still_occupies_its_slot(bot):
    _declare(bot)
    with session_scope() as db:
        bookings.confirm_booking(db, db.scalar(select(Booking)))
    assert _booking().status in BLOCKING_STATUSES


@pytest.mark.parametrize(
    "status", [BookingStatus.PENDING_PAYMENT, BookingStatus.CANCELLED, BookingStatus.EXPIRED]
)
def test_only_a_booking_awaiting_verification_can_be_confirmed(bot, status):
    """Guards against confirming a cancelled or unpaid booking by mistake."""
    book_fully(bot)
    with session_scope() as db:
        booking = db.scalar(select(Booking))
        booking.status = status
        db.flush()
        with pytest.raises(ValueError, match="AWAITING_VERIFICATION"):
            bookings.confirm_booking(db, booking)


# --------------------------------------------------------------------------
# Reject
# --------------------------------------------------------------------------


def test_rejecting_cancels_the_booking_and_frees_the_slot(bot):
    _declare(bot)
    taken = _booking().starts_at

    with session_scope() as db:
        bookings.reject_payment(db, db.scalar(select(Booking)), reason="no matching UPI credit")

    booking = _booking()
    assert booking.status is BookingStatus.CANCELLED
    assert booking.status not in BLOCKING_STATUSES, "the slot must be bookable again"
    assert booking.cancelled_reason == "no matching UPI credit"
    assert booking.starts_at == taken


def test_a_rejected_slot_can_be_booked_by_someone_else(bot, bot2):
    _declare(bot)
    original = _booking()
    slot, doctor_id = original.starts_at, original.doctor_id

    with session_scope() as db:
        bookings.reject_payment(db, db.scalar(select(Booking)))

    book_fully(bot2)

    with session_scope() as db:
        live = list(
            db.scalars(
                select(Booking).where(
                    Booking.doctor_id == doctor_id,
                    Booking.starts_at == slot,
                    Booking.status.in_(BLOCKING_STATUSES),
                )
            )
        )
    assert len(live) == 1, "exactly one live booking may hold a freed slot"


def test_only_a_booking_awaiting_verification_can_be_rejected(bot):
    book_fully(bot)
    with session_scope() as db, pytest.raises(ValueError, match="AWAITING_VERIFICATION"):
        bookings.reject_payment(db, db.scalar(select(Booking)))


# --------------------------------------------------------------------------
# The UPI reference itself
# --------------------------------------------------------------------------


def test_payment_ref_is_truncated_not_trusted(bot):
    """Patient-supplied text — it is stored for a human to read, nothing more."""
    _declare(bot)
    with session_scope() as db:
        bookings.record_payment_ref(db, db.scalar(select(Booking)), "9" * 100)
    assert len(_booking().payment_ref) == 32
