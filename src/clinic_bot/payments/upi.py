"""UPI deep-link construction.

The generic `upi://pay?...` URI is the NPCI-standard form. On Android it opens the
system UPI app chooser, which is the most reliable path and the one we lead with.

App-specific schemes (GPay/PhonePe/Paytm/CRED) are *best effort*: vendors change
them without notice and they behave differently on iOS. They are offered as
secondary shortcuts on the payment page, never as the only route — the copyable
UPI ID always works regardless.

No QR image is generated (see PROJECT_PLAN.md D4, amended 2026-07-26). The patient
pays from the same phone that holds the chat, so the app chooser and the copyable
VPA cover the journey without carrying an image-rendering dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from clinic_bot.clinic_config import ClinicConfig

#: Booking refs appear in URLs, so their shape is enforced before any DB lookup.
_SAFE_REF = re.compile(r"^[A-Z0-9\-]{3,32}$")


class InvalidRefError(ValueError):
    """A booking reference did not match the expected shape."""


def validate_ref(ref: str) -> str:
    if not _SAFE_REF.match(ref):
        raise InvalidRefError(f"malformed booking ref: {ref!r}")
    return ref


def pay_url(base_url: str, ref: str) -> str:
    """The clinic-scoped payment page URL sent to the patient."""
    return f"{base_url.rstrip('/')}/pay/{validate_ref(ref)}"


@dataclass(frozen=True)
class UpiApp:
    key: str
    label: str
    scheme: str
    #: Brand colour used on the payment page.
    color: str


#: Order matters — most used in India first.
UPI_APPS: tuple[UpiApp, ...] = (
    UpiApp("gpay", "Google Pay", "tez://upi/pay", "#1a73e8"),
    UpiApp("phonepe", "PhonePe", "phonepe://pay", "#5f259f"),
    UpiApp("paytm", "Paytm", "paytmmp://pay", "#00baf2"),
    UpiApp("cred", "CRED", "credpay://upi/pay", "#0b0b0b"),
    UpiApp("bhim", "BHIM", "bhim://pay", "#00808f"),
)


def upi_params(
    cfg: ClinicConfig, *, ref: str, amount: int | None = None, note: str | None = None
) -> dict[str, str]:
    """NPCI UPI query parameters.

    pa = payee address (VPA)   pn = payee name    am = amount
    cu = currency              tn = transaction note
    tr = transaction reference (our booking ref, so the clinic can reconcile)
    """
    p = cfg.payment
    return {
        "pa": p.upi_id,
        "pn": p.upi_name,
        "am": f"{amount if amount is not None else p.advance_amount}",
        "cu": p.currency,
        "tn": note or f"Appointment {ref}",
        "tr": ref,
    }


def _query(params: dict[str, str]) -> str:
    # quote_via=quote keeps spaces as %20 rather than '+', which some UPI apps
    # render literally in the payment note.
    return urlencode(params, quote_via=quote)


def build_upi_uri(
    cfg: ClinicConfig, *, ref: str, amount: int | None = None, note: str | None = None
) -> str:
    """The standard URI behind the 'Pay with any UPI app' button."""
    return f"upi://pay?{_query(upi_params(cfg, ref=ref, amount=amount, note=note))}"


def build_app_uri(
    app: UpiApp, cfg: ClinicConfig, *, ref: str, amount: int | None = None
) -> str:
    return f"{app.scheme}?{_query(upi_params(cfg, ref=ref, amount=amount))}"


def build_app_links(
    cfg: ClinicConfig, *, ref: str, amount: int | None = None
) -> list[tuple[UpiApp, str]]:
    return [(app, build_app_uri(app, cfg, ref=ref, amount=amount)) for app in UPI_APPS]
