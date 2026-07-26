"""Message builders — the bot's entire visual output.

Views are pure: they take plain data and return messages. No database access, no
session mutation. That keeps them trivially unit-testable and keeps the router
focused on state transitions.
"""

from __future__ import annotations

import datetime as dt

from clinic_bot.clinic_config import ClinicConfig
from clinic_bot.db.models import Booking, Doctor, Service
from clinic_bot.flow import ids
from clinic_bot.whatsapp import messages as M
from clinic_bot.whatsapp.base import (
    BODY_MAX,
    Button,
    ButtonMessage,
    ListMessage,
    Reply,
    Row,
    Section,
    TextMessage,
)

#: 9 real rows + 1 "Show more" row = WhatsApp's hard limit of 10.
PAGE_SIZE = 9
MAX_ROWS = 10


def more_id(kind: str, offset: int) -> str:
    return f"{ids.P_MORE}{kind}:{offset}"


def parse_more(payload: str) -> tuple[str, int] | None:
    raw = ids.parse(ids.P_MORE, payload)
    if raw is None:
        return None
    kind, _, offset = raw.partition(":")
    try:
        return kind, int(offset)
    except ValueError:
        return None


def paginate(rows: list[Row], *, offset: int, kind: str) -> list[Row]:
    """Return one page, appending a 'Show more' row when items remain."""
    remaining = rows[offset:]
    if len(remaining) <= MAX_ROWS:
        return remaining
    page = remaining[:PAGE_SIZE]
    page.append(
        Row(
            id=more_id(kind, offset + PAGE_SIZE),
            title=M.MORE_ROW_TITLE,
            description=M.MORE_ROW_DESC,
        )
    )
    return page


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def welcome(to: str, cfg: ClinicConfig, patient_name: str = "") -> Reply:
    return Reply(
        [
            ButtonMessage(
                to=to,
                body=M.welcome(cfg, patient_name),
                buttons=[
                    Button(ids.BTN_BOOK, "Book Appointment"),
                    Button(ids.BTN_SERVICES, "Our Services"),
                    Button(ids.BTN_CONTACT, "Contact Us"),
                ],
            )
        ]
    )


