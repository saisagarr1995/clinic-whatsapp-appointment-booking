"""Webhook security and payload handling.

The webhook is the only endpoint an attacker can reach with intent. Signature
verification and idempotency are therefore treated as security tests, not
plumbing tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from clinic_bot.main import create_app
from clinic_bot.whatsapp.cloud_api import parse_webhook, verify_signature
from clinic_bot.whatsapp.fake import FakeAdapter

from .conftest import clinic_url

WEBHOOK = clinic_url("/webhook")

SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def text_payload(text: str = "Hi", wa_id: str = "919812345678", msg_id: str = "wamid.1") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"profile": {"name": "Tester"}, "wa_id": wa_id}],
                            "messages": [
                                {
                                    "from": wa_id,
                                    "id": msg_id,
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.fixture
def client_and_adapter():
    adapter = FakeAdapter()
    app = create_app(adapter=adapter)
    with TestClient(app) as client:
        yield client, adapter


# --------------------------------------------------------------------------
# Verification handshake
# --------------------------------------------------------------------------


def test_correct_verify_token_echoes_the_challenge(client_and_adapter):
    client, _ = client_and_adapter
    r = client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "abc123",
        },
    )
    assert r.status_code == 200
    assert r.text == "abc123"


def test_wrong_verify_token_is_rejected(client_and_adapter):
    client, _ = client_and_adapter
    r = client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "abc123",
        },
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Signature verification
# --------------------------------------------------------------------------


def test_valid_signature_is_accepted_and_the_bot_replies(client_and_adapter):
    client, adapter = client_and_adapter
    body = json.dumps(text_payload()).encode()

    r = client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": sign(body)})

    assert r.status_code == 200
    assert adapter.sent, "the bot should have replied"
    assert adapter.has_button("btn_book")


def test_missing_signature_is_rejected(client_and_adapter):
    client, adapter = client_and_adapter
    body = json.dumps(text_payload()).encode()

    r = client.post(WEBHOOK, content=body)

    assert r.status_code == 403
    assert not adapter.sent, "no message may be processed without a valid signature"


def test_forged_signature_is_rejected(client_and_adapter):
    client, adapter = client_and_adapter
    body = json.dumps(text_payload()).encode()

    r = client.post(
        WEBHOOK,
        content=body,
        headers={"X-Hub-Signature-256": sign(body, "attacker-guessed-secret")},
    )

    assert r.status_code == 403
    assert not adapter.sent


def test_tampered_body_invalidates_the_signature(client_and_adapter):
    """Signature must cover the exact bytes, so edited payloads are caught."""
    client, adapter = client_and_adapter
    original = json.dumps(text_payload()).encode()
    signature = sign(original)
    tampered = json.dumps(text_payload(text="Book me in", msg_id="wamid.evil")).encode()

    r = client.post(WEBHOOK, content=tampered, headers={"X-Hub-Signature-256": signature})

    assert r.status_code == 403
    assert not adapter.sent


@pytest.mark.parametrize(
    "header",
    ["", "sha256=", "garbage", "sha1=abcdef", "sha256=nothex", None],
)
def test_malformed_signature_headers_are_rejected(header):
    assert verify_signature(SECRET, b"{}", header) is False


def test_signature_check_fails_closed_without_an_app_secret():
    """An unconfigured secret must never mean 'allow everything'."""
    body = b"{}"
    assert verify_signature("", body, sign(body)) is False


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


def test_a_replayed_delivery_is_processed_only_once(client_and_adapter):
    """Meta retries until it gets a 200; a retry must not double-book."""
    client, adapter = client_and_adapter
    body = json.dumps(text_payload(msg_id="wamid.same")).encode()
    headers = {"X-Hub-Signature-256": sign(body)}

    client.post(WEBHOOK, content=body, headers=headers)
    first_count = len(adapter.sent)
    assert first_count > 0

    client.post(WEBHOOK, content=body, headers=headers)
    assert len(adapter.sent) == first_count, "the replay produced extra messages"


# --------------------------------------------------------------------------
# Payload parsing
# --------------------------------------------------------------------------


def test_status_callbacks_are_ignored(client_and_adapter):
    client, adapter = client_and_adapter
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {"id": "wamid.x", "status": "delivered",
                                 "recipient_id": "919812345678"}
                            ],
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()

    r = client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": sign(body)})

    assert r.status_code == 200
    assert not adapter.sent, "delivery receipts must not trigger a reply"


def test_button_and_list_replies_are_parsed():
    for itype, key in (("button_reply", "button_reply"), ("list_reply", "list_reply")):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"profile": {"name": "T"}}],
                                "messages": [
                                    {
                                        "from": "919812345678",
                                        "id": f"wamid.{itype}",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": itype,
                                            key: {"id": "btn_book", "title": "Book"},
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        parsed = parse_webhook(payload)
        assert len(parsed) == 1
        assert parsed[0]["reply_id"] == "btn_book"


def test_unsupported_media_does_not_crash_the_parser():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919812345678",
                                    "id": "wamid.img",
                                    "type": "image",
                                    "image": {"id": "media123"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    parsed = parse_webhook(payload)
    assert len(parsed) == 1
    assert parsed[0]["text"] == ""
    assert parsed[0]["reply_id"] is None


def test_empty_and_malformed_payloads_are_safe():
    assert parse_webhook({}) == []
    assert parse_webhook({"entry": []}) == []
    assert parse_webhook({"entry": [{"changes": []}]}) == []
    assert parse_webhook({"entry": [{"changes": [{"value": {}}]}]}) == []


def test_no_api_docs_are_exposed(client_and_adapter):
    """A public repo plus public docs would hand an attacker the whole surface."""
    client, _ = client_and_adapter
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
