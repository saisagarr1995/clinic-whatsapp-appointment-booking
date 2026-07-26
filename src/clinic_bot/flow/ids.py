"""Stable button and list-row identifiers.

These strings travel to WhatsApp and come back on the next inbound message, so
they are a wire protocol: never change an existing value, only add. Prefixed ids
carry a payload after the colon.
"""

from __future__ import annotations

# --- Plain buttons ---
BTN_BOOK = "btn_book"
BTN_SERVICES = "btn_services"
BTN_CONTACT = "btn_contact"

BTN_BOOK_NEW = "btn_book_new"
BTN_RESCHEDULE = "btn_reschedule"
BTN_CANCEL = "btn_cancel"

BTN_VIEW_SERVICES = "btn_view_services"
BTN_CONFIRM = "btn_confirm"
BTN_CHANGE = "btn_change"

BTN_PAID = "btn_paid"
BTN_HELP = "btn_help"
#: Lets a patient past the UPI-reference prompt without typing one.
BTN_SKIP_UTR = "btn_skip_utr"

BTN_MAIN_MENU = "btn_main_menu"
BTN_CANCEL_YES = "btn_cancel_yes"
BTN_CANCEL_NO = "btn_cancel_no"

# --- Prefixed row ids ---
P_SERVICE = "svc:"
P_DOCTOR = "doc:"
P_DATE = "date:"
P_SLOT = "slot:"
P_BOOKING = "bk:"
P_MORE = "more:"


def make(prefix: str, value: str | int) -> str:
    return f"{prefix}{value}"


def parse(prefix: str, payload: str) -> str | None:
    """Return the value after `prefix`, or None if `payload` does not match."""
    if payload.startswith(prefix):
        return payload[len(prefix) :]
    return None


#: Typing any of these from any state returns the patient to the welcome menu.
RESET_KEYWORDS = frozenset(
    {
        "hi",
        "hii",
        "hiii",
        "hey",
        "hello",
        "helo",
        "start",
        "restart",
        "menu",
        "main menu",
        "back",
        "reset",
        "namaste",
        "hi there",
    }
)


def is_reset(text: str) -> bool:
    return text.strip().lower().strip("!.?") in RESET_KEYWORDS
