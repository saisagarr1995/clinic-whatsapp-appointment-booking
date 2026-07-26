"""Single source of "now".

Every part of the app asks this module for the time so that tests can freeze it.
Returns NAIVE datetimes in the clinic's local timezone — see the note in db/models.py.

FLEET CAVEAT
------------
This module is process-wide, not per clinic: it reads the timezone from the
default clinic config. That is safe only because `registry.load_registry`
refuses to start when enabled clinics disagree on their timezone, so every
clinic in one process shares one local time. If per-clinic timezones are ever
needed, `now()` must take the clinic as an argument and every caller must pass
it — do not quietly relax the registry check instead.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

_frozen: dt.datetime | None = None


def _clinic_zone() -> ZoneInfo | None:
    """The clinic's timezone, or None to fall back to system local time.

    A missing timezone is NOT silently acceptable: it means every appointment
    time could be wrong. It is validated up front by `ClinicInfo.timezone`, so
    reaching the fallback here means something changed under a running process.
    We log loudly rather than raise, because crashing mid-conversation would
    strand a patient — but the log is the signal that times cannot be trusted.
    """
    from clinic_bot.clinic_config import ConfigError, get_clinic_config

    try:
        return ZoneInfo(get_clinic_config().clinic.timezone)
    except ZoneInfoNotFoundError:
        log.error(
            "TIME ZONE DATABASE MISSING — appointment times are being computed in "
            "this machine's local time, which may be wrong. Install it with: "
            "pip install tzdata"
        )
        return None
    except (ConfigError, ValueError, OSError):
        log.error("Could not resolve the clinic timezone; using system local time")
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
