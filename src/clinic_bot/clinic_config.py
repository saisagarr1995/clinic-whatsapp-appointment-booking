"""Loader and validator for config/clinic.yaml.

Everything clinic-specific is defined here so that onboarding a new clinic is a
data change, never a code change. Validation is strict and fails loudly at startup:
a clinic operator should learn about a bad config during setup, not when a patient
is mid-booking.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

# WhatsApp interactive-message limits. Exceeding these makes Meta reject the
# message at send time, so we validate against them up front.
LIST_ROW_TITLE_MAX = 24
LIST_ROW_DESC_MAX = 72

WEEKDAYS: dict[str, int] = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


class ConfigError(RuntimeError):
    """Raised when clinic.yaml is missing or invalid."""


def _parse_time(value: str, field: str) -> dt.time:
    try:
        hour, minute = value.strip().split(":")
        return dt.time(int(hour), int(minute))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must look like 'HH:MM' (24-hour), got {value!r}") from exc


class Break(BaseModel):
    start: str
    end: str

    @property
    def start_time(self) -> dt.time:
        return _parse_time(self.start, "break.start")

    @property
    def end_time(self) -> dt.time:
        return _parse_time(self.end, "break.end")

    @model_validator(mode="after")
    def _check_order(self) -> Break:
        if self.start_time >= self.end_time:
            raise ValueError("break.start must be earlier than break.end")
        return self


class Hours(BaseModel):
    open: str
    close: str
    days: list[str] = Field(default_factory=list)
    brk: Break | None = Field(default=None, alias="break")

    model_config = {"populate_by_name": True}

    @property
    def open_time(self) -> dt.time:
        return _parse_time(self.open, "hours.open")

    @property
    def close_time(self) -> dt.time:
        return _parse_time(self.close, "hours.close")

    @field_validator("days")
    @classmethod
    def _check_days(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d.lower() not in WEEKDAYS]
        if bad:
            raise ValueError(f"unknown weekday(s) {bad}; use any of {list(WEEKDAYS)}")
        return [d.lower() for d in v]

    @property
    def weekday_numbers(self) -> set[int]:
        return {WEEKDAYS[d] for d in self.days}

    @model_validator(mode="after")
    def _check_order(self) -> Hours:
        if self.open_time >= self.close_time:
            raise ValueError(f"open ({self.open}) must be earlier than close ({self.close})")
        return self


class ClinicInfo(BaseModel):
    name: str
    tagline: str = ""
    phone: str
    address: str
    timezone: str = "Asia/Kolkata"
    hours: Hours

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "")
        if not cleaned.startswith("+"):
            raise ValueError("clinic.phone must be in international format, e.g. +919000000000")
        return cleaned


class BookingRules(BaseModel):
    slot_minutes: int = Field(default=30, ge=5, le=240)
    advance_days: int = Field(default=7, ge=1, le=90)
    hold_minutes: int = Field(default=15, ge=1, le=180)
    min_notice_minutes: int = Field(default=60, ge=0, le=10_080)


class SessionRules(BaseModel):
    timeout_minutes: int = Field(default=30, ge=1, le=1440)


class PaymentInfo(BaseModel):
    upi_id: str
    upi_name: str
    advance_amount: int = Field(ge=1)
    currency: str = "INR"

    @field_validator("upi_id")
    @classmethod
    def _check_vpa(cls, v: str) -> str:
        cleaned = v.strip()
        # A UPI VPA is <handle>@<psp>. This catches the common setup mistake of
        # pasting a phone number or an email-looking value with no PSP.
        if "@" not in cleaned or cleaned.startswith("@") or cleaned.endswith("@"):
            raise ValueError(f"payment.upi_id must look like 'name@bank', got {v!r}")
        return cleaned


class ServiceCfg(BaseModel):
    code: str
    name: str
    fee_from: int = Field(ge=0)
    duration_minutes: int = Field(default=30, ge=5, le=480)
    description: str = ""

    @field_validator("name")
    @classmethod
    def _check_name_len(cls, v: str) -> str:
        if len(v) > LIST_ROW_TITLE_MAX:
            raise ValueError(
                f"service name {v!r} is {len(v)} chars; WhatsApp list rows allow "
                f"{LIST_ROW_TITLE_MAX}. Shorten it."
            )
        return v

    @field_validator("description")
    @classmethod
    def _check_desc_len(cls, v: str) -> str:
        if len(v) > LIST_ROW_DESC_MAX:
            raise ValueError(
                f"service description is {len(v)} chars; WhatsApp allows "
                f"{LIST_ROW_DESC_MAX}. Shorten it."
            )
        return v


class DoctorCfg(BaseModel):
    code: str
    name: str
    specialization: str = ""
    services: list[str]
    working_days: list[str]
    hours: Hours | None = None

    @field_validator("working_days")
    @classmethod
    def _check_days(cls, v: list[str]) -> list[str]:
        bad = [d for d in v if d.lower() not in WEEKDAYS]
        if bad:
            raise ValueError(f"doctor working_days has unknown day(s) {bad}")
        if not v:
            raise ValueError("doctor must have at least one working day")
        return [d.lower() for d in v]

    @field_validator("name")
    @classmethod
    def _check_name_len(cls, v: str) -> str:
        if len(v) > LIST_ROW_TITLE_MAX:
            raise ValueError(
                f"doctor name {v!r} is {len(v)} chars; WhatsApp list rows allow "
                f"{LIST_ROW_TITLE_MAX}. Shorten it."
            )
        return v

    @property
    def weekday_numbers(self) -> set[int]:
        return {WEEKDAYS[d] for d in self.working_days}


class ClinicConfig(BaseModel):
    clinic: ClinicInfo
    booking: BookingRules = Field(default_factory=BookingRules)
    session: SessionRules = Field(default_factory=SessionRules)
    payment: PaymentInfo
    services: list[ServiceCfg]
    doctors: list[DoctorCfg]

    @model_validator(mode="after")
    def _cross_check(self) -> ClinicConfig:
        if not self.services:
            raise ValueError("at least one service must be defined")
        if not self.doctors:
            raise ValueError("at least one doctor must be defined")

        service_codes = [s.code for s in self.services]
        dupes = {c for c in service_codes if service_codes.count(c) > 1}
        if dupes:
            raise ValueError(f"duplicate service code(s): {sorted(dupes)}")

        doctor_codes = [d.code for d in self.doctors]
        dupes = {c for c in doctor_codes if doctor_codes.count(c) > 1}
        if dupes:
            raise ValueError(f"duplicate doctor code(s): {sorted(dupes)}")

        known = set(service_codes)
        for doc in self.doctors:
            unknown = [s for s in doc.services if s not in known]
            if unknown:
                raise ValueError(
                    f"doctor {doc.code!r} lists service(s) {unknown} that are not defined "
                    f"under `services`. Known codes: {sorted(known)}"
                )
            if not doc.services:
                raise ValueError(f"doctor {doc.code!r} provides no services")

        # A service nobody provides can never be booked; that is always a config mistake.
        provided = {s for d in self.doctors for s in d.services}
        orphans = known - provided
        if orphans:
            raise ValueError(
                f"service(s) {sorted(orphans)} have no doctor providing them. "
                f"Either assign a doctor or remove the service."
            )
        return self

    def service_by_code(self, code: str) -> ServiceCfg | None:
        return next((s for s in self.services if s.code == code), None)

    def doctor_by_code(self, code: str) -> DoctorCfg | None:
        return next((d for d in self.doctors if d.code == code), None)

    def doctor_hours(self, doctor: DoctorCfg) -> Hours:
        """Doctor-specific hours, falling back to clinic hours."""
        return doctor.hours or self.clinic.hours


def load_clinic_config(path: str | Path) -> ClinicConfig:
    p = Path(path)
    if not p.exists():
        raise ConfigError(
            f"Clinic config not found at {p}.\n"
            f"Run `python setup.py` to create it, or copy config/clinic.yaml.example."
        )
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p} is not valid YAML:\n{exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{p} must contain a YAML mapping at the top level.")

    try:
        return ClinicConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{p} is invalid:\n{exc}") from exc


@lru_cache
def get_clinic_config() -> ClinicConfig:
    from clinic_bot.settings import get_settings

    return load_clinic_config(get_settings().clinic_config_path)
