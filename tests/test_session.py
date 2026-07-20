"""Conversation session persistence, expiry and timezone correctness."""

from __future__ import annotations

import datetime as dt

from clinic_bot.db.models import ConversationSession
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids
from clinic_bot.flow.states import State
from clinic_bot.scheduling import clock

from .conftest import FROZEN_NOW, PATIENT_WA_ID


def test_session_timestamps_use_the_clinic_clock_not_server_wall_time(bot):
    """Regression: onupdate=datetime.now wrote server-local time into a column
    compared against clinic-timezone time. On a UTC server serving an IST clinic
    that expired every session instantly, breaking every conversation on the
    second tap. All timestamps must come from clock.now()."""
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)

    with session_scope() as db:
        row = db.get(ConversationSession, PATIENT_WA_ID)
        assert row is not None
        assert row.updated_at == FROZEN_NOW, (
            "session timestamp drifted from the frozen clinic clock — a real "
            "clock leaked into the write path"
        )


def test_a_long_conversation_never_self_expires(bot):
    """Every turn writes the same frozen timestamp; none may be treated as stale."""
    bot.say("Hi")
    for _ in range(6):
        out = bot.tap(ids.BTN_BOOK)
        assert not out.contains("timed out")
        assert out.has_button(ids.BTN_BOOK_NEW)


def test_state_survives_between_messages(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)

    with session_scope() as db:
        row = db.get(ConversationSession, PATIENT_WA_ID)
        assert row.state == State.BOOKING_MENU.value


def test_expired_session_restarts_with_an_explanation(bot, cfg):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)

    # Jump past the inactivity window.
    clock.freeze(FROZEN_NOW + dt.timedelta(minutes=cfg.session.timeout_minutes + 5))
    out = bot.tap(ids.BTN_BOOK_NEW)

    assert out.contains("timed out")
    assert out.has_button(ids.BTN_BOOK)


def test_expired_session_still_remembers_the_patient_name(bot):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    bot.say("Sagar Reddy")

    clock.freeze(FROZEN_NOW + dt.timedelta(hours=3))
    out = bot.say("Hi")

    assert out.contains("Sagar Reddy")


def test_two_patients_have_independent_sessions(bot, bot2):
    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_BOOK_NEW)
    bot.say("Patient One")

    # Second patient starts from scratch and must not inherit the first one's name.
    out = bot2.say("Hi")
    assert not out.contains("Patient One")

    bot2.tap(ids.BTN_BOOK)
    out = bot2.tap(ids.BTN_BOOK_NEW)
    assert out.contains("May I have your full name")


def test_corrupt_session_data_does_not_crash(bot):
    bot.say("Hi")

    with session_scope() as db:
        row = db.get(ConversationSession, PATIENT_WA_ID)
        row.data_json = "{not valid json"

    out = bot.say("Hi")
    assert out.has_button(ids.BTN_BOOK)


def test_unknown_state_value_recovers_gracefully(bot):
    bot.say("Hi")

    with session_scope() as db:
        row = db.get(ConversationSession, PATIENT_WA_ID)
        row.state = "STATE_FROM_A_FUTURE_VERSION"

    out = bot.say("anything")
    assert out.has_button(ids.BTN_BOOK)
