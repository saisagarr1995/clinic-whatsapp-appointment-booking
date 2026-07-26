"""Book New, end to end — PROJECT_PLAN.md section 3.1."""

from __future__ import annotations

from sqlalchemy import select

from clinic_bot.db.models import Booking, BookingStatus
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids
from clinic_bot.whatsapp.base import ButtonMessage, ListMessage

from .conftest import CLINIC_SLUG

PATIENT_NAME = "Sagar Reddy"


def start_booking(bot, name: str = PATIENT_NAME):
    """Drive as far as the service list and return the last adapter."""
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    bot.say(name)
    return bot.tap(ids.BTN_VIEW_SERVICES)


def book_to_summary(bot, name: str = PATIENT_NAME):
    start_booking(bot, name)
    bot.pick_row(ids.P_SERVICE)
    bot.pick_row(ids.P_DOCTOR)
    bot.pick_row(ids.P_DATE)
    return bot.pick_row(ids.P_SLOT)


def book_fully(bot, name: str = PATIENT_NAME):
    book_to_summary(bot, name)
    return bot.tap(ids.BTN_CONFIRM)


# --------------------------------------------------------------------------
# Step-by-step copy contract
# --------------------------------------------------------------------------


def test_book_new_asks_for_the_full_name_with_the_specified_wording(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_BOOK_NEW)

    texts = out.texts()
    assert len(texts) == 2, "expected two separate messages"
    assert "Great! Let's get you booked in" in texts[0]
    assert "May I have your full name please?" in texts[1]


