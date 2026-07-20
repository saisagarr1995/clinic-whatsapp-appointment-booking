"""Persisted conversation state.

Kept in SQLite rather than memory so a restart or a crash never strands a patient
mid-booking — they simply carry on from where they were.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from clinic_bot.clinic_config import ClinicConfig
from clinic_bot.db.models import ConversationSession
from clinic_bot.flow.states import State
from clinic_bot.scheduling import clock

log = logging.getLogger(__name__)


@dataclass
class FlowSession:
    wa_id: str
    state: State = State.IDLE
    data: dict[str, Any] = field(default_factory=dict)
    #: True when the previous session had timed out and was discarded.
    was_expired: bool = False

    # --- typed accessors, so key typos surface in one place ---

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def clear_booking_draft(self) -> None:
        """Reset the booking-in-progress but keep who the patient is."""
        for key in ("service_id", "doctor_id", "date", "slot", "booking_id", "offset"):
            self.data.pop(key, None)

    def reset(self) -> None:
        name = self.data.get("name")
        self.data = {"name": name} if name else {}
        self.state = State.IDLE


def load(session: Session, wa_id: str, cfg: ClinicConfig) -> FlowSession:
    row = session.get(ConversationSession, wa_id)
    if row is None:
        return FlowSession(wa_id=wa_id)

    timeout = dt.timedelta(minutes=cfg.session.timeout_minutes)
    expired = (clock.now() - row.updated_at) > timeout

    try:
        data = json.loads(row.data_json) or {}
    except (json.JSONDecodeError, TypeError):
        log.warning("Corrupt session data for %s; starting fresh", wa_id)
        data = {}

    if expired:
        # Keep the remembered name so a returning patient is greeted properly.
        name = data.get("name")
        return FlowSession(
            wa_id=wa_id,
            state=State.IDLE,
            data={"name": name} if name else {},
            was_expired=True,
        )

    try:
        state = State(row.state)
    except ValueError:
        log.warning("Unknown state %r for %s; starting fresh", row.state, wa_id)
        state = State.IDLE

    return FlowSession(wa_id=wa_id, state=state, data=data)


def save(session: Session, flow: FlowSession) -> None:
    row = session.get(ConversationSession, flow.wa_id)
    now = clock.now()
    if row is None:
        row = ConversationSession(wa_id=flow.wa_id)
        session.add(row)
    row.state = flow.state.value
    row.data_json = json.dumps(flow.data, default=str)
    row.updated_at = now
    session.flush()
