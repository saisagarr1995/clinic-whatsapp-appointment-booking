"""Patient-facing web routes: the UPI payment page.

This is the only public page. It exposes no personal data beyond the booking
reference the patient already holds, and it is marked noindex.

Mounted per clinic at /c/{slug}/pay/{ref}, so the booking is always looked up in
that clinic's own database — a reference from one clinic is simply not found in
another's.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from clinic_bot.booking_service import booking_by_ref
from clinic_bot.db.models import BookingStatus
from clinic_bot.payments.upi import InvalidRefError, build_app_links, build_upi_uri, validate_ref
from clinic_bot.registry import Clinic, clinic_dependency
from clinic_bot.whatsapp.messages import rupees

router = APIRouter()

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

#: Statuses for which a payment page still makes sense.
_PAYABLE = (BookingStatus.PENDING_PAYMENT, BookingStatus.AWAITING_VERIFICATION)


@router.get("/c/{slug}/pay/{ref}", response_class=HTMLResponse, include_in_schema=False)
def pay_page(
    ref: str, request: Request, clinic: Clinic = Depends(clinic_dependency)
) -> HTMLResponse:
    """The UPI app chooser page linked from the WhatsApp payment message."""
    cfg = clinic.config

    try:
        validate_ref(ref)  # check the shape before any DB work
    except InvalidRefError as exc:
        raise HTTPException(status_code=400, detail="Invalid reference") from exc

    with clinic.session() as db:
        booking = booking_by_ref(db, ref)
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found")
        if booking.status not in _PAYABLE:
            raise HTTPException(
                status_code=410,
                detail="This booking is no longer awaiting payment.",
            )
        amount = booking.amount

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
        },
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )
