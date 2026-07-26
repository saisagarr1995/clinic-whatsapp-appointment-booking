"""Offline conversation simulator.

Drives the REAL state machine, against the REAL clinic database, using the same
`FakeAdapter` the test suite uses. No Meta account, no credentials, no internet,
no tunnel. What you see here is exactly what a patient's handset would render.

SECURITY
--------
This endpoint injects messages into the state machine WITHOUT a webhook
signature — precisely what `verify_signature` exists to prevent. It is therefore
gated on `SIMULATOR=true`, which defaults to false, and `create_app` does not
even register this router when the flag is off. Never enable it on a deployment
reachable from the internet.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from clinic_bot.db.models import ConversationSession
from clinic_bot.registry import Clinic, clinic_dependency
from clinic_bot.whatsapp.base import (
    ButtonMessage,
    ListMessage,
    OutboundMessage,
    TextMessage,
)
from clinic_bot.whatsapp.fake import FakeAdapter

router = APIRouter()

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: Distinctive so simulated bookings are obvious in the database.
DEFAULT_SIM_WA_ID = "919000000001"

_message_ids = itertools.count(1)


class SimInbound(BaseModel):
    text: str = ""
    reply_id: str | None = None
    wa_id: str = DEFAULT_SIM_WA_ID


def _serialize(message: OutboundMessage) -> dict[str, Any]:
    """Turn an outbound message into something the browser can render.

    Mirrors the structure Meta would deliver, so the buttons and rows shown are
    driven by the same ids that go over the wire in production.
    """
    if isinstance(message, TextMessage):
        return {"kind": "text", "body": message.body}

    if isinstance(message, ButtonMessage):
        return {
            "kind": "buttons",
            "body": message.body,
            "header": message.header,
            "footer": message.footer,
            "buttons": [{"id": b.id, "title": b.title} for b in message.buttons],
        }

    if isinstance(message, ListMessage):
        return {
            "kind": "list",
            "body": message.body,
            "header": message.header,
            "footer": message.footer,
            "button_title": message.button_title,
            "sections": [
                {
                    "title": s.title,
                    "rows": [
                        {"id": r.id, "title": r.title, "description": r.description}
                        for r in s.rows
                    ],
                }
                for s in message.sections
            ],
        }

    return {"kind": "text", "body": str(message)}


@router.get("/c/{slug}/sim", response_class=HTMLResponse, include_in_schema=False)
def sim_page(request: Request, clinic: Clinic = Depends(clinic_dependency)) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request=request,
        name="sim.html",
        context={
            "clinic_name": clinic.config.clinic.name,
            "slug": clinic.slug,
            "wa_id": DEFAULT_SIM_WA_ID,
        },
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )


@router.post("/c/{slug}/sim/send", include_in_schema=False)
def sim_send(
    inbound: SimInbound, clinic: Clinic = Depends(clinic_dependency)
) -> JSONResponse:
    """Run one turn of the conversation and return what the bot would send."""
    from clinic_bot.whatsapp.base import InboundMessage

    message = InboundMessage(
        wa_id=inbound.wa_id,
        message_id=f"sim.{clinic.slug}.{next(_message_ids)}",
        profile_name="Simulator",
        text=inbound.text,
        reply_id=inbound.reply_id,
    )

    adapter = FakeAdapter()
    router_ = clinic.router()
    with clinic.session() as db:
        reply = router_.handle(db, message)
    adapter.send_all(reply)

    return JSONResponse({"messages": [_serialize(m) for m in adapter.sent]})


@router.post("/c/{slug}/sim/reset", include_in_schema=False)
def sim_reset(
    inbound: SimInbound, clinic: Clinic = Depends(clinic_dependency)
) -> JSONResponse:
    """Forget the simulated patient's conversation state.

    Bookings are deliberately left alone — clearing them would hide exactly the
    kind of double-booking bug this simulator is here to surface.
    """
    with clinic.session() as db:
        row = db.get(ConversationSession, inbound.wa_id)
        if row is not None:
            db.delete(row)
    return JSONResponse({"ok": True})
