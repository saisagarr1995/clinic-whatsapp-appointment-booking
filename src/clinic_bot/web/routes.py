"""Patient-facing web routes: the UPI payment page and the QR image.

These are the only public pages. They expose no personal data beyond the booking
reference the patient already holds, and they are marked noindex.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from clinic_bot.booking_service import booking_by_ref
from clinic_bot.clinic_config import get_clinic_config
from clinic_bot.db.models import BookingStatus
from clinic_bot.db.session import session_scope
from clinic_bot.payments import qr
from clinic_bot.payments.upi import build_app_links, build_upi_uri
from clinic_bot.settings import get_settings
from clinic_bot.whatsapp.messages import rupees

router = APIRouter()

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: Statuses for which a payment page still makes sense.
_PAYABLE = (BookingStatus.PENDING_PAYMENT, BookingStatus.AWAITING_VERIFICATION)


@router.get("/qr/{ref}.png", include_in_schema=False)
def qr_image(ref: str) -> FileResponse:
    """Serve a booking's UPI QR. Meta fetches this URL to deliver the image."""
    try:
        path = qr.qr_path(ref)
    except qr.InvalidRefError as exc:
        raise HTTPException(status_code=400, detail="Invalid reference") from exc

    if not path.exists():
        # Regenerate on demand — the file may have been cleaned up.
        with session_scope() as db:
            booking = booking_by_ref(db, ref)
            if booking is None:
                raise HTTPException(status_code=404, detail="Not found")
            amount = booking.amount
        path = qr.ensure_qr(get_clinic_config(), ref=ref, amount=amount)

    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/pay/{ref}", response_class=HTMLResponse, include_in_schema=False)
def pay_page(ref: str, request: Request) -> HTMLResponse:
    """The UPI app chooser page linked from the WhatsApp payment message."""
    cfg = get_clinic_config()
    settings = get_settings()

    try:
        qr.qr_path(ref)  # validates the ref shape before any DB work
    except qr.InvalidRefError as exc:
        raise HTTPException(status_code=400, detail="Invalid reference") from exc

    with session_scope() as db:
        booking = booking_by_ref(db, ref)
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found")
        if booking.status not in _PAYABLE:
            raise HTTPException(
                status_code=410,
                detail="This booking is no longer awaiting payment.",
            )
        amount = booking.amount

    qr.ensure_qr(cfg, ref=ref, amount=amount)

    return _TEMPLATES.TemplateResponse(
        request=request,
        name="pay.html",
        context={
            "clinic_name": cfg.clinic.name,
            "clinic_phone": cfg.clinic.phone,
            "ref": ref,
            "amount_label": rupees(amount),
            "upi_id": cfg.payment.upi_id,
            "upi_uri": build_upi_uri(cfg, ref=ref, amount=amount),
            "app_links": build_app_links(cfg, ref=ref, amount=amount),
            "qr_url": qr.qr_url(settings.public_base_url, ref),
        },
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )
