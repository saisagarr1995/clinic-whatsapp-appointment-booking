"""Meta WhatsApp Cloud API adapter.

Talks to the documented Graph API directly. Deliberately dependency-light: the
surface we need is four JSON message shapes plus an HMAC signature check.

COST NOTE
---------
This adapter only ever *replies* to an inbound patient message, which Meta bills
as a free service conversation. It must never be used to initiate a conversation
(template messages are paid). See PROJECT_PLAN.md section 4.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from clinic_bot.settings import Settings, get_settings
from clinic_bot.whatsapp.base import (
    ButtonMessage,
    ImageMessage,
    ListMessage,
    OutboundMessage,
    Reply,
    TextMessage,
)

log = logging.getLogger(__name__)


class WhatsAppSendError(RuntimeError):
    """Meta rejected a send. Carries the API error payload for diagnosis."""


def verify_signature(app_secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """Validate the X-Hub-Signature-256 header.

    Without this, anyone who learns the webhook URL can inject fake patient
    messages. Compared in constant time.
    """
    if not header_value or not app_secret:
        return False
    prefix = "sha256="
    if not header_value.startswith(prefix):
        return False
    provided = header_value[len(prefix) :].strip()
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def build_payload(message: OutboundMessage) -> dict[str, Any]:
    """Translate an internal message into Cloud API JSON."""
    base: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.to,
    }

    if isinstance(message, TextMessage):
        return {
            **base,
            "type": "text",
            "text": {"body": message.body, "preview_url": message.preview_url},
        }

    if isinstance(message, ImageMessage):
        image: dict[str, Any] = {"link": message.image_url}
        if message.caption:
            image["caption"] = message.caption
        return {**base, "type": "image", "image": image}

    if isinstance(message, ButtonMessage):
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": message.body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b.id, "title": b.title}}
                    for b in message.buttons
                ]
            },
        }
        if message.header:
            interactive["header"] = {"type": "text", "text": message.header}
        if message.footer:
            interactive["footer"] = {"text": message.footer}
        return {**base, "type": "interactive", "interactive": interactive}

    if isinstance(message, ListMessage):
        interactive = {
            "type": "list",
            "body": {"text": message.body},
            "action": {
                "button": message.button_title,
                "sections": [
                    {
                        "title": section.title,
                        "rows": [
                            {
                                "id": row.id,
                                "title": row.title,
                                **({"description": row.description} if row.description else {}),
                            }
                            for row in section.rows
                        ],
                    }
                    for section in message.sections
                ],
            },
        }
        if message.header:
            interactive["header"] = {"type": "text", "text": message.header}
        if message.footer:
            interactive["footer"] = {"text": message.footer}
        return {**base, "type": "interactive", "interactive": interactive}

    raise TypeError(f"Unsupported message type: {type(message).__name__}")


def parse_webhook(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalised inbound message dicts from a webhook payload.

    Returns [] for delivery-status callbacks and any other non-message event,
    which Meta sends constantly and which we must ignore silently.
    """
    results: list[dict[str, Any]] = []

    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            messages = value.get("messages") or []
            if not messages:
                continue  # statuses, errors, etc.

            contacts = value.get("contacts") or []
            profile_name = ""
            if contacts:
                profile_name = (contacts[0].get("profile") or {}).get("name", "") or ""

            for msg in messages:
                wa_id = msg.get("from", "")
                message_id = msg.get("id", "")
                if not wa_id or not message_id:
                    continue

                text = ""
                reply_id: str | None = None
                reply_title = ""
                msg_type = msg.get("type")

                if msg_type == "text":
                    text = (msg.get("text") or {}).get("body", "") or ""
                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    itype = interactive.get("type")
                    if itype == "button_reply":
                        reply = interactive.get("button_reply") or {}
                        reply_id = reply.get("id")
                        reply_title = reply.get("title", "") or ""
                    elif itype == "list_reply":
                        reply = interactive.get("list_reply") or {}
                        reply_id = reply.get("id")
                        reply_title = reply.get("title", "") or ""
                elif msg_type == "button":
                    # Legacy template quick-reply shape.
                    btn = msg.get("button") or {}
                    text = btn.get("text", "") or ""
                else:
                    # image / audio / location / sticker / unsupported — treat as
                    # unrecognised input so the router replies with a nudge.
                    text = ""

                results.append(
                    {
                        "wa_id": wa_id,
                        "message_id": message_id,
                        "profile_name": profile_name,
                        "text": text,
                        "reply_id": reply_id,
                        "reply_title": reply_title,
                    }
                )

    return results


class CloudApiAdapter:
    """Sends messages through the Meta Graph API.

    Credentials are per clinic: each clinic in the fleet has its own phone number
    id and access token, so the adapter is constructed once per clinic rather
    than once per process.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.Client | None = None,
        credentials=None,  # noqa: ANN001 - registry.ClinicCredentials, avoids a circular import
    ):
        self._settings = settings or get_settings()
        self._creds = credentials
        self._client = client or httpx.Client(timeout=20.0)

    @property
    def _access_token(self) -> str:
        if self._creds is not None:
            return self._creds.access_token
        return self._settings.whatsapp_access_token

    @property
    def _messages_url(self) -> str:
        if self._creds is not None:
            return self._creds.messages_url
        return self._settings.messages_url

    def send(self, message: OutboundMessage) -> str | None:
        payload = build_payload(message)
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(self._messages_url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"Network error contacting Meta: {exc}") from exc

        if response.status_code >= 400:
            # Meta's error body is the only useful diagnostic; surface it verbatim.
            raise WhatsAppSendError(
                f"Meta rejected the message (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()
        sent = (data.get("messages") or [{}])[0]
        return sent.get("id")

    def send_all(self, reply: Reply) -> None:
        """Deliver in order. One failure must not swallow the remaining messages."""
        for message in reply.messages:
            try:
                self.send(message)
            except WhatsAppSendError:
                log.exception("Failed to deliver message to %s", message.to)

    def close(self) -> None:
        self._client.close()
