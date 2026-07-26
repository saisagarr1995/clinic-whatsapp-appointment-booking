"""Seed the database from config/clinic.yaml.

Idempotent by design: safe to re-run after editing clinic.yaml. Existing bookings
are never touched. Entities removed from the YAML are deactivated rather than
deleted, so historical bookings keep their foreign keys intact.

Usage:  python -m clinic_bot.db.seed
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from clinic_bot.clinic_config import ClinicConfig, get_clinic_config
from clinic_bot.db.models import Doctor, DoctorSchedule, Service
from clinic_bot.db.session import init_db, session_scope

log = logging.getLogger(__name__)


def _minutes(t) -> int:  # noqa: ANN001 - datetime.time
    return t.hour * 60 + t.minute


def seed_services(session: Session, cfg: ClinicConfig) -> dict[str, Service]:
    by_code: dict[str, Service] = {}
    wanted = {s.code for s in cfg.services}

    for order, svc in enumerate(cfg.services):
        existing = session.scalar(select(Service).where(Service.code == svc.code))
        if existing is None:
            existing = Service(code=svc.code)
            session.add(existing)
        existing.name = svc.name
        existing.fee_from = svc.fee_from
        existing.duration_minutes = svc.duration_minutes
        existing.description = svc.description
        existing.sort_order = order
        existing.active = True
        by_code[svc.code] = existing

    # Deactivate services dropped from the YAML; never delete (bookings reference them).
    for stale in session.scalars(select(Service).where(Service.code.notin_(wanted))):
        stale.active = False

    session.flush()
    return by_code


def seed_doctors(session: Session, cfg: ClinicConfig, services: dict[str, Service]) -> None:
    wanted = {d.code for d in cfg.doctors}

    for order, doc in enumerate(cfg.doctors):
        existing = session.scalar(select(Doctor).where(Doctor.code == doc.code))
        if existing is None:
            existing = Doctor(code=doc.code)
            session.add(existing)
        existing.name = doc.name
        existing.specialization = doc.specialization
        existing.sort_order = order
        existing.active = True

        existing.services = [services[c] for c in doc.services if c in services]

        hours = cfg.doctor_hours(doc)
        brk = hours.brk or cfg.clinic.hours.brk
        session.flush()

        # Rebuild schedules wholesale — they are pure config, no history to preserve.
        existing.schedules.clear()
        session.flush()
        for weekday in sorted(doc.weekday_numbers):
            existing.schedules.append(
                DoctorSchedule(
                    weekday=weekday,
                    start_minute=_minutes(hours.open_time),
                    end_minute=_minutes(hours.close_time),
                    break_start_minute=_minutes(brk.start_time) if brk else None,
                    break_end_minute=_minutes(brk.end_time) if brk else None,
                )
            )

    for stale in session.scalars(select(Doctor).where(Doctor.code.notin_(wanted))):
        stale.active = False

    session.flush()


def seed(cfg: ClinicConfig | None = None, url: str | None = None) -> None:
    """Seed one clinic. `url` selects which database — omit it for the default."""
    cfg = cfg or get_clinic_config()
    init_db(url)
    with session_scope(url) as session:
        services = seed_services(session, cfg)
        seed_doctors(session, cfg, services)
    log.info(
        "Seeded %d services and %d doctors for %s",
        len(cfg.services),
        len(cfg.doctors),
        cfg.clinic.name,
    )


def main() -> None:  # pragma: no cover - CLI entry point
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = get_clinic_config()
    seed(cfg)
    print(
        f"✅ Seeded '{cfg.clinic.name}': "
        f"{len(cfg.services)} services, {len(cfg.doctors)} doctors."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
