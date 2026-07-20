"""Availability computation.

Slots sit on a fixed grid of `booking.slot_minutes`, but an appointment occupies
the *service's* duration. A 60-minute root canal booked at 10:00 therefore blocks
10:00 and 10:30 on a 30-minute grid — computed by overlap, not by exact-start
comparison.

CONCURRENCY
-----------
Two guarantees, at different layers:
  1. DB partial unique index on (doctor_id, starts_at) — makes identical-start
     double booking impossible even under concurrent webhook deliveries.
  2. Overlap filtering here — hides slots that would collide with a longer
     appointment already booked.
A residual race exists for *overlapping but non-identical* starts booked in the
same instant. It is rare (both patients must confirm within the same moment for
the same doctor) and self-heals: the clinic sees both in the day list. Closing it
fully needs row locking that SQLite does not offer; documented rather than hidden.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from clinic_bot.clinic_config import ClinicConfig
from clinic_bot.db.models import BLOCKING_STATUSES, Booking, Doctor, DoctorSchedule, Service
from clinic_bot.scheduling import clock


def doctors_for_service(session: Session, service_id: int) -> list[Doctor]:
    """Active doctors who provide the given service, in configured order."""
    service = session.get(Service, service_id)
    if service is None:
        return []
    return sorted(
        (d for d in service.doctors if d.active),
        key=lambda d: (d.sort_order, d.name),
    )


def _schedule_for(doctor: Doctor, weekday: int) -> DoctorSchedule | None:
    return next((s for s in doctor.schedules if s.weekday == weekday), None)


def _working_windows(schedule: DoctorSchedule) -> list[tuple[int, int]]:
    """Working minute-ranges for the day, with the lunch break removed."""
    start, end = schedule.start_minute, schedule.end_minute
    bs, be = schedule.break_start_minute, schedule.break_end_minute

    if bs is None or be is None or be <= start or bs >= end:
        return [(start, end)]

    windows: list[tuple[int, int]] = []
    if bs > start:
        windows.append((start, min(bs, end)))
    if be < end:
        windows.append((max(be, start), end))
    return [(a, b) for a, b in windows if b > a]


def _candidate_starts(
    schedule: DoctorSchedule, day: dt.date, *, grid_minutes: int, duration_minutes: int
) -> list[dt.datetime]:
    """Grid-aligned starts that fit entirely inside a working window."""
    out: list[dt.datetime] = []
    midnight = dt.datetime.combine(day, dt.time.min)
    for window_start, window_end in _working_windows(schedule):
        minute = window_start
        while minute + duration_minutes <= window_end:
            out.append(midnight + dt.timedelta(minutes=minute))
            minute += grid_minutes
    return out


def _blocking_bookings(
    session: Session, doctor_id: int, start: dt.datetime, end: dt.datetime
) -> list[tuple[dt.datetime, dt.datetime]]:
    """(starts_at, ends_at) of slot-occupying bookings overlapping [start, end)."""
    rows = session.execute(
        select(Booking.starts_at, Booking.ends_at).where(
            Booking.doctor_id == doctor_id,
            Booking.status.in_(BLOCKING_STATUSES),
            Booking.starts_at < end,
            Booking.ends_at > start,
        )
    ).all()
    return [(r[0], r[1]) for r in rows]


def _overlaps(
    start: dt.datetime, end: dt.datetime, busy: Iterable[tuple[dt.datetime, dt.datetime]]
) -> bool:
    return any(start < b_end and end > b_start for b_start, b_end in busy)


def available_slots(
    session: Session,
    *,
    doctor: Doctor,
    service: Service,
    day: dt.date,
    cfg: ClinicConfig,
    exclude_booking_id: int | None = None,
) -> list[dt.datetime]:
    """Free start times for this doctor/service/day, earliest first.

    `exclude_booking_id` lets a reschedule ignore the booking being moved, so a
    patient can keep their existing slot if they change their mind.
    """
    schedule = _schedule_for(doctor, day.weekday())
    if schedule is None:
        return []

    duration = max(service.duration_minutes, cfg.booking.slot_minutes)
    candidates = _candidate_starts(
        schedule,
        day,
        grid_minutes=cfg.booking.slot_minutes,
        duration_minutes=duration,
    )
    if not candidates:
        return []

    earliest = clock.now() + dt.timedelta(minutes=cfg.booking.min_notice_minutes)
    day_start = dt.datetime.combine(day, dt.time.min)
    day_end = day_start + dt.timedelta(days=1)

    busy = _blocking_bookings(session, doctor.id, day_start, day_end)
    if exclude_booking_id is not None:
        excluded = session.get(Booking, exclude_booking_id)
        if excluded is not None:
            busy = [
                b
                for b in busy
                if not (b[0] == excluded.starts_at and b[1] == excluded.ends_at)
            ]

    free: list[dt.datetime] = []
    for start in candidates:
        if start < earliest:
            continue
        end = start + dt.timedelta(minutes=duration)
        if _overlaps(start, end, busy):
            continue
        free.append(start)
    return free


def available_dates(
    session: Session,
    *,
    doctor: Doctor,
    service: Service,
    cfg: ClinicConfig,
    exclude_booking_id: int | None = None,
    limit: int | None = None,
) -> list[dt.date]:
    """Dates within the booking horizon that have at least one free slot."""
    today = clock.today()
    horizon = cfg.booking.advance_days
    working_days = {s.weekday for s in doctor.schedules}

    out: list[dt.date] = []
    for offset in range(horizon + 1):
        day = today + dt.timedelta(days=offset)
        if day.weekday() not in working_days:
            continue
        if available_slots(
            session,
            doctor=doctor,
            service=service,
            day=day,
            cfg=cfg,
            exclude_booking_id=exclude_booking_id,
        ):
            out.append(day)
            if limit is not None and len(out) >= limit:
                break
    return out


def slot_is_free(
    session: Session,
    *,
    doctor: Doctor,
    service: Service,
    start: dt.datetime,
    cfg: ClinicConfig,
    exclude_booking_id: int | None = None,
) -> bool:
    """Re-check at confirmation time — the slot may have gone since it was listed."""
    return start in set(
        available_slots(
            session,
            doctor=doctor,
            service=service,
            day=start.date(),
            cfg=cfg,
            exclude_booking_id=exclude_booking_id,
        )
    )


def booking_end(start: dt.datetime, service: Service, cfg: ClinicConfig) -> dt.datetime:
    duration = max(service.duration_minutes, cfg.booking.slot_minutes)
    return start + dt.timedelta(minutes=duration)
