"""The conversation state machine.

One inbound message in, one ordered batch of outbound messages out. Pure with
respect to the transport: the router never touches HTTP. This is what makes the
whole flow testable without a phone.

Design rules:
  * The bot NEVER dead-ends. Every state has a fallback that re-prompts.
  * Slot availability is re-checked at confirmation, never trusted from the list.
  * All patient-visible copy comes from whatsapp/messages.py via flow/views.py.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from clinic_bot import booking_service as bookings
from clinic_bot.booking_service import SlotTakenError
from clinic_bot.clinic_config import ClinicConfig
from clinic_bot.db.models import Booking, BookingStatus, Doctor, Service
from clinic_bot.flow import ids, session_store, views
from clinic_bot.flow.session_store import FlowSession
from clinic_bot.flow.states import Mode, State
from clinic_bot.payments.upi import pay_url
from clinic_bot.scheduling import clock, slots
from clinic_bot.settings import Settings
from clinic_bot.whatsapp import messages as M
from clinic_bot.whatsapp.base import InboundMessage, Reply

log = logging.getLogger(__name__)

NAME_MIN = 2
NAME_MAX = 60


class Router:
    def __init__(self, cfg: ClinicConfig, settings: Settings, base_url: str | None = None):
        self.cfg = cfg
        self.settings = settings
        #: Public URL this clinic is reached on. In the multi-clinic fleet each
        #: clinic carries its own /c/<slug> prefix, so the payment link a patient
        #: receives always points back at *their* clinic.
        self.base_url = (base_url or settings.public_base_url).rstrip("/")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def handle(self, db: Session, inbound: InboundMessage) -> Reply:
        # Free any slots whose payment window lapsed before computing availability,
        # so an abandoned booking never blocks the next patient.
        bookings.expire_stale_holds(db)

        flow = session_store.load(db, inbound.wa_id, self.cfg)
        payload = inbound.payload

        reply = self._dispatch(db, flow, inbound, payload)

        session_store.save(db, flow)
        return reply

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        # A typed greeting from any state returns to the top. Interactive taps are
        # exempt so a button whose title happens to be "Back" cannot reset the flow.
        if not inbound.is_interactive and ids.is_reset(payload):
            return self._go_welcome(db, flow, to, note_expiry=False)

        # Session timed out: tell the patient why before starting over.
        if flow.was_expired and flow.state is State.IDLE and payload:
            return self._go_welcome(db, flow, to, note_expiry=True)

        # --- globally available buttons ---
        if payload == ids.BTN_BOOK:
            flow.state = State.BOOKING_MENU
            return views.booking_menu(to)
        if payload == ids.BTN_SERVICES:
            flow.state = State.WELCOME
            return views.services_overview(to, self.cfg)
        if payload == ids.BTN_CONTACT:
            flow.state = State.WELCOME
            return views.contact(to, self.cfg)
        if payload == ids.BTN_MAIN_MENU:
            return self._go_welcome(db, flow, to, note_expiry=False)

        handler = {
            State.IDLE: self._st_idle,
            State.WELCOME: self._st_welcome,
            State.BOOKING_MENU: self._st_booking_menu,
            State.ASK_NAME: self._st_ask_name,
            State.ASK_SERVICE: self._st_ask_service,
            State.PICK_DOCTOR: self._st_pick_doctor,
            State.PICK_DATE: self._st_pick_date,
            State.PICK_SLOT: self._st_pick_slot,
            State.SUMMARY: self._st_summary,
            State.PAYMENT: self._st_payment,
            State.PAID: self._st_paid,
            State.RESCHEDULE_PICK_BOOKING: self._st_reschedule_pick,
            State.CANCEL_PICK_BOOKING: self._st_cancel_pick,
            State.CANCEL_CONFIRM: self._st_cancel_confirm,
        }[flow.state]

        return handler(db, flow, inbound, payload)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _go_welcome(
        self, db: Session, flow: FlowSession, to: str, *, note_expiry: bool
    ) -> Reply:
        name = flow.get("name") or ""
        flow.reset()
        if name:
            flow.set("name", name)
        flow.state = State.WELCOME

        reply = views.welcome(to, self.cfg, name)
        if note_expiry:
            reply.messages.insert(0, views.simple(to, M.SESSION_EXPIRED).messages[0])
        return reply

    def _active_services(self, db: Session) -> list[Service]:
        return list(
            db.scalars(
                select(Service)
                .where(Service.active.is_(True))
                .order_by(Service.sort_order, Service.name)
            )
        )

    def _fallback(self, flow: FlowSession, to: str, db: Session) -> Reply:
        """Re-prompt the current state. The bot must never dead-end."""
        nudge = views.simple(to, M.FALLBACK)
        repeat = self._render_current(db, flow, to)
        nudge.messages.extend(repeat.messages)
        return nudge

    def _render_current(self, db: Session, flow: FlowSession, to: str) -> Reply:
        """Re-send whatever the current state is asking for."""
        state = flow.state
        if state in (State.IDLE, State.WELCOME):
            return views.welcome(to, self.cfg, flow.get("name") or "")
        if state is State.BOOKING_MENU:
            return views.booking_menu(to)
        if state is State.ASK_NAME:
            return views.simple(to, M.ASK_NAME)
        if state is State.ASK_SERVICE:
            return views.ask_service(to, flow.get("name") or "")
        if state is State.PICK_DOCTOR:
            return self._show_doctors(db, flow, to)
        if state is State.PICK_DATE:
            return self._show_dates(db, flow, to)
        if state is State.PICK_SLOT:
            return self._show_slots(db, flow, to)
        if state is State.SUMMARY:
            return self._show_summary(db, flow, to)
        if state is State.PAYMENT:
            return self._show_payment(db, flow, to)
        return views.welcome(to, self.cfg, flow.get("name") or "")

    # ------------------------------------------------------------------
    # States: entry
    # ------------------------------------------------------------------

    def _st_idle(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        return self._go_welcome(db, flow, inbound.wa_id, note_expiry=False)

    def _st_welcome(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        return self._fallback(flow, inbound.wa_id, db)

    def _st_booking_menu(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        if payload == ids.BTN_BOOK_NEW:
            flow.clear_booking_draft()
            flow.set("mode", Mode.NEW.value)
            # A returning patient does not need to retype their name.
            if flow.get("name"):
                flow.state = State.ASK_SERVICE
                return views.ask_service(to, flow.get("name"))
            flow.state = State.ASK_NAME
            return views.ask_name(to)

        if payload == ids.BTN_RESCHEDULE:
            return self._start_booking_pick(db, flow, to, mode=Mode.RESCHEDULE)

        if payload == ids.BTN_CANCEL:
            return self._start_booking_pick(db, flow, to, mode=None)

        return self._fallback(flow, to, db)

    # ------------------------------------------------------------------
    # States: book new
    # ------------------------------------------------------------------

    def _st_ask_name(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id
        if inbound.is_interactive:
            return self._fallback(flow, to, db)

        raw = (inbound.text or "").strip()
        if len(raw) < NAME_MIN:
            return views.simple(to, M.NAME_TOO_SHORT)
        if len(raw) > NAME_MAX:
            return views.simple(to, M.NAME_TOO_LONG)
        if not any(ch.isalpha() for ch in raw):
            return views.simple(to, M.NAME_INVALID)

        name = " ".join(raw.split())
        flow.set("name", name)
        bookings.get_or_create_patient(db, inbound.wa_id, name)

        flow.state = State.ASK_SERVICE
        return views.ask_service(to, name)

    def _st_ask_service(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        if payload == ids.BTN_VIEW_SERVICES:
            return views.services_list(to, self._active_services(db), offset=0)

        more = views.parse_more(payload)
        if more and more[0] == "svc":
            return views.services_list(to, self._active_services(db), offset=more[1])

        raw_id = ids.parse(ids.P_SERVICE, payload)
        if raw_id is not None and raw_id.isdigit():
            service = db.get(Service, int(raw_id))
            if service is not None and service.active:
                flow.set("service_id", service.id)
                flow.state = State.PICK_DOCTOR
                return self._show_doctors(db, flow, to)

        return self._fallback(flow, to, db)

    def _show_doctors(self, db: Session, flow: FlowSession, to: str, *, offset: int = 0) -> Reply:
        service = db.get(Service, flow.get("service_id") or 0)
        if service is None:
            flow.state = State.ASK_SERVICE
            return views.ask_service(to, flow.get("name") or "")

        doctors = slots.doctors_for_service(db, service.id)
        if not doctors:
            flow.state = State.ASK_SERVICE
            reply = views.simple(to, M.NO_DOCTORS)
            reply.messages.extend(views.ask_service(to, flow.get("name") or "").messages)
            return reply

        return views.doctors_list(to, service, doctors, offset=offset)

    def _st_pick_doctor(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        more = views.parse_more(payload)
        if more and more[0] == "doc":
            return self._show_doctors(db, flow, to, offset=more[1])

        raw_id = ids.parse(ids.P_DOCTOR, payload)
        if raw_id is not None and raw_id.isdigit():
            doctor = db.get(Doctor, int(raw_id))
            if doctor is not None and doctor.active:
                flow.set("doctor_id", doctor.id)
                flow.state = State.PICK_DATE
                return self._show_dates(db, flow, to)

        return self._fallback(flow, to, db)

    def _load_doctor_service(
        self, db: Session, flow: FlowSession
    ) -> tuple[Doctor | None, Service | None]:
        doctor = db.get(Doctor, flow.get("doctor_id") or 0)
        service = db.get(Service, flow.get("service_id") or 0)
        return doctor, service

    def _show_dates(self, db: Session, flow: FlowSession, to: str, *, offset: int = 0) -> Reply:
        doctor, service = self._load_doctor_service(db, flow)
        if doctor is None or service is None:
            flow.state = State.ASK_SERVICE
            return views.ask_service(to, flow.get("name") or "")

        exclude = flow.get("booking_id") if flow.get("mode") == Mode.RESCHEDULE.value else None
        dates = slots.available_dates(
            db, doctor=doctor, service=service, cfg=self.cfg, exclude_booking_id=exclude
        )
        if not dates:
            flow.state = State.PICK_DOCTOR
            reply = views.simple(to, M.NO_DATES)
            reply.messages.extend(self._show_doctors(db, flow, to).messages)
            return reply

        return views.dates_list(to, doctor, dates, clock.today(), offset=offset)

    def _st_pick_date(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        more = views.parse_more(payload)
        if more and more[0] == "date":
            return self._show_dates(db, flow, to, offset=more[1])

        raw = ids.parse(ids.P_DATE, payload)
        if raw is not None:
            try:
                day = dt.date.fromisoformat(raw)
            except ValueError:
                return self._fallback(flow, to, db)
            flow.set("date", day.isoformat())
            flow.state = State.PICK_SLOT
            return self._show_slots(db, flow, to)

        return self._fallback(flow, to, db)

    def _show_slots(self, db: Session, flow: FlowSession, to: str, *, offset: int = 0) -> Reply:
        doctor, service = self._load_doctor_service(db, flow)
        raw_date = flow.get("date")
        if doctor is None or service is None or not raw_date:
            flow.state = State.PICK_DATE
            return self._show_dates(db, flow, to)

        day = dt.date.fromisoformat(raw_date)
        exclude = flow.get("booking_id") if flow.get("mode") == Mode.RESCHEDULE.value else None
        free = slots.available_slots(
            db, doctor=doctor, service=service, day=day, cfg=self.cfg, exclude_booking_id=exclude
        )
        if not free:
            flow.state = State.PICK_DATE
            reply = views.simple(to, M.NO_SLOTS_DATE)
            reply.messages.extend(self._show_dates(db, flow, to).messages)
            return reply

        return views.slots_list(to, doctor, day, free, clock.today(), offset=offset)

    def _st_pick_slot(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        more = views.parse_more(payload)
        if more and more[0] == "slot":
            return self._show_slots(db, flow, to, offset=more[1])

        raw = ids.parse(ids.P_SLOT, payload)
        if raw is not None:
            try:
                start = dt.datetime.strptime(raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                return self._fallback(flow, to, db)

            flow.set("slot", start.strftime("%Y-%m-%dT%H:%M"))

            if flow.get("mode") == Mode.RESCHEDULE.value:
                return self._apply_reschedule(db, flow, to, start)

            flow.state = State.SUMMARY
            return self._show_summary(db, flow, to)

        return self._fallback(flow, to, db)

    def _show_summary(self, db: Session, flow: FlowSession, to: str) -> Reply:
        doctor, service = self._load_doctor_service(db, flow)
        raw_slot = flow.get("slot")
        if doctor is None or service is None or not raw_slot:
            flow.state = State.ASK_SERVICE
            return views.ask_service(to, flow.get("name") or "")

        start = dt.datetime.strptime(raw_slot, "%Y-%m-%dT%H:%M")
        return views.summary(
            to,
            cfg=self.cfg,
            patient_name=flow.get("name") or "",
            service=service,
            doctor=doctor,
            starts_at=start,
            today=clock.today(),
        )

    def _st_summary(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        if payload == ids.BTN_CHANGE:
            # Keep who they are, drop what they picked.
            flow.clear_booking_draft()
            flow.set("mode", Mode.NEW.value)
            flow.state = State.ASK_SERVICE
            return views.ask_service(to, flow.get("name") or "")

        if payload == ids.BTN_CONFIRM:
            return self._confirm_booking(db, flow, inbound)

        return self._fallback(flow, to, db)

    def _confirm_booking(self, db: Session, flow: FlowSession, inbound: InboundMessage) -> Reply:
        to = inbound.wa_id
        doctor, service = self._load_doctor_service(db, flow)
        raw_slot = flow.get("slot")
        if doctor is None or service is None or not raw_slot:
            flow.state = State.ASK_SERVICE
            return views.ask_service(to, flow.get("name") or "")

        start = dt.datetime.strptime(raw_slot, "%Y-%m-%dT%H:%M")
        patient = bookings.get_or_create_patient(db, to, flow.get("name") or "")

        try:
            booking = bookings.create_hold(
                db,
                cfg=self.cfg,
                patient=patient,
                doctor=doctor,
                service=service,
                start=start,
                patient_name=flow.get("name") or patient.name,
            )
        except SlotTakenError:
            # Someone else took it while this patient was reading the summary.
            flow.data.pop("slot", None)
            flow.state = State.PICK_SLOT
            reply = views.simple(to, M.SLOT_TAKEN)
            reply.messages.extend(self._show_slots(db, flow, to).messages)
            return reply

        flow.set("booking_id", booking.id)
        flow.set("ref", booking.ref)
        flow.state = State.PAYMENT
        return self._show_payment(db, flow, to)

    def _show_payment(self, db: Session, flow: FlowSession, to: str) -> Reply:
        ref = flow.get("ref")
        if not ref:
            return self._go_welcome(db, flow, to, note_expiry=False)

        return views.payment(
            to,
            cfg=self.cfg,
            ref=ref,
            pay_page_url=pay_url(self.base_url, ref),
        )

    def _st_payment(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        if payload == ids.BTN_HELP:
            return views.need_help(to, self.cfg)

        if payload == ids.BTN_PAID:
            booking = db.get(Booking, flow.get("booking_id") or 0)
            if booking is None:
                return self._go_welcome(db, flow, to, note_expiry=False)

            if booking.status is BookingStatus.EXPIRED:
                # Hold lapsed before they tapped. Be honest and restart cleanly.
                flow.clear_booking_draft()
                flow.state = State.WELCOME
                return views.with_menu_button(to, M.hold_expired(self.cfg))

            bookings.declare_paid(db, booking)
            flow.state = State.PAID
            return views.paid(
                to,
                cfg=self.cfg,
                patient_name=booking.patient_name or flow.get("name") or "",
                ref=booking.ref,
                doctor_name=booking.doctor.name,
                starts_at=booking.starts_at,
                today=clock.today(),
            )

        return self._fallback(flow, to, db)

    def _st_paid(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        if payload == ids.BTN_HELP:
            return views.need_help(inbound.wa_id, self.cfg)
        return self._go_welcome(db, flow, inbound.wa_id, note_expiry=False)

    # ------------------------------------------------------------------
    # States: reschedule / cancel
    # ------------------------------------------------------------------

    def _start_booking_pick(
        self, db: Session, flow: FlowSession, to: str, *, mode: Mode | None
    ) -> Reply:
        patient = bookings.get_or_create_patient(db, to, flow.get("name") or "")
        upcoming = bookings.upcoming_bookings(db, patient)

        if not upcoming:
            flow.state = State.WELCOME
            return views.with_menu_button(to, M.NO_BOOKINGS)

        if mode is Mode.RESCHEDULE:
            flow.set("mode", Mode.RESCHEDULE.value)
            flow.state = State.RESCHEDULE_PICK_BOOKING
            prompt = M.PICK_BOOKING_RESCHEDULE
        else:
            flow.state = State.CANCEL_PICK_BOOKING
            prompt = M.PICK_BOOKING_CANCEL

        return views.bookings_list(to, upcoming, clock.today(), prompt=prompt)

    def _resolve_booking(self, db: Session, to: str, payload: str) -> Booking | None:
        ref = ids.parse(ids.P_BOOKING, payload)
        if ref is None:
            return None
        booking = bookings.booking_by_ref(db, ref)
        # Never let one patient act on another's booking.
        if booking is None or booking.patient.wa_id != to:
            return None
        return booking

    def _st_reschedule_pick(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id
        booking = self._resolve_booking(db, to, payload)
        if booking is None:
            return self._fallback(flow, to, db)

        flow.set("booking_id", booking.id)
        flow.set("ref", booking.ref)
        flow.set("doctor_id", booking.doctor_id)
        flow.set("service_id", booking.service_id)
        flow.set("mode", Mode.RESCHEDULE.value)
        flow.data.pop("date", None)
        flow.data.pop("slot", None)
        flow.state = State.PICK_DATE

        reply = views.simple(to, M.RESCHEDULE_INTRO)
        reply.messages.extend(self._show_dates(db, flow, to).messages)
        return reply

    def _apply_reschedule(
        self, db: Session, flow: FlowSession, to: str, start: dt.datetime
    ) -> Reply:
        booking = db.get(Booking, flow.get("booking_id") or 0)
        doctor, service = self._load_doctor_service(db, flow)
        if booking is None or doctor is None or service is None:
            return self._go_welcome(db, flow, to, note_expiry=False)

        try:
            bookings.reschedule_booking(
                db, cfg=self.cfg, booking=booking, doctor=doctor, service=service, new_start=start
            )
        except SlotTakenError:
            flow.state = State.PICK_SLOT
            reply = views.simple(to, M.SLOT_TAKEN)
            reply.messages.extend(self._show_slots(db, flow, to).messages)
            return reply

        flow.clear_booking_draft()
        flow.set("mode", Mode.NEW.value)
        flow.state = State.WELCOME
        return views.simple(
            to,
            M.rescheduled(booking.ref, start, doctor.name, clock.today()),
        )

    def _st_cancel_pick(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id
        booking = self._resolve_booking(db, to, payload)
        if booking is None:
            return self._fallback(flow, to, db)

        flow.set("booking_id", booking.id)
        flow.set("ref", booking.ref)
        flow.state = State.CANCEL_CONFIRM
        return views.confirm_cancel(to, booking, clock.today())

    def _st_cancel_confirm(
        self, db: Session, flow: FlowSession, inbound: InboundMessage, payload: str
    ) -> Reply:
        to = inbound.wa_id

        if payload == ids.BTN_CANCEL_YES:
            booking = db.get(Booking, flow.get("booking_id") or 0)
            if booking is not None and booking.patient.wa_id == to:
                bookings.cancel_booking(db, booking, reason="patient")
                ref = booking.ref
            else:
                ref = flow.get("ref") or ""
            flow.clear_booking_draft()
            flow.state = State.WELCOME
            reply = views.simple(to, M.cancelled(self.cfg, ref))
            reply.messages.extend(views.with_menu_button(to, M.SERVICES_CTA).messages)
            return reply

        if payload == ids.BTN_CANCEL_NO:
            flow.clear_booking_draft()
            flow.state = State.WELCOME
            reply = views.simple(to, M.CANCEL_ABORTED)
            reply.messages.extend(views.with_menu_button(to, M.SERVICES_CTA).messages)
            return reply

        return self._fallback(flow, to, db)
