"""FastAPI application: the WhatsApp webhook plus the patient payment pages.

SECURITY
--------
Two independent checks guard the webhook:
  * GET  — Meta's subscription handshake must present our verify token.
  * POST — every payload must carry a valid X-Hub-Signature-256 HMAC of the raw
           body, computed with the app secret. Without this, anyone who learns
           the URL could inject fake patient messages and create bookings.
Signature verification is never skipped outside tests.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError

from clinic_bot.clinic_config import ConfigError, get_clinic_config
from clinic_bot.db.models import ProcessedMessage
from clinic_bot.db.session import init_db, session_scope
from clinic_bot.flow.router import Router
from clinic_bot.settings import get_settings
from clinic_bot.web.routes import router as web_router
from clinic_bot.whatsapp.base import InboundMessage
from clinic_bot.whatsapp.cloud_api import CloudApiAdapter, parse_webhook, verify_signature

log = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    init_db()

    settings = get_settings()
    try:
        cfg = get_clinic_config()
        log.info("Clinic loaded: %s (%d services, %d doctors)",
                 cfg.clinic.name, len(cfg.services), len(cfg.doctors))
    except ConfigError:
        log.exception("clinic.yaml failed to load — run `python setup.py`")
        raise

    missing = settings.missing_credentials()
    if missing and not settings.testing:
        # Not fatal: the payment pages and self-test still work. But say so loudly.
        log.warning(
            "Missing WhatsApp credentials: %s. The bot cannot send messages until "
            "these are set in .env. Run `python setup.py` to configure.",
            ", ".join(missing),
        )

    if app.state.adapter is None:
        app.state.adapter = CloudApiAdapter(settings)

    yield

    adapter = app.state.adapter
    if hasattr(adapter, "close"):
        adapter.close()


def create_app(adapter=None) -> FastAPI:  # noqa: ANN001 - adapter is a Protocol
    app = FastAPI(
        title="Clinic WhatsApp Appointment Booking",
        version="1.0.0",
        docs_url=None,      # no public API docs
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.adapter = adapter
    app.include_router(web_router)

    settings = get_settings()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/health", include_in_schema=False)
    def health() -> JSONResponse:
        missing = settings.missing_credentials()
        try:
            cfg = get_clinic_config()
            clinic_ok, clinic_name = True, cfg.clinic.name
        except ConfigError:
            clinic_ok, clinic_name = False, None

        healthy = clinic_ok and not missing
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "clinic": clinic_name,
                "clinic_config_loaded": clinic_ok,
                "missing_credentials": missing,
            },
        )

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    @app.get("/webhook", include_in_schema=False)
    def verify(request: Request) -> Response:
        """Meta's subscription handshake."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge", "")

        expected = settings.whatsapp_verify_token
        if mode == "subscribe" and expected and token == expected:
            log.info("Webhook verified by Meta")
            return PlainTextResponse(challenge, status_code=200)

        log.warning("Webhook verification rejected (mode=%s)", mode)
        return PlainTextResponse("Forbidden", status_code=403)

    @app.post("/webhook", include_in_schema=False)
    async def receive(request: Request, background: BackgroundTasks) -> Response:
        raw = await request.body()

        if not verify_signature(
            settings.whatsapp_app_secret, raw, request.headers.get("X-Hub-Signature-256")
        ):
            log.warning("Rejected webhook with an invalid signature")
            return PlainTextResponse("Forbidden", status_code=403)

        try:
            body = await request.json()
        except ValueError:
            return PlainTextResponse("Bad Request", status_code=400)

        inbounds = parse_webhook(body)

        # Claim message ids synchronously, BEFORE returning 200. Meta retries until
        # it gets a 200, so claiming here is what makes a retry a no-op instead of
        # a duplicate booking.
        fresh: list[InboundMessage] = []
        for item in inbounds:
            if _claim(item["message_id"]):
                fresh.append(InboundMessage(**item))

        for inbound in fresh:
            background.add_task(_process, app, inbound)

        # Always 200 once the signature is valid, so Meta stops retrying.
        return PlainTextResponse("EVENT_RECEIVED", status_code=200)

    return app


def _claim(message_id: str) -> bool:
    """Record a message id. Returns False if it was already processed."""
    if not message_id:
        return False
    try:
        with session_scope() as db:
            db.add(ProcessedMessage(message_id=message_id))
    except IntegrityError:
        log.info("Duplicate webhook delivery for %s — ignoring", message_id)
        return False
    return True


def _process(app: FastAPI, inbound: InboundMessage) -> None:
    """Run the state machine and deliver the reply.

    Runs after the 200 has been returned to Meta, so a slow send never causes a
    webhook retry.
    """
    from clinic_bot.whatsapp import messages as M
    from clinic_bot.whatsapp.base import Reply, TextMessage

    try:
        cfg = get_clinic_config()
        router = Router(cfg, get_settings())
        with session_scope() as db:
            reply = router.handle(db, inbound)
        app.state.adapter.send_all(reply)
    except Exception:
        log.exception("Failed handling message %s from %s", inbound.message_id, inbound.wa_id)
        # Never leave the patient staring at silence.
        try:
            app.state.adapter.send_all(
                Reply([TextMessage(to=inbound.wa_id, body=M.GENERIC_ERROR)])
            )
        except Exception:
            log.exception("Could not deliver the error notice either")


app = create_app()