def chunk_body(text: str, limit: int = BODY_MAX) -> list[str]:
    """Split long copy across several messages instead of letting it be truncated.

    A clinic with many services can push the services overview past WhatsApp's
    1024-character body limit. Splitting on blank lines keeps each service block
    intact; only a single oversized block is hard-split.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > limit:
            chunks.append(block[:limit])
            block = block[limit:]
        current = block
    if current:
        chunks.append(current)
    return chunks


def services_overview(to: str, cfg: ClinicConfig) -> Reply:
    """Full service list with fees and timings, then a booking nudge."""
    messages: list[TextMessage | ButtonMessage] = [
        TextMessage(to=to, body=part) for part in chunk_body(M.services_intro(cfg))
    ]
    messages.append(
        ButtonMessage(
            to=to,
            body=M.SERVICES_CTA,
            buttons=[Button(ids.BTN_BOOK, "Book Appointment")],
        )
    )
    return Reply(messages)


def contact(to: str, cfg: ClinicConfig) -> Reply:
    return Reply(
        [
            TextMessage(to=to, body=M.contact(cfg)),
            ButtonMessage(
                to=to,
                body=M.SERVICES_CTA,
                buttons=[Button(ids.BTN_BOOK, "Book Appointment")],
            ),
        ]
    )


def booking_menu(to: str) -> Reply:
    return Reply(
        [
            ButtonMessage(
                to=to,
                body=M.BOOKING_MENU,
                buttons=[
                    Button(ids.BTN_BOOK_NEW, "Book New"),
                    Button(ids.BTN_RESCHEDULE, "Reschedule"),
                    Button(ids.BTN_CANCEL, "Cancel"),
                ],
            )
        ]
    )


# --------------------------------------------------------------------------
# Book new
# --------------------------------------------------------------------------


def ask_name(to: str) -> Reply:
    return Reply([TextMessage(to=to, body=M.BOOK_INTRO), TextMessage(to=to, body=M.ASK_NAME)])


def ask_service(to: str, name: str) -> Reply:
    """Thank-you plus the 'View Services' button the patient taps to open the list."""
    return Reply(
        [
            TextMessage(to=to, body=M.thank_you_name(name)),
            ButtonMessage(
                to=to,
                body=M.ASK_SERVICE,
                buttons=[Button(ids.BTN_VIEW_SERVICES, M.VIEW_SERVICES_BTN)],
            ),
        ]
    )


def services_list(to: str, services: list[Service], *, offset: int = 0) -> Reply:
    rows = [
        Row(
            id=ids.make(ids.P_SERVICE, s.id),
            title=s.name,
            description=f"From {M.rupees(s.fee_from)} · {s.duration_minutes} min",
        )
        for s in services
    ]
    return Reply(
        [
            ListMessage(
                to=to,
                header=M.SERVICES_LIST_HEADER,
                body=M.SERVICES_LIST_BODY,
                button_title=M.VIEW_SERVICES_BTN,
                sections=[Section(M.SERVICES_SECTION, paginate(rows, offset=offset, kind="svc"))],
            )
        ]
    )


def doctors_list(
    to: str, service: Service, doctors: list[Doctor], *, offset: int = 0
) -> Reply:
    rows = [
        Row(
            id=ids.make(ids.P_DOCTOR, d.id),
            title=d.name,
            description=d.specialization or "Dental Surgeon",
        )
        for d in doctors
    ]
    return Reply(
        [
            ListMessage(
                to=to,
                header=M.DOCTORS_LIST_HEADER,
                body=M.ask_doctor(service.name),
                button_title=M.DOCTORS_LIST_BTN,
                sections=[Section(M.DOCTORS_SECTION, paginate(rows, offset=offset, kind="doc"))],
            )
        ]
    )


def dates_list(
    to: str, doctor: Doctor, dates: list[dt.date], today: dt.date, *, offset: int = 0
) -> Reply:
    rows = [
        Row(
            id=ids.make(ids.P_DATE, d.isoformat()),
            title=M.fmt_date_short(d, today=today),
            description=f"{['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][d.weekday()]}",
        )
        for d in dates
    ]
    return Reply(
        [
            ListMessage(
                to=to,
                header=M.DATES_LIST_HEADER,
                body=M.ask_date(doctor.name),
                button_title=M.DATES_LIST_BTN,
                sections=[Section(M.DATES_SECTION, paginate(rows, offset=offset, kind="date"))],
            )
        ]
    )


def slots_list(
    to: str,
    doctor: Doctor,
    day: dt.date,
    slots: list[dt.datetime],
    today: dt.date,
    *,
    offset: int = 0,
) -> Reply:
    rows = [
        Row(
            id=ids.make(ids.P_SLOT, s.strftime("%Y-%m-%dT%H:%M")),
            title=M.fmt_time(s),
            description=f"with {doctor.name}",
        )
        for s in slots
    ]
    return Reply(
        [
            ListMessage(
                to=to,
                header=M.SLOTS_LIST_HEADER,
                body=M.ask_slot(doctor.name, M.fmt_date(day, today=today)),
                button_title=M.SLOTS_LIST_BTN,
                sections=[Section(M.SLOTS_SECTION, paginate(rows, offset=offset, kind="slot"))],
            )
        ]
    )


def summary(
    to: str,
    *,
    cfg: ClinicConfig,
    patient_name: str,
    service: Service,
    doctor: Doctor,
    starts_at: dt.datetime,
    today: dt.date,
) -> Reply:
    return Reply(
        [
            ButtonMessage(
                to=to,
                body=M.summary(
                    cfg=cfg,
                    patient_name=patient_name,
                    service_name=service.name,
                    fee_from=service.fee_from,
                    doctor_name=doctor.name,
                    specialization=doctor.specialization,
                    starts_at=starts_at,
                    today=today,
                ),
                buttons=[
                    Button(ids.BTN_CONFIRM, "Confirm"),
                    Button(ids.BTN_CHANGE, "Change Details"),
                ],
            )
        ]
    )


def payment(to: str, *, cfg: ClinicConfig, ref: str, pay_page_url: str) -> Reply:
    """Payment instructions, then the action buttons.

    No QR image: the patient pays from the phone holding this chat, so the
    payment page's app chooser and the copyable UPI ID cover the journey.
    See PROJECT_PLAN.md D4 (amended 2026-07-26).
    """
    return Reply(
        [
            TextMessage(
                to=to,
                body=M.payment_instructions(cfg, ref, pay_page_url),
                preview_url=False,
            ),
            ButtonMessage(
                to=to,
                body=M.PAYMENT_CTA,
                buttons=[
                    Button(ids.BTN_PAID, "I've Paid"),
                    Button(ids.BTN_HELP, "Need Help"),
                ],
            ),
        ]
    )


def paid(
    to: str,
    *,
    cfg: ClinicConfig,
    patient_name: str,
    ref: str,
    doctor_name: str,
    starts_at: dt.datetime,
    today: dt.date,
) -> Reply:
    return Reply(
        [
            TextMessage(
                to=to,
                body=M.paid_thanks(
                    cfg,
                    patient_name=patient_name,
                    ref=ref,
                    starts_at=starts_at,
                    doctor_name=doctor_name,
                    today=today,
                ),
            )
        ]
    )


def need_help(to: str, cfg: ClinicConfig) -> Reply:
    return Reply(
        [
            TextMessage(to=to, body=M.need_help(cfg)),
            ButtonMessage(
                to=to,
                body=M.PAYMENT_CTA,
                buttons=[Button(ids.BTN_PAID, "I've Paid")],
            ),
        ]
    )


# --------------------------------------------------------------------------
# Reschedule / cancel
# --------------------------------------------------------------------------


def bookings_list(
    to: str, bookings: list[Booking], today: dt.date, *, prompt: str, offset: int = 0
) -> Reply:
    rows = [
        Row(
            id=ids.make(ids.P_BOOKING, b.ref),
            title=f"{M.fmt_date_short(b.starts_at.date(), today=today)}",
            description=f"{M.fmt_time(b.starts_at)} · {b.doctor.name} · {b.ref}",
        )
        for b in bookings
    ]
    return Reply(
        [
            ListMessage(
                to=to,
                header=M.BOOKINGS_LIST_HEADER,
                body=prompt,
                button_title=M.BOOKINGS_LIST_BTN,
                sections=[Section(M.BOOKINGS_SECTION, paginate(rows, offset=offset, kind="bk"))],
            )
        ]
    )


def confirm_cancel(
    to: str, booking: Booking, today: dt.date
) -> Reply:
    return Reply(
        [
            ButtonMessage(
                to=to,
                body=M.confirm_cancel(
                    booking.ref, booking.doctor.name, booking.starts_at, today
                ),
                buttons=[
                    Button(ids.BTN_CANCEL_YES, "Yes, Cancel"),
                    Button(ids.BTN_CANCEL_NO, "No, Keep It"),
                ],
            )
        ]
    )


def simple(to: str, body: str) -> Reply:
    return Reply([TextMessage(to=to, body=body)])


def with_menu_button(to: str, body: str) -> Reply:
    return Reply(
        [
            ButtonMessage(
                to=to,
                body=body,
                buttons=[Button(ids.BTN_BOOK, "Book Appointment")],
            )
        ]
    )
