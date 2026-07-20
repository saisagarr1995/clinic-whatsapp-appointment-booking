"""Availability engine unit tests."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from clinic_bot.db.models import Doctor, Service
from clinic_bot.db.session import session_scope
from clinic_bot.scheduling import clock
from clinic_bot.scheduling.slots import (
    _working_windows,
    available_dates,
    available_slots,
    doctors_for_service,
)

from .conftest import FROZEN_NOW

MONDAY = dt.date(2026, 8, 3)
SUNDAY = dt.date(2026, 8, 9)


def _get(db, model, code):
    return db.scalar(select(model).where(model.code == code))


def test_doctors_are_filtered_by_the_service_they_provide():
    with session_scope() as db:
        braces = _get(db, Service, "braces")
        names = {d.code for d in doctors_for_service(db, braces.id)}
        assert names == {"dr_arjun"}

        consultation = _get(db, Service, "consultation")
        names = {d.code for d in doctors_for_service(db, consultation.id)}
        assert names == {"dr_ramesh", "dr_priya", "dr_arjun", "dr_meera"}


def test_lunch_break_is_excluded(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_ramesh")
        service = _get(db, Service, "consultation")
        free = available_slots(db, doctor=doctor, service=service, day=MONDAY, cfg=cfg)

        times = {s.strftime("%H:%M") for s in free}
        # Break is 13:30-14:30 in clinic.yaml.
        assert "13:30" not in times
        assert "14:00" not in times
        assert "14:30" in times


def test_slots_stop_before_the_doctors_closing_time(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_ramesh")  # works 09:00-17:00
        service = _get(db, Service, "consultation")  # 30 minutes
        free = available_slots(db, doctor=doctor, service=service, day=MONDAY, cfg=cfg)

        assert max(free).strftime("%H:%M") == "16:30"


def test_a_longer_service_ends_earlier_in_the_day(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_priya")  # 10:00-18:00
        root_canal = _get(db, Service, "root_canal")  # 60 minutes
        free = available_slots(db, doctor=doctor, service=root_canal, day=MONDAY, cfg=cfg)

        # A 60-minute appointment cannot start at 17:30.
        assert max(free).strftime("%H:%M") == "17:00"


def test_minimum_notice_hides_imminent_slots(cfg):
    """Frozen now is Monday 09:00 and min notice is 60 minutes."""
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_ramesh")
        service = _get(db, Service, "consultation")
        free = available_slots(db, doctor=doctor, service=service, day=MONDAY, cfg=cfg)

        assert min(free).strftime("%H:%M") == "10:00"


def test_a_non_working_day_yields_nothing(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_priya")  # mon, wed, fri, sat only
        service = _get(db, Service, "consultation")

        tuesday = MONDAY + dt.timedelta(days=1)
        assert available_slots(db, doctor=doctor, service=service, day=tuesday, cfg=cfg) == []
        assert available_slots(db, doctor=doctor, service=service, day=SUNDAY, cfg=cfg) == []


def test_available_dates_only_contain_working_days(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_arjun")  # tue, thu, sat
        service = _get(db, Service, "consultation")
        dates = available_dates(db, doctor=doctor, service=service, cfg=cfg)

        assert dates, "expected at least one available date"
        assert all(d.weekday() in {1, 3, 5} for d in dates)


def test_available_dates_respect_the_booking_horizon(cfg):
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_ramesh")
        service = _get(db, Service, "consultation")
        dates = available_dates(db, doctor=doctor, service=service, cfg=cfg)

        horizon = clock.today() + dt.timedelta(days=cfg.booking.advance_days)
        assert all(clock.today() <= d <= horizon for d in dates)


def test_a_fully_past_day_offers_nothing(cfg):
    """Late in the evening, today must drop out rather than offer stale times."""
    clock.freeze(FROZEN_NOW.replace(hour=23, minute=0))
    with session_scope() as db:
        doctor = _get(db, Doctor, "dr_ramesh")
        service = _get(db, Service, "consultation")
        assert available_slots(db, doctor=doctor, service=service, day=MONDAY, cfg=cfg) == []


class _Schedule:
    def __init__(self, start, end, bs=None, be=None):
        self.start_minute, self.end_minute = start, end
        self.break_start_minute, self.break_end_minute = bs, be


def test_working_windows_split_around_a_break():
    assert _working_windows(_Schedule(540, 1020, 810, 870)) == [(540, 810), (870, 1020)]


def test_working_windows_without_a_break_are_contiguous():
    assert _working_windows(_Schedule(540, 1020)) == [(540, 1020)]


def test_break_outside_working_hours_is_ignored():
    assert _working_windows(_Schedule(540, 720, 810, 870)) == [(540, 720)]
