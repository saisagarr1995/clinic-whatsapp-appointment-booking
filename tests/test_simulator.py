"""The offline simulator.

The simulator bypasses webhook signature verification by design, so the tests
that matter most here are the ones proving it does not exist unless explicitly
switched on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clinic_bot.flow import ids
from clinic_bot.main import create_app
from clinic_bot.registry import reset_registry
from clinic_bot.settings import get_settings
from clinic_bot.whatsapp.fake import FakeAdapter

from .conftest import clinic_url

SIM = clinic_url("/sim")


@pytest.fixture
def sim_client(monkeypatch):
    """A client with SIMULATOR=true."""
    monkeypatch.setenv("SIMULATOR", "true")
    get_settings.cache_clear()
    reset_registry()
    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def plain_client():
    """A client with the simulator off — the production default."""
    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def test_simulator_is_absent_by_default(plain_client):
    """SIMULATOR defaults to false, so the routes must not exist at all."""
    assert plain_client.get(SIM).status_code == 404
    assert plain_client.post(f"{SIM}/send", json={"text": "hi"}).status_code == 404


def test_simulator_default_is_off():
    get_settings.cache_clear()
    assert get_settings().simulator is False


def test_simulator_page_renders_when_enabled(sim_client):
    r = sim_client.get(SIM)
    assert r.status_code == 200
    assert "simulator" in r.text.lower()


def test_simulator_is_not_indexable(sim_client):
    r = sim_client.get(SIM)
    assert "noindex" in r.headers.get("X-Robots-Tag", "").lower()


def test_simulator_rejects_an_unknown_clinic(sim_client):
    assert sim_client.get("/c/ghost/sim").status_code == 404


# --------------------------------------------------------------------------
# Driving the real state machine
# --------------------------------------------------------------------------


def test_a_greeting_returns_the_welcome_buttons(sim_client):
    r = sim_client.post(f"{SIM}/send", json={"text": "hi"})
    assert r.status_code == 200

    messages = r.json()["messages"]
    assert messages, "the bot must answer"

    button_ids = [b["id"] for m in messages if m["kind"] == "buttons" for b in m["buttons"]]
    assert ids.BTN_BOOK in button_ids
    assert ids.BTN_SERVICES in button_ids
    assert ids.BTN_CONTACT in button_ids


def test_tapping_a_button_id_advances_the_flow(sim_client):
    sim_client.post(f"{SIM}/send", json={"text": "hi"})
    r = sim_client.post(f"{SIM}/send", json={"reply_id": ids.BTN_BOOK})

    button_ids = [
        b["id"] for m in r.json()["messages"] if m["kind"] == "buttons" for b in m["buttons"]
    ]
    assert ids.BTN_BOOK_NEW in button_ids


def test_a_service_list_is_serialised_with_real_row_ids(sim_client):
    for payload in ({"text": "hi"}, {"reply_id": ids.BTN_BOOK}, {"reply_id": ids.BTN_BOOK_NEW}):
        sim_client.post(f"{SIM}/send", json=payload)

    sim_client.post(f"{SIM}/send", json={"text": "Test Patient"})
    r = sim_client.post(f"{SIM}/send", json={"reply_id": ids.BTN_VIEW_SERVICES})

    rows = [
        row
        for m in r.json()["messages"]
        if m["kind"] == "list"
        for s in m["sections"]
        for row in s["rows"]
    ]
    assert rows, "the service list must contain rows"
    assert all(row["id"].startswith(ids.P_SERVICE) for row in rows)


def test_conversation_state_persists_between_requests(sim_client):
    """State lives in the database, so each request continues the same chat."""
    sim_client.post(f"{SIM}/send", json={"text": "hi"})
    sim_client.post(f"{SIM}/send", json={"reply_id": ids.BTN_BOOK})
    sim_client.post(f"{SIM}/send", json={"reply_id": ids.BTN_BOOK_NEW})
    r = sim_client.post(f"{SIM}/send", json={"text": "Priya Sharma"})

    text = " ".join(m.get("body", "") for m in r.json()["messages"])
    assert "Priya Sharma" in text, "the name given a request earlier must be remembered"


def test_reset_clears_the_conversation(sim_client):
    sim_client.post(f"{SIM}/send", json={"text": "hi"})
    sim_client.post(f"{SIM}/send", json={"reply_id": ids.BTN_BOOK})

    assert sim_client.post(f"{SIM}/reset", json={}).status_code == 200

    r = sim_client.post(f"{SIM}/send", json={"text": "hi"})
    button_ids = [
        b["id"] for m in r.json()["messages"] if m["kind"] == "buttons" for b in m["buttons"]
    ]
    assert ids.BTN_BOOK in button_ids, "after a reset the chat starts from WELCOME again"


def test_simulator_writes_to_the_clinics_own_database(sim_client, clinic):
    """A simulated conversation must land in the clinic's real database."""
    from clinic_bot.db.models import ConversationSession

    sim_client.post(f"{SIM}/send", json={"text": "hi"})

    with clinic.session() as db:
        rows = db.query(ConversationSession).all()
    assert len(rows) == 1
    assert rows[0].wa_id.startswith("9190000")
