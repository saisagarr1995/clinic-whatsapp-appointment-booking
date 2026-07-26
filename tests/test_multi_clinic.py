"""Fleet isolation.

One process serves many clinics (PROJECT_PLAN.md D13, amended 2026-07-26). These
are the tests that justify that decision: they prove the file boundary and the
per-clinic app secret actually hold. If any test in this module fails, the fleet
is leaking one clinic's data into another and must not be deployed.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clinic_bot.clinic_config import load_clinic_config
from clinic_bot.db.models import Booking
from clinic_bot.db.seed import seed
from clinic_bot.db.session import reset_engine
from clinic_bot.main import create_app
from clinic_bot.registry import (
    RegistryError,
    UnknownClinicError,
    get_clinic,
    get_registry,
    load_registry,
    reset_registry,
)
from clinic_bot.settings import get_settings
from clinic_bot.whatsapp.fake import FakeAdapter

from .conftest import Bot, write_registry
from .test_flow_booking import book_fully
from .test_webhook import text_payload

A_SECRET = "clinic-a-app-secret"
B_SECRET = "clinic-b-app-secret"


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """Two clinics, each with its own database and its own Meta app secret."""
    a_db = f"sqlite:///{(tmp_path / 'a.db').as_posix()}"
    b_db = f"sqlite:///{(tmp_path / 'b.db').as_posix()}"

    registry_file = tmp_path / "fleet.yaml"
    write_registry(
        registry_file,
        [("alpha", "config/clinic.yaml", a_db), ("beta", "config/clinic.yaml", b_db)],
    )

    secrets = tmp_path / "secrets"
    secrets.mkdir()
    for slug, secret in (("alpha", A_SECRET), ("beta", B_SECRET)):
        (secrets / f"{slug}.env").write_text(
            "\n".join(
                [
                    f"WHATSAPP_APP_SECRET={secret}",
                    f"WHATSAPP_VERIFY_TOKEN={slug}-verify",
                    f"WHATSAPP_ACCESS_TOKEN={slug}-token",
                    f"WHATSAPP_PHONE_NUMBER_ID=1111{slug}",
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setenv("CLINICS_REGISTRY_PATH", str(registry_file))
    monkeypatch.setenv("SECRETS_DIR", str(secrets))
    get_settings.cache_clear()
    reset_registry()
    reset_engine()

    cfg = load_clinic_config("config/clinic.yaml")
    seed(cfg, url=a_db)
    seed(cfg, url=b_db)

    yield get_registry()

    reset_engine()
    reset_registry()
    get_settings.cache_clear()


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_lists_every_enabled_clinic(fleet):
    assert set(fleet) == {"alpha", "beta"}


def test_each_clinic_gets_its_own_database(fleet):
    assert fleet["alpha"].db_url != fleet["beta"].db_url


def test_each_clinic_gets_its_own_public_prefix(fleet):
    assert fleet["alpha"].public_base_url.endswith("/c/alpha")
    assert fleet["beta"].public_base_url.endswith("/c/beta")


def test_disabled_clinics_are_excluded(tmp_path, monkeypatch):
    registry_file = tmp_path / "r.yaml"
    registry_file.write_text(
        "clinics:\n"
        "  - slug: live\n    config: config/clinic.yaml\n    enabled: true\n"
        "  - slug: paused\n    config: config/clinic.yaml\n    enabled: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINICS_REGISTRY_PATH", str(registry_file))
    get_settings.cache_clear()
    reset_registry()

    clinics = load_registry(registry_file)
    assert set(clinics) == {"live"}


def test_duplicate_slugs_are_refused(tmp_path, monkeypatch):
    registry_file = tmp_path / "dupe.yaml"
    registry_file.write_text(
        "clinics:\n"
        "  - slug: same\n    config: config/clinic.yaml\n"
        "  - slug: same\n    config: config/clinic.yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLINICS_REGISTRY_PATH", str(registry_file))
    get_settings.cache_clear()
    reset_registry()

    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(registry_file)


@pytest.mark.parametrize("bad", ["Has Space", "UPPER", "slash/es", "", "dot.dot"])
def test_unsafe_slugs_are_refused(tmp_path, monkeypatch, bad):
    """Slugs become URL segments and filenames."""
    registry_file = tmp_path / "bad.yaml"
    registry_file.write_text(
        f"clinics:\n  - slug: {bad!r}\n    config: config/clinic.yaml\n", encoding="utf-8"
    )
    monkeypatch.setenv("CLINICS_REGISTRY_PATH", str(registry_file))
    get_settings.cache_clear()
    reset_registry()

    with pytest.raises(RegistryError):
        load_registry(registry_file)


def test_unknown_slug_raises(fleet):
    with pytest.raises(UnknownClinicError):
        get_clinic("ghost")


# --------------------------------------------------------------------------
# Data isolation — the reason this design was chosen
# --------------------------------------------------------------------------


def test_a_booking_in_one_clinic_is_invisible_to_the_other(fleet):
    alpha, beta = fleet["alpha"], fleet["beta"]

    book_fully(Bot(alpha.router(), db_url=alpha.db_url))

    with alpha.session() as db:
        alpha_bookings = list(db.scalars(select(Booking)))
    with beta.session() as db:
        beta_bookings = list(db.scalars(select(Booking)))

    assert len(alpha_bookings) == 1, "the booking should exist in its own clinic"
    assert beta_bookings == [], "another clinic must never see it"


def test_a_payment_reference_does_not_resolve_at_another_clinic(fleet):
    alpha = fleet["alpha"]
    book_fully(Bot(alpha.router(), db_url=alpha.db_url))

    with alpha.session() as db:
        ref = db.scalar(select(Booking)).ref

    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as client:
        assert client.get(f"/c/alpha/pay/{ref}").status_code == 200
        assert client.get(f"/c/beta/pay/{ref}").status_code == 404


# --------------------------------------------------------------------------
# Credential isolation
# --------------------------------------------------------------------------


def test_each_clinic_has_its_own_app_secret(fleet):
    assert fleet["alpha"].credentials.app_secret == A_SECRET
    assert fleet["beta"].credentials.app_secret == B_SECRET


def test_a_signature_valid_for_one_clinic_is_rejected_by_another(fleet):
    """The core security property of the fleet."""
    body = json.dumps(text_payload()).encode()
    signature = "sha256=" + hmac.new(A_SECRET.encode(), body, hashlib.sha256).hexdigest()

    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as client:
        ok = client.post(
            "/c/alpha/webhook", content=body, headers={"X-Hub-Signature-256": signature}
        )
        leaked = client.post(
            "/c/beta/webhook", content=body, headers={"X-Hub-Signature-256": signature}
        )

    assert ok.status_code == 200, "alpha must accept its own signature"
    assert leaked.status_code == 403, "beta must reject a signature it did not issue"


def test_verify_token_is_per_clinic(fleet):
    app = create_app(adapter=FakeAdapter())
    params = {"hub.mode": "subscribe", "hub.challenge": "xyz"}

    with TestClient(app) as client:
        good = client.get("/c/alpha/webhook", params={**params, "hub.verify_token": "alpha-verify"})
        bad = client.get("/c/beta/webhook", params={**params, "hub.verify_token": "alpha-verify"})

    assert good.status_code == 200
    assert bad.status_code == 403


def test_unknown_clinic_webhook_is_a_404(fleet):
    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as client:
        r = client.post("/c/nope/webhook", content=b"{}", headers={"X-Hub-Signature-256": "x"})
    assert r.status_code == 404
