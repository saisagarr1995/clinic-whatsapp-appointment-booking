"""Single source of "now".

Every part of the app asks this module for the time so that tests can freeze it.
Returns NAIVE datetimes in the clinic's local timezone — see the note in db/models.py.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_frozen: dt.datetime | None = None


def _clinic_zone() -> ZoneInfo | None:
    from clinic_bot.clinic_config import get_clinic_config

    try:
        return ZoneInfo(get_clinic_config().clinic.timezone)
    except (ZoneInfoNotFoundError, Exception):  # noqa: B014 - config may be unavailable
        return None


def now() -> dt.datetime:
    """Current local clinic time, naive."""
    if _frozen is not None:
        return _frozen
    zone = _clinic_zone()
    if zone is None:
        return dt.datetime.now()
    return dt.datetime.now(zone).replace(tzinfo=None)


def today() -> dt.date:
    return now().date()


def freeze(when: dt.datetime | None) -> None:
    """Test helper. Pass None to unfreeze."""
    global _frozen
    _frozen = when
