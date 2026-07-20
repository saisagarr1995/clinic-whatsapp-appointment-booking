"""Every user-facing string in the product.

Centralised so that (a) copy changes never require touching flow logic, and
(b) adding Telugu/Hindi later is a data-only change. Handlers must not contain
inline patient-visible text.
"""

from __future__ import annotations

import datetime as dt

from clinic_bot.clinic_config import ClinicConfig

# --------------------------------------------------------------------------
# Formatters
# --------------------------------------------------------------------------

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def rupees(amount: int) -> str:
    """Indian digit grouping: 25000 -> ₹25,000."""
    s = str(abs(int(amount)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join([*parts, tail])
    return f"₹{s}"


def fmt_time(t: dt.time | dt.datetime) -> str:
    """09:00 -> 9:00 AM"""
    if isinstance(t, dt.datetime):
        t = t.time()
    hour = t.hour % 12 or 12
    meridiem = "AM" if t.hour < 12 else "PM"
    return f"{hour}:{t.minute:02d} {meridiem}"


def fmt_date(d: dt.date, *, today: dt.date | None = None) -> str:
    """Friendly date: 'Today (Mon, 21 Jul)'."""
    label = f"{_DAY_NAMES[d.weekday()][:3]}, {d.day} {d.strftime('%b')}"
    if today is not None:
        if d == today:
            return f"Today ({label})"
        if d == today + dt.timedelta(days=1):
            return f"Tomorrow ({label})"
    return label


def fmt_date_short(d: dt.date, *, today: dt.date | None = None) -> str:
    """Fits the 24-char WhatsApp row-title limit."""
    if today is not None:
        if d == today:
            return f"Today, {d.day} {d.strftime('%b')}"
        if d == today + dt.timedelta(days=1):
            return f"Tomorrow, {d.day} {d.strftime('%b')}"
    return f"{_DAY_NAMES[d.weekday()][:3]}, {d.day} {d.strftime('%b')}"


def fmt_days(days: list[str]) -> str:
    """['mon','tue','wed'] -> 'Mon - Wed'; non-contiguous -> 'Mon, Wed, Fri'."""
    order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    idx = sorted(order.index(d) for d in days if d in order)
    if not idx:
        return "—"
    names = [order[i].capitalize() for i in idx]
    contiguous = all(b - a == 1 for a, b in zip(idx, idx[1:], strict=False))
    if contiguous and len(idx) > 2:
        return f"{names[0]} - {names[-1]}"
    return ", ".join(names)


# --------------------------------------------------------------------------
# Copy
# --------------------------------------------------------------------------


def welcome(cfg: ClinicConfig, patient_name: str = "") -> str:
    greeting = f"Hello {patient_name}! 👋" if patient_name else "Hello! 👋"
    tagline = f"_{cfg.clinic.tagline}_\n\n" if cfg.clinic.tagline else "\n"
    return (
        f"{greeting}\n\n"
        f"Welcome to *{cfg.clinic.name}*\n"
        f"{tagline}"
        f"How can we help you today?"
    )


def services_intro(cfg: ClinicConfig) -> str:
    h = cfg.clinic.hours
    lines = [f"🦷 *Our Services at {cfg.clinic.name}*", ""]
    for svc in cfg.services:
        lines.append(f"*{svc.name}*")
        if svc.description:
            lines.append(f"_{svc.description}_")
        lines.append(f"Consultation fee starts at {rupees(svc.fee_from)}")
        lines.append("")

    lines.append("🕐 *Clinic Timings*")
    lines.append(f"{fmt_days(h.days)}: {fmt_time(h.open_time)} - {fmt_time(h.close_time)}")
    if h.brk:
        lines.append(f"Lunch break: {fmt_time(h.brk.start_time)} - {fmt_time(h.brk.end_time)}")
    closed = [d for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] if d not in h.days]
    if closed:
        lines.append(f"Closed: {fmt_days(closed)}")
    return "\n".join(lines).strip()


SERVICES_CTA = "Ready to book your appointment?"

CONTACT_TITLE = "📞 *Contact Us*"


def contact(cfg: ClinicConfig) -> str:
    h = cfg.clinic.hours
    parts = [
        CONTACT_TITLE,
        "",
        f"*{cfg.clinic.name}*",
        f"📱 {cfg.clinic.phone}",
        f"📍 {cfg.clinic.address}",
        "",
        "🕐 *Timings*",
        f"{fmt_days(h.days)}: {fmt_time(h.open_time)} - {fmt_time(h.close_time)}",
    ]
    return "\n".join(parts)


BOOKING_MENU = "What would you like to do?"

# --- Book new ---
BOOK_INTRO = "Great! Let's get you booked in. 😊"
ASK_NAME = "May I have your full name please?"


def thank_you_name(name: str) -> str:
    return f"Thank you, *{name}*!"


ASK_SERVICE = "Which service do you need today?"
VIEW_SERVICES_BTN = "View Services"
SERVICES_LIST_HEADER = "Our Services"
SERVICES_LIST_BODY = "Tap below to see all treatments and pick the one you need."
SERVICES_SECTION = "Treatments"


def ask_doctor(service_name: str) -> str:
    return f"You selected *{service_name}*.\n\nPlease choose your preferred doctor:"


DOCTORS_LIST_BTN = "View Doctors"
DOCTORS_LIST_HEADER = "Available Doctors"
DOCTORS_SECTION = "Doctors"


def ask_date(doctor_name: str) -> str:
    return f"You selected *{doctor_name}*.\n\nPlease choose a date:"


DATES_LIST_BTN = "View Dates"
DATES_LIST_HEADER = "Available Dates"
DATES_SECTION = "Next available"


def ask_slot(doctor_name: str, date_label: str) -> str:
    return f"*{doctor_name}* on *{date_label}*.\n\nPlease choose a time slot:"


SLOTS_LIST_BTN = "View Timings"
SLOTS_LIST_HEADER = "Available Slots"
SLOTS_SECTION = "Time slots"
MORE_ROW_TITLE = "▶️ Show more"
MORE_ROW_DESC = "See further options"


def summary(
    *,
    cfg: ClinicConfig,
    patient_name: str,
    service_name: str,
    fee_from: int,
    doctor_name: str,
    specialization: str,
    starts_at: dt.datetime,
    today: dt.date,
) -> str:
    return "\n".join(
        [
            "📋 *Booking Summary*",
            "",
            f"👤 *Patient:* {patient_name}",
            f"🦷 *Service:* {service_name}",
            f"👨‍⚕️ *Doctor:* {doctor_name}" + (f" ({specialization})" if specialization else ""),
            f"📅 *Date:* {fmt_date(starts_at.date(), today=today)}",
            f"🕐 *Time:* {fmt_time(starts_at)}",
            "",
            f"💰 *Consultation fee starts at:* {rupees(fee_from)}",
            f"💳 *Advance to confirm:* {rupees(cfg.payment.advance_amount)}",
            "",
            f"📍 {cfg.clinic.address}",
            "",
            "Please review and confirm.",
        ]
    )


def payment_instructions(cfg: ClinicConfig, ref: str, pay_url: str) -> str:
    p = cfg.payment
    return "\n".join(
        [
            "✅ *Appointment reserved!*",
            f"Booking reference: *{ref}*",
            "",
            f"To confirm, please pay the advance of *{rupees(p.advance_amount)}*.",
            "",
            "💳 *UPI Details*",
            f"UPI ID: `{p.upi_id}`",
            f"Name: {p.upi_name}",
            f"Amount: {rupees(p.advance_amount)}",
            "",
            f"👉 *Tap to pay:* {pay_url}",
            "",
            "You can also scan the QR code above with any UPI app "
            "(GPay, PhonePe, Paytm, CRED, BHIM).",
            "",
            f"⏳ This slot is held for {cfg.booking.hold_minutes} minutes.",
        ]
    )


QR_CAPTION = "Scan to pay with any UPI app"
PAYMENT_CTA = "Once you have paid, tap *I've Paid* below."


def paid_thanks(cfg: ClinicConfig, *, patient_name: str, ref: str, starts_at: dt.datetime,
                doctor_name: str, today: dt.date) -> str:
    return "\n".join(
        [
            f"🎉 *Thank you, {patient_name}!*",
            "",
            "Your appointment is booked. We look forward to seeing you! 😊",
            "",
            f"🔖 *Reference:* {ref}",
            f"👨‍⚕️ *Doctor:* {doctor_name}",
            f"📅 *Date:* {fmt_date(starts_at.date(), today=today)}",
            f"🕐 *Time:* {fmt_time(starts_at)}",
            f"📍 {cfg.clinic.address}",
            "",
            "_Our team will verify your payment shortly. "
            "Please arrive 10 minutes early._",
            "",
            f"Need anything? Call us on {cfg.clinic.phone}",
        ]
    )


def need_help(cfg: ClinicConfig) -> str:
    return "\n".join(
        [
            "🤝 *We're here to help!*",
            "",
            "Please call the clinic directly:",
            f"📱 *{cfg.clinic.phone}*",
            "",
            f"📍 {cfg.clinic.address}",
            "",
            "Our team will assist you right away.",
        ]
    )


# --- Reschedule / cancel ---
NO_BOOKINGS = (
    "You don't have any upcoming appointments with us right now.\n\n"
    "Would you like to book a new one?"
)
PICK_BOOKING_RESCHEDULE = "Which appointment would you like to reschedule?"
PICK_BOOKING_CANCEL = "Which appointment would you like to cancel?"
BOOKINGS_LIST_BTN = "View Bookings"
BOOKINGS_LIST_HEADER = "Your Appointments"
BOOKINGS_SECTION = "Upcoming"


def confirm_cancel(ref: str, doctor_name: str, starts_at: dt.datetime, today: dt.date) -> str:
    return (
        f"Are you sure you want to cancel this appointment?\n\n"
        f"🔖 {ref}\n"
        f"👨‍⚕️ {doctor_name}\n"
        f"📅 {fmt_date(starts_at.date(), today=today)} at {fmt_time(starts_at)}"
    )


def cancelled(cfg: ClinicConfig, ref: str) -> str:
    return (
        f"Your appointment *{ref}* has been cancelled.\n\n"
        f"If you paid an advance, please call {cfg.clinic.phone} regarding a refund.\n\n"
        f"We hope to see you again soon!"
    )


CANCEL_ABORTED = "No problem — your appointment is unchanged."
RESCHEDULE_INTRO = "Let's find you a new time."


def rescheduled(ref: str, starts_at: dt.datetime, doctor_name: str, today: dt.date) -> str:
    return (
        f"✅ *Appointment rescheduled!*\n\n"
        f"🔖 {ref}\n"
        f"👨‍⚕️ {doctor_name}\n"
        f"📅 {fmt_date(starts_at.date(), today=today)}\n"
        f"🕐 {fmt_time(starts_at)}\n\n"
        f"See you then! 😊"
    )


# --- Errors / fallbacks. The bot must never dead-end. ---
FALLBACK = "Sorry, I didn't quite catch that. Please use the buttons below. 👇"
NAME_TOO_SHORT = "That name looks a little short. Please enter your full name."
NAME_TOO_LONG = "That name is too long. Please enter a shorter version."
NAME_INVALID = "Please enter your name using letters only."

SLOT_TAKEN = (
    "😔 Sorry, that slot was just booked by someone else.\n\nPlease choose another time:"
)
NO_SLOTS_DATE = "😔 No free slots left on that date. Please pick another date:"
NO_DATES = (
    "😔 That doctor has no free dates in the next few days.\n\n"
    "Please choose another doctor, or call us to be added to the waiting list."
)
NO_DOCTORS = "😔 No doctors are available for that service right now. Please pick another service."

SESSION_EXPIRED = "Your session timed out, so let's start fresh. 🙂"

GENERIC_ERROR = (
    "😔 Something went wrong on our side. Please try again, "
    "or call the clinic directly if it keeps happening."
)


def hold_expired(cfg: ClinicConfig) -> str:
    return (
        f"⏳ Your {cfg.booking.hold_minutes}-minute payment window expired, so the slot "
        f"was released.\n\nWould you like to book again?"
    )