def test_name_is_echoed_back_with_a_view_services_button(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    out = bot.say(PATIENT_NAME)

    assert out.contains(f"Thank you, *{PATIENT_NAME}*")
    assert out.contains("Which service do you need today?")
    assert out.has_button(ids.BTN_VIEW_SERVICES)


def test_view_services_opens_a_selectable_list(bot, cfg):
    out = start_booking(bot)

    lists = [m for m in out.sent if isinstance(m, ListMessage)]
    assert len(lists) == 1
    assert out.has_row_prefix(ids.P_SERVICE)
    # Fees appear in the row descriptions so the patient can choose informed.
    assert any("From ₹" in r.description for s in lists[0].sections for r in s.rows)


def test_choosing_a_service_shows_only_doctors_who_provide_it(bot, cfg):
    start_booking(bot)
    out = bot.pick_row(ids.P_SERVICE)

    assert out.has_row_prefix(ids.P_DOCTOR)
    titles = out.row_titles()

    # First service is "General Consultation", which every seeded doctor provides.
    consult_doctors = {d.name for d in cfg.doctors if "consultation" in d.services}
    assert set(titles) <= {d.name for d in cfg.doctors}
    assert set(titles) == consult_doctors


def test_choosing_a_doctor_shows_dates_then_slots(bot):
    start_booking(bot)
    bot.pick_row(ids.P_SERVICE)
    out = bot.pick_row(ids.P_DOCTOR)
    assert out.has_row_prefix(ids.P_DATE)

    out = bot.pick_row(ids.P_DATE)
    assert out.has_row_prefix(ids.P_SLOT)


def test_min_notice_is_respected(bot):
    """Frozen now is 09:00 with a 60-minute notice rule, so 09:00/09:30 must not appear."""
    start_booking(bot)
    bot.pick_row(ids.P_SERVICE)
    bot.pick_row(ids.P_DOCTOR)
    out = bot.pick_row(ids.P_DATE)

    today_slots = [r for r in out.row_ids() if r.startswith(ids.P_SLOT)]
    if today_slots:  # only meaningful when the first offered date is today
        first = today_slots[0]
        assert not first.endswith("T09:00")
        assert not first.endswith("T09:30")


def test_summary_shows_every_detail_and_two_buttons(bot, cfg):
    out = book_to_summary(bot)

    msg = out.sent[-1]
    assert isinstance(msg, ButtonMessage)
    assert [b.id for b in msg.buttons] == [ids.BTN_CONFIRM, ids.BTN_CHANGE]
    assert [b.title for b in msg.buttons] == ["Confirm", "Change Details"]

    body = msg.body
    assert PATIENT_NAME in body
    assert "Booking Summary" in body
    for label in ("Patient:", "Service:", "Doctor:", "Date:", "Time:"):
        assert label in body, f"summary missing {label}"
    assert str(cfg.payment.advance_amount) in body


# --------------------------------------------------------------------------
# Confirm and payment
# --------------------------------------------------------------------------


def test_confirm_creates_a_pending_booking_and_sends_upi_details(bot, cfg):
    out = book_fully(bot)

    with session_scope() as db:
        booking = db.scalar(select(Booking))
        assert booking is not None
        assert booking.status is BookingStatus.PENDING_PAYMENT
        assert booking.patient_name == PATIENT_NAME
        assert booking.amount == cfg.payment.advance_amount
        assert booking.hold_expires_at is not None
        ref = booking.ref

    # No image is sent — the UPI QR was dropped (PROJECT_PLAN D4, 2026-07-26).
    assert out.images() == []

    body = out.all_text()
    assert cfg.payment.upi_id in body
    assert cfg.payment.upi_name in body
    assert ref in body
    # The payment link must carry this clinic's own prefix, so a patient of one
    # clinic can never be sent to another clinic's page.
    assert f"/c/{CLINIC_SLUG}/pay/{ref}" in body

    assert out.has_button(ids.BTN_PAID)
    assert out.has_button(ids.BTN_HELP)


def test_ive_paid_moves_to_awaiting_verification_and_greets(bot):
    book_fully(bot)
    out = bot.tap(ids.BTN_PAID)

    with session_scope() as db:
        booking = db.scalar(select(Booking))
        assert booking.status is BookingStatus.AWAITING_VERIFICATION
        assert booking.paid_declared_at is not None
        assert booking.hold_expires_at is None

    body = out.all_text()
    assert "Thank you" in body
    assert PATIENT_NAME in body


def test_need_help_shows_the_clinic_number(bot, cfg):
    book_fully(bot)
    out = bot.tap(ids.BTN_HELP)

    assert cfg.clinic.phone in out.all_text()
    # The patient must still be able to declare payment afterwards.
    assert out.has_button(ids.BTN_PAID)

    out = bot.tap(ids.BTN_PAID)
    assert "Thank you" in out.all_text()


# --------------------------------------------------------------------------
# Change Details
# --------------------------------------------------------------------------


def test_change_details_returns_to_service_choice_and_keeps_the_name(bot):
    book_to_summary(bot)
    out = bot.tap(ids.BTN_CHANGE)

    assert out.contains(f"Thank you, *{PATIENT_NAME}*")
    assert out.has_button(ids.BTN_VIEW_SERVICES)

    # No booking may have been created by backing out.
    with session_scope() as db:
        assert db.scalar(select(Booking)) is None


def test_change_details_then_rebooking_works(bot):
    book_to_summary(bot)
    bot.tap(ids.BTN_CHANGE)

    bot.tap(ids.BTN_VIEW_SERVICES)
    bot.pick_row(ids.P_SERVICE, index=1)
    bot.pick_row(ids.P_DOCTOR)
    bot.pick_row(ids.P_DATE)
    bot.pick_row(ids.P_SLOT)
    out = bot.tap(ids.BTN_CONFIRM)

    assert out.has_button(ids.BTN_PAID)
    with session_scope() as db:
        assert db.scalar(select(Booking)) is not None


def test_returning_patient_is_not_asked_for_their_name_again(bot):
    book_fully(bot)
    bot.tap(ids.BTN_PAID)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    out = bot.tap(ids.BTN_BOOK_NEW)

    assert not out.contains("May I have your full name")
    assert out.has_button(ids.BTN_VIEW_SERVICES)


# --------------------------------------------------------------------------
# Name validation
# --------------------------------------------------------------------------


def test_too_short_name_is_rejected_and_reprompted(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)

    out = bot.say("A")
    assert out.contains("short")

    out = bot.say("12345")
    assert out.contains("letters only")

    out = bot.say("Valid Name")
    assert out.has_button(ids.BTN_VIEW_SERVICES)


def test_name_whitespace_is_normalised(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    out = bot.say("  Sagar    Reddy  ")
    assert out.contains("Thank you, *Sagar Reddy*")
