"""SQLAlchemy models.

DATETIME CONVENTION
-------------------
All datetimes are stored NAIVE and are expressed in the clinic's local timezone
(config `clinic.timezone`). One deployment serves one clinic in one timezone, so
carrying tzinfo through SQLite adds bugs without adding value. Use
`clinic_bot.scheduling.clock.now()` to obtain "now" — never `datetime.now()`
directly, so tests can freeze time.
"""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from clinic_bot.scheduling import clock


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    """Column default. Routed through clock so it honours the clinic timezone.

    Never use `datetime.now` directly as a column default: the server may run in a
    different timezone from the clinic, which would make stored timestamps
    incomparable with the values the rest of the app computes.
    """
    return clock.now()


class BookingStatus(enum.StrEnum):
    DRAFT = "DRAFT"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    RESCHEDULED = "RESCHEDULED"


#: Statuses that occupy a slot. A slot is re-bookable in any other status.
BLOCKING_STATUSES: tuple[BookingStatus, ...] = (
    BookingStatus.PENDING_PAYMENT,
    BookingStatus.AWAITING_VERIFICATION,
    BookingStatus.CONFIRMED,
)

_BLOCKING_SQL = ", ".join(f"'{s.value}'" for s in BLOCKING_STATUSES)


doctor_services = Table(
    "doctor_services",
    Base.metadata,
    Column("doctor_id", ForeignKey("doctors.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    fee_from: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    description: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    doctors: Mapped[list[Doctor]] = relationship(
        secondary=doctor_services, back_populates="services"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Service {self.code}>"


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    specialization: Mapped[str] = mapped_column(String(120), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    services: Mapped[list[Service]] = relationship(
        secondary=doctor_services, back_populates="doctors"
    )
    schedules: Mapped[list[DoctorSchedule]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Doctor {self.code}>"


class DoctorSchedule(Base):
    """One row per weekday the doctor works."""

    __tablename__ = "doctor_schedules"
    __table_args__ = (UniqueConstraint("doctor_id", "weekday", name="uq_doctor_weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon .. 6=Sun
    start_minute: Mapped[int] = mapped_column(Integer)  # minutes from midnight
    end_minute: Mapped[int] = mapped_column(Integer)
    break_start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    break_end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    bookings: Mapped[list[Booking]] = relationship(back_populates="patient")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # THE anti-double-booking guarantee. Enforced by SQLite itself, not by
        # application logic, so two concurrent webhook deliveries cannot both win.
        # Partial: only blocking statuses occupy the slot, so a cancelled booking
        # frees its slot for re-use.
        Index(
            "uq_active_slot",
            "doctor_id",
            "starts_at",
            unique=True,
            sqlite_where=text(f"status IN ({_BLOCKING_SQL})"),
        ),
        Index("ix_booking_lookup", "patient_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))

    starts_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, native_enum=False, length=32),
        default=BookingStatus.DRAFT,
        index=True,
    )
    amount: Mapped[int] = mapped_column(Integer, default=0)

    patient_name: Mapped[str] = mapped_column(String(120), default="")
    hold_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    paid_declared_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_reason: Mapped[str] = mapped_column(String(200), default="")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    patient: Mapped[Patient] = relationship(back_populates="bookings")
    doctor: Mapped[Doctor] = relationship()
    service: Mapped[Service] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Booking {self.ref} {self.status.value} {self.starts_at}>"


class ConversationSession(Base):
    """Persisted FSM state, so a restart never strands a patient mid-booking."""

    __tablename__ = "conversation_sessions"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    state: Mapped[str] = mapped_column(String(48), default="IDLE")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    # Deliberately NO onupdate: session_store.save() always assigns this
    # explicitly. With onupdate, a save that wrote an unchanged timestamp would be
    # omitted from the UPDATE statement and onupdate would substitute server
    # wall-clock time — silently expiring every session on a server whose
    # timezone differs from the clinic's.
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class ProcessedMessage(Base):
    """Webhook idempotency.

    Meta retries webhook deliveries until it gets a 200. Without this table a retry
    would replay the patient's last action and, for example, create a second booking.
    """

    __tablename__ = "processed_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
