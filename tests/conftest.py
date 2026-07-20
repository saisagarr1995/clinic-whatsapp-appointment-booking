"""Shared test fixtures.

Every test runs against a fresh temporary SQLite database seeded from the real
config/clinic.yaml, with time frozen, so results are deterministic and the suite
never touches the developer's working database.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterator

import pytest

from clinic_bot.clinic_config import get_clinic_config, load_clinic_config
from clinic_bot.db.seed import seed
from clinic_bot.db.session import reset_engine, session_scope
from clinic_bot.flow.router import Router
from clinic_bot.scheduling import clock
from clinic_bot.settings import get_settings
from clinic_bot.whatsapp.base import InboundMessage, Reply
from clinic_bot.whatsapp.fake import FakeAdapter

#: Monday 2026-08-03, 09:00. Chosen so that "today" is a working day for every
#: seeded doctor and the min-notice window pushes the first slot to 10:00.
FROZEN_NOW = dt.datetime(2026, 8, 3, 9, 0)

PATIENT_WA_ID = "919812345678"


@pytest.fixture(autouse=True)
def _frozen_clock() -> Iterator[None]:
    clock.freeze(FROZEN_NOW)
    yield
    clock.freeze(None)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch) -> Iterator[None]:
    """Point the app at a throwaway database and QR directory."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    monkeypatch.setenv("CLINIC_CONFIG_PATH", "config/clinic.yaml")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://test.example.com")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-access-token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1234567890")
    monkeypatch.setenv("TESTING", "true")

    # QR files must not leak into the repo's data/ directory.
    from clinic_bot.payments import qr as qr_module

    monkeypatch.setattr(qr_module, "QR_DIR", tmp_path / "qrcodes")

    get_settings.cache_clear()
    get_clinic_config.cache_clear()
    reset_engine()

    seed(load_clinic_config("config/clinic.yaml"))
    yield

    reset_engine()
    get_settings.cache_clear()
    get_clinic_config.cache_clear()


@pytest.fixture
def cfg():
    return get_clinic_config()


@pytest.fixture
def adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture
def router(cfg) -> Router:
    return Router(cfg, get_settings())


class Bot:
    """Drives a whole conversation through the router with no network.

    Each call returns the FakeAdapter holding ONLY the messages produced by that
    turn, so assertions stay scoped to one step.
    """

    _ids = itertools.count(1)

    def __init__(self, router: Router, wa_id: str = PATIENT_WA_ID, profile_name: str = "Test"):
        self.router = router
        self.wa_id = wa_id
        self.profile_name = profile_name
        self.adapter = FakeAdapter()
        self.history: list[Reply] = []

    def _inbound(self, text: str = "", reply_id: str | None = None) -> InboundMessage:
        return InboundMessage(
            wa_id=self.wa_id,
            message_id=f"wamid.test.{next(Bot._ids)}",
            profile_name=self.profile_name,
            text=text,
            reply_id=reply_id,
        )

    def _run(self, inbound: InboundMessage) -> FakeAdapter:
        self.adapter.clear()
        with session_scope() as db:
            reply = self.router.handle(db, inbound)
        self.history.append(reply)
        self.adapter.send_all(reply)
        return self.adapter

    def say(self, text: str) -> FakeAdapter:
        """Patient types a message."""
        return self._run(self._inbound(text=text))

    def tap(self, reply_id: str) -> FakeAdapter:
        """Patient taps a button or selects a list row."""
        return self._run(self._inbound(reply_id=reply_id))

    def pick_row(self, prefix: str, index: int = 0) -> FakeAdapter:
        """Select the Nth row whose id starts with `prefix` from the last message."""
        matching = [r for r in self.adapter.row_ids() if r.startswith(prefix)]
        assert matching, (
            f"no rows with prefix {prefix!r} in the last reply; "
            f"available row ids: {self.adapter.row_ids()}"
        )
        return self.tap(matching[index])


@pytest.fixture
def bot(router) -> Bot:
    return Bot(router)


@pytest.fixture
def bot2(router) -> Bot:
    """A second, distinct patient — used for concurrency and isolation tests."""
    return Bot(router, wa_id="919898989898", profile_name="Other")
