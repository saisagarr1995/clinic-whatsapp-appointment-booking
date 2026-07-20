"""Welcome / Our Services / Contact Us — PROJECT_PLAN.md section 3.1, top block."""

from __future__ import annotations

import pytest

from clinic_bot.flow import ids
from clinic_bot.whatsapp.base import BODY_MAX, ButtonMessage, ListMessage, TextMessage


def test_hi_returns_welcome_with_exactly_three_buttons(bot, cfg):
    out = bot.say("Hi")

    assert len(out.sent) == 1
    msg = out.sent[0]
    assert isinstance(msg, ButtonMessage)
    assert [b.id for b in msg.buttons] == [ids.BTN_BOOK, ids.BTN_SERVICES, ids.BTN_CONTACT]
    assert [b.title for b in msg.buttons] == [
        "Book Appointment",
        "Our Services",
        "Contact Us",
    ]
    assert cfg.clinic.name in msg.body


@pytest.mark.parametrize("greeting", ["Hi", "hello", "HELLO", "hey", "menu", "start", "Namaste"])
def test_reset_keywords_all_open_the_welcome_menu(bot, greeting):
    out = bot.say(greeting)
    assert out.has_button(ids.BTN_BOOK)


def test_our_services_lists_every_service_with_fee_and_timings(bot, cfg):
    bot.say("Hi")
    out = bot.tap(ids.BTN_SERVICES)

    body = out.all_text()
    for service in cfg.services:
        assert service.name in body, f"{service.name} missing from the services message"
        assert f"{service.fee_from:,}".replace(",", ",") in body or str(service.fee_from) in body

    # Clinic opening hours must be shown alongside the fees.
    assert "9:00 AM" in body
    assert "8:00 PM" in body
    assert "Lunch break" in body

    # And it must end with a Book Appointment nudge.
    assert out.has_button(ids.BTN_BOOK)


def test_services_overview_never_exceeds_whatsapp_body_limit(bot):
    """Long service lists must be split across messages, not silently truncated."""
    bot.say("Hi")
    out = bot.tap(ids.BTN_SERVICES)

    for msg in out.sent:
        if isinstance(msg, TextMessage | ButtonMessage):
            assert len(msg.body) <= BODY_MAX
    # Nothing was clipped with an ellipsis.
    assert "…" not in out.all_text()


def test_contact_us_shows_phone_address_and_book_button(bot, cfg):
    bot.say("Hi")
    out = bot.tap(ids.BTN_CONTACT)

    body = out.all_text()
    assert cfg.clinic.phone in body
    assert cfg.clinic.address in body
    assert out.has_button(ids.BTN_BOOK)


def test_book_appointment_opens_the_three_option_menu(bot):
    bot.say("Hi")
    out = bot.tap(ids.BTN_BOOK)

    msg = out.sent[0]
    assert isinstance(msg, ButtonMessage)
    assert [b.id for b in msg.buttons] == [
        ids.BTN_BOOK_NEW,
        ids.BTN_RESCHEDULE,
        ids.BTN_CANCEL,
    ]
    assert [b.title for b in msg.buttons] == ["Book New", "Reschedule", "Cancel"]


def test_book_appointment_reachable_directly_from_services(bot):
    """The nudge under Our Services must actually work."""
    bot.say("Hi")
    bot.tap(ids.BTN_SERVICES)
    out = bot.tap(ids.BTN_BOOK)
    assert out.has_button(ids.BTN_BOOK_NEW)


def test_unrecognised_input_never_dead_ends(bot):
    bot.say("Hi")
    out = bot.say("asdkjhaskdjh")

    assert out.contains("didn't quite catch that")
    # A nudge alone is useless — the menu must come with it.
    assert out.has_button(ids.BTN_BOOK)


def test_every_list_message_respects_the_ten_row_limit(bot):
    """WhatsApp rejects lists with more than 10 rows outright."""
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    bot.say("Sagar Reddy")
    out = bot.tap(ids.BTN_VIEW_SERVICES)

    for msg in out.sent:
        if isinstance(msg, ListMessage):
            assert sum(len(s.rows) for s in msg.sections) <= 10
