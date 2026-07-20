"""UPI URI construction, QR generation and the payment page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from clinic_bot.db.models import Booking
from clinic_bot.db.session import session_scope
from clinic_bot.flow import ids
from clinic_bot.main import create_app
from clinic_bot.payments import qr
from clinic_bot.payments.upi import UPI_APPS, build_app_links, build_upi_uri
from clinic_bot.whatsapp.fake import FakeAdapter
from clinic_bot.whatsapp.messages import rupees

from .test_flow_booking import book_fully

# --------------------------------------------------------------------------
# UPI URI
# --------------------------------------------------------------------------


def test_upi_uri_carries_every_required_npci_parameter(cfg):
    uri = build_upi_uri(cfg, ref="SDC-ABC12")
    parsed = urlparse(uri)
    assert parsed.scheme == "upi"
    assert parsed.netloc == "pay"

    q = parse_qs(parsed.query)
    assert q["pa"] == [cfg.payment.upi_id]
    assert q["pn"] == [cfg.payment.upi_name]
    assert q["am"] == [str(cfg.payment.advance_amount)]
    assert q["cu"] == [cfg.payment.currency]
    assert q["tr"] == ["SDC-ABC12"]
    assert "SDC-ABC12" in q["tn"][0]


def test_upi_uri_encodes_spaces_safely(cfg):
    """'+' in a payment note is rendered literally by some UPI apps."""
    uri = build_upi_uri(cfg, ref="SDC-ABC12", note="Advance for appointment")
    assert "+" not in urlparse(uri).query
    assert "%20" in uri


def test_every_app_link_shares_the_same_payment_parameters(cfg):
    links = build_app_links(cfg, ref="SDC-ABC12")
    assert len(links) == len(UPI_APPS)

    baseline = parse_qs(urlparse(build_upi_uri(cfg, ref="SDC-ABC12")).query)
    for app, link in links:
        q = parse_qs(urlparse(link).query)
        for key in ("pa", "pn", "am", "cu", "tr"):
            assert q[key] == baseline[key], f"{app.key} disagrees on {key}"


def test_amount_override_is_honoured(cfg):
    uri = build_upi_uri(cfg, ref="SDC-ABC12", amount=999)
    assert parse_qs(urlparse(uri).query)["am"] == ["999"]


# --------------------------------------------------------------------------
# QR
# --------------------------------------------------------------------------


def test_qr_is_a_real_png(cfg):
    path = qr.ensure_qr(cfg, ref="SDC-ABC12")
    assert path.exists()
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_qr_generation_is_cached(cfg):
    first = qr.ensure_qr(cfg, ref="SDC-ABC12")
    mtime = first.stat().st_mtime_ns
    second = qr.ensure_qr(cfg, ref="SDC-ABC12")
    assert second == first
    assert second.stat().st_mtime_ns == mtime


@pytest.mark.parametrize(
    "bad_ref",
    ["../../etc/passwd", "a/b", "SDC ABC", "", "x" * 40, "sdc-abc12", "..\\win.ini"],
)
def test_path_traversal_and_odd_refs_are_refused(bad_ref):
    """Booking refs become filenames, so the shape is enforced."""
    with pytest.raises(qr.InvalidRefError):
        qr.qr_path(bad_ref)


# --------------------------------------------------------------------------
# Payment page
# --------------------------------------------------------------------------


@pytest.fixture
def client():
    app = create_app(adapter=FakeAdapter())
    with TestClient(app) as c:
        yield c


def _make_booking(bot):
    book_fully(bot)
    with session_scope() as db:
        booking = db.scalar(select(Booking))
        return booking.ref, booking.amount


def test_payment_page_renders_the_details_a_patient_needs(bot, client, cfg):
    ref, amount = _make_booking(bot)

    r = client.get(f"/pay/{ref}")
    assert r.status_code == 200

    html = r.text
    assert cfg.payment.upi_id in html
    assert cfg.clinic.name in html
    assert ref in html
    assert rupees(amount) in html
    assert "upi://pay?" in html
    for app in UPI_APPS:
        assert app.label in html, f"{app.label} button missing"


def test_payment_page_is_not_indexable(bot, client):
    ref, _ = _make_booking(bot)
    r = client.get(f"/pay/{ref}")
    assert "noindex" in r.headers.get("X-Robots-Tag", "").lower()


def test_qr_endpoint_serves_a_png(bot, client):
    ref, _ = _make_booking(bot)
    r = client.get(f"/qr/{ref}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")


def test_unknown_booking_reference_is_a_404(client):
    assert client.get("/pay/SDC-ZZZZZ").status_code == 404


def test_malformed_reference_is_rejected(client):
    assert client.get("/pay/not%20a%20ref").status_code in (400, 404)


def test_cancelled_booking_stops_accepting_payment(bot, client):
    ref, _ = _make_booking(bot)

    bot.say("Hi")
    bot.tap(ids.BTN_BOOK)
    bot.tap(ids.BTN_CANCEL)
    bot.pick_row(ids.P_BOOKING)
    bot.tap(ids.BTN_CANCEL_YES)

    r = client.get(f"/pay/{ref}")
    assert r.status_code == 410, "a cancelled booking must not keep collecting money"
