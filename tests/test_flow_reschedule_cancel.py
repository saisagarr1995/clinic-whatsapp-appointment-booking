"""Reschedule and Cancel — PROJECT_PLAN.md section 3.1."""

from __future__ import annotations

from sqlalchemy import select

from clinic_bot.db.models import Booking, BookingStatus
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids

from .test_flow_booking import book_fully


def _only_booking():
    with session_scope() as db:
        return db.scalar(select(Booking))


def test_reschedule_with_no_bookings_offers_to_book(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_RESCHEDULE)

    assert out.contains("don't have any upcoming appointments")
    assert out.has_button(ids.BTN_BOOK)


def test_cancel_with_no_bookings_offers_to_book(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_CANCEL)

    assert out.contains("don't have any upcoming appointments")
    assert out.has_button(ids.BTN_BOOK)


def test_reschedule_moves_the_booking_and_keeps_the_reference(bot):
    book_fully(bot)
    bot.tap(ids.BTN_PAID)

    original = _only_booking()
    original_ref, original_start = original.ref, original.starts_at

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_RESCHEDULE)
    assert out.has_row_prefix(ids.P_BOOKING)

    bot.pick_row(ids.P_BOOKING)
    bot.pick_row(ids.P_DATE)
    # index 1: index 0 is the patient's own current slot, which a reschedule
    # deliberately offers back so they can keep it.
    out = bot.pick_row(ids.P_SLOT, index=1)

    assert out.contains("rescheduled")

    moved = _only_booking()
    assert moved.ref == original_ref, "reference must survive a reschedule"
    assert moved.starts_at != original_start
    assert moved.status is BookingStatus.AWAITING_VERIFICATION

    with session_scope() as db:
        assert db.scalar(select(Booking).where(Booking.ref == original_ref)) is not None
        assert len(list(db.scalars(select(Booking)))) == 1, "reschedule must not duplicate"


def test_rescheduling_frees_the_original_slot(bot, bot2):
    book_fully(bot)
    freed = _only_booking().starts_at

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_RESCHEDULE)
    bot.pick_row(ids.P_BOOKING)
    bot.pick_row(ids.P_DATE)
    bot.pick_row(ids.P_SLOT, index=1)  # move away from the original slot

    # A different patient must now be able to take the original time.
    bot2.say("Hi")
    bot2.tap(ids.BTN_BOOK)
    bot2.tap(ids.BTN_BOOK_NEW)
    bot2.say("Second Patient")
    bot2.tap(ids.BTN_VIEW_SERVICES)
    bot2.pick_row(ids.P_SERVICE)
    bot2.pick_row(ids.P_DOCTOR)
    out = bot2.pick_row(ids.P_DATE)

    offered = {r for r in out.row_ids() if r.startswith(ids.P_SLOT)}
    freed_id = ids.make(ids.P_SLOT, freed.strftime("%Y-%m-%dT%H:%M"))
    assert freed_id in offered, "the vacated slot should be bookable again"


def test_reschedule_offers_the_patients_own_slot_back(bot):
    """A patient who opens Reschedule and changes their mind must be able to keep
    their existing time — their own booking must not block itself."""
    book_fully(bot)
    original = _only_booking().starts_at

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_RESCHEDULE)
    bot.pick_row(ids.P_BOOKING)
    out = bot.pick_row(ids.P_DATE)

    own_slot = ids.make(ids.P_SLOT, original.strftime("%Y-%m-%dT%H:%M"))
    assert own_slot in set(out.row_ids())

    out = bot.tap(own_slot)
    assert out.contains("rescheduled")
    assert _only_booking().starts_at == original


def test_cancel_asks_for_confirmation_before_acting(bot):
    book_fully(bot)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_CANCEL)
    out = bot.pick_row(ids.P_BOOKING)

    assert out.contains("Are you sure")
    assert out.has_button(ids.BTN_CANCEL_YES)
    assert out.has_button(ids.BTN_CANCEL_NO)

    # Still active until confirmed.
    assert _only_booking().status is BookingStatus.PENDING_PAYMENT


def test_declining_cancellation_leaves_the_booking_untouched(bot):
    book_fully(bot)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_CANCEL)
    bot.pick_row(ids.P_BOOKING)
    out = bot.tap(ids.BTN_CANCEL_NO)

    assert out.contains("unchanged")
    assert _only_booking().status is BookingStatus.PENDING_PAYMENT


def test_confirming_cancellation_cancels_and_frees_the_slot(bot, bot2):
    book_fully(bot)
    freed = _only_booking().starts_at

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_CANCEL)
    bot.pick_row(ids.P_BOOKING)
    out = bot.tap(ids.BTN_CANCEL_YES)

    assert out.contains("cancelled")
    assert _only_booking().status is BookingStatus.CANCELLED

    bot2.say("Hi")
    bot2.tap(ids.BTN_BOOK)
    bot2.tap(ids.BTN_BOOK_NEW)
    bot2.say("Second Patient")
    bot2.tap(ids.BTN_VIEW_SERVICES)
    bot2.pick_row(ids.P_SERVICE)
    bot2.pick_row(ids.P_DOCTOR)
    out = bot2.pick_row(ids.P_DATE)

    freed_id = ids.make(ids.P_SLOT, freed.strftime("%Y-%m-%dT%H:%M"))
    assert freed_id in set(out.row_ids())


def test_a_patient_cannot_cancel_someone_elses_booking(bot, bot2):
    """Security: booking refs must not be actionable across patients."""
    book_fully(bot)
    victim_ref = _only_booking().ref

    bot2.say("Hi")
    bot2.tap(ids.BTN_BOOK)
    bot2.tap(ids.BTN_CANCEL)
    # Forge a tap carrying the other patient's booking reference.
    out = bot2.tap(ids.make(ids.P_BOOKING, victim_ref))

    assert not out.contains("Are you sure")
    assert _only_booking().status is BookingStatus.PENDING_PAYMENT


def test_cancelled_bookings_disappear_from_the_reschedule_list(bot):
    book_fully(bot)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_CANCEL)
    bot.pick_row(ids.P_BOOKING)
    bot.tap(ids.BTN_CANCEL_YES)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_RESCHEDULE)
    assert out.contains("don't have any upcoming appointments")
