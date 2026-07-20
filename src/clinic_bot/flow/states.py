"""Conversation states. See PROJECT_PLAN.md section 3.1 for the transition diagram."""

from __future__ import annotations

import enum


class State(enum.StrEnum):
    IDLE = "IDLE"
    WELCOME = "WELCOME"
    BOOKING_MENU = "BOOKING_MENU"

    # Book new
    ASK_NAME = "ASK_NAME"
    ASK_SERVICE = "ASK_SERVICE"
    PICK_DOCTOR = "PICK_DOCTOR"
    PICK_DATE = "PICK_DATE"
    PICK_SLOT = "PICK_SLOT"
    SUMMARY = "SUMMARY"
    PAYMENT = "PAYMENT"
    PAID = "PAID"

    # Reschedule / cancel
    RESCHEDULE_PICK_BOOKING = "RESCHEDULE_PICK_BOOKING"
    CANCEL_PICK_BOOKING = "CANCEL_PICK_BOOKING"
    CANCEL_CONFIRM = "CANCEL_CONFIRM"


class Mode(enum.StrEnum):
    """Whether the date/slot pickers are creating or moving a booking."""

    NEW = "new"
    RESCHEDULE = "reschedule"
