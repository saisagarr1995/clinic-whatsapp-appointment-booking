"""FastAPI application: the WhatsApp webhooks plus the patient payment pages.

One process serves the whole clinic fleet. Every patient-facing route is scoped
to a clinic slug — /c/{slug}/… — and resolves to that clinic's own config,
database and Meta credentials.

SECURITY
--------
Two independent checks guard each webhook:
  * GET  — Meta's subscription handshake must present THAT CLINIC's verify token.
  * POST — every payload must carry a valid X-Hub-Signature-256 HMAC of the raw
           body, computed with THAT CLINIC's app secret. Without this, anyone who
           learns the URL could inject fake patient messages and create bookings.

Because the secret is per clinic, a signature that is valid for one clinic is
rejected by every other clinic in the fleet. Signature verification is never
skipped outside tests.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.exc import IntegrityError

from clinic_bot.db.models import ProcessedMessage
from clinic_bot.registry import Clinic, clinic_dependency, get_registry, validate_all
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
    settings = get_settings()

    clinics = get_registry()

    # Fail loudly at startup if any clinic's YAML is broken — the operator can
    # still fix it now; at 2am with a patient waiting they cannot.
    problems = validate_all()
    if problems:
        for slug, error in problems:
            log.error("Clinic %s has an invalid config:\n%s", slug, error)
        raise RuntimeError(
            f"{len(problems)} clinic config(s) failed to load: "
            f"{', '.join(slug for slug, _ in problems)}"
        )

    override = app.state.adapter  # a test may inject one fake for the whole fleet

    for slug, clinic in clinics.items():
        clinic.init_db()
        cfg = clinic.config
        log.info(
            "Clinic %-12s %s (%d services, %d doctors) -> %s",
            slug, cfg.clinic.name, len(cfg.services), len(cfg.doctors), clinic.db_url,
        )

        app.state.adapters[slug] = override or CloudApiAdapter(
            settings, credentials=clinic.credentials
        )

        missing = clinic.credentials.missing()
        if missing and not settings.testing:
            # Not fatal: the payment page and the simulator still work. But say so.
            log.warning(
                "Clinic %s is missing %s — it cannot send WhatsApp messages until "
                "these are set in config/secrets/%s.env",
                slug, ", ".join(missing), slug,
            )

    if settings.simulator:
        log.warning(
            "SIMULATOR MODE IS ON — /c/{slug}/sim accepts unsigned messages. "
            "Never enable this on a public deployment."
        )

    yield

    for adapter in app.state.adapters.values():
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
    app.state.adapters = {}
    app.include_router(web_router)

    settings = get_settings()

    if settings.simulator:
        from clinic_bot.web.sim import router as sim_router

        app.include_router(sim_router)

    # ------------------------------------------------------------------
    # Health — fleet-wide
    # ------------------------------------------------------------------

    @app.get("/health", include_in_schema=False)
    def health() -> JSONResponse:
        try:
            clinics = get_registry()
        except Exception as exc:  # registry itself is broken
            return JSONResponse(status_code=503, content={"status": "down", "error": str(exc)})

        report = []
        healthy = True
        for slug, clinic in clinics.items():
            try:
                _ = clinic.config  # property access performs the load
                config_ok, error = True, None
            except Exception as exc:
                config_ok, error = False, str(exc)

            missing = clinic.credentials.missing()
            # In simulator mode absent Meta credentials are expected, not a fault.
            live_ok = config_ok and (not missing or get_settings().simulator)
            healthy = healthy and live_ok

            entry = {
                "slug": slug,
                "name": clinic.name,
                "config_loaded": config_ok,
                "missing_credentials": missing,
                "can_send_whatsapp": not missing,
            }
            if error:
                entry["error"] = error
            report.append(entry)

        return JSONResponse(
            status_code=200 if healthy else 503,
            content={
                "status": "ok" if healthy else "degraded",
                "simulator": get_settings().simulator,
                "clinics": report,
            },
        )

    # ------------------------------------------------------------------
    # Webhook — one per clinic
    # ------------------------------------------------------------------

    @app.get("/c/{slug}/webhook", include_in_schema=False)
    def verify(request: Request, clinic: Clinic = Depends(clinic_dependency)) -> Response:
        """Meta's subscription handshake, checked against this clinic's token."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge", "")

        expected = clinic.credentials.verify_token
        if mode == "subscribe" and expected and token == expected:
            log.info("Webhook verified by Meta for clinic %s", clinic.slug)
            return PlainTextResponse(challenge, status_code=200)

        log.warning("Webhook verification rejected for %s (mode=%s)", clinic.slug, mode)
        return PlainTextResponse("Forbidden", status_code=403)

    @app.post("/c/{slug}/webhook", include_in_schema=False)
    async def receive(
        request: Request,
        background: BackgroundTasks,
        clinic: Clinic = Depends(clinic_dependency),
    ) -> Response:
        raw = await request.body()

        if not verify_signature(
            clinic.credentials.app_secret, raw, request.headers.get("X-Hub-Signature-256")
        ):
            log.warning("Rejected webhook with an invalid signature for %s", clinic.slug)
            return PlainTextResponse("Forbidden", status_code=403)

        try:
            body = await request.json()
        except ValueError:
            return PlainTextResponse("Bad Request", status_code=400)

        inbounds = parse_webhook(body)

        # Claim message ids synchronously, BEFORE returning 200. Meta retries until
        # it gets a 200, so claiming here is what makes a retry a no-op instead of
        # a duplicate booking. The claim lives in this clinic's own database.
        fresh: list[InboundMessage] = []
        for item in inbounds:
            if _claim(clinic, item["message_id"]):
                fresh.append(InboundMessage(**item))

        for inbound in fresh:
            background.add_task(_process, app, clinic, inbound)

        # Always 200 once the signature is valid, so Meta stops retrying.
        return PlainTextResponse("EVENT_RECEIVED", status_code=200)

    return app


def _claim(clinic: Clinic, message_id: str) -> bool:
    """Record a message id. Returns False if it was already processed."""
    if not message_id:
        return False
    try:
        with clinic.session() as db:
            db.add(ProcessedMessage(message_id=message_id))
    except IntegrityError:
        log.info("Duplicate webhook delivery for %s (%s) — ignoring", message_id, clinic.slug)
        return False
    return True


def _process(app: FastAPI, clinic: Clinic, inbound: InboundMessage) -> None:
    """Run the state machine and deliver the reply.

    Runs after the 200 has been returned to Meta, so a slow send never causes a
    webhook retry.
    """
    from clinic_bot.whatsapp import messages as M
    from clinic_bot.whatsapp.base import Reply, TextMessage

    adapter = app.state.adapters.get(clinic.slug)
    try:
        router = clinic.router()
        with clinic.session() as db:
            reply = router.handle(db, inbound)
        adapter.send_all(reply)
    except Exception:
        log.exception(
            "Failed handling message %s from %s (clinic %s)",
            inbound.message_id, inbound.wa_id, clinic.slug,
        )
        # Never leave the patient staring at silence.
        try:
            adapter.send_all(Reply([TextMessage(to=inbound.wa_id, body=M.GENERIC_ERROR)]))
        except Exception:
            log.exception("Could not deliver the error notice either")


app = create_app()
