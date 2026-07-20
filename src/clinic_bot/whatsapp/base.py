"""Transport-agnostic message types and the adapter interface.

The bot core never imports a transport implementation. It builds the objects in
this module and hands them to whatever adapter is wired in — the real Cloud API
adapter in production, a recording fake in tests.

WhatsApp enforces hard size limits on interactive messages. Exceeding them makes
Meta reject the send with an opaque error, so the dataclasses validate on
construction: a limit violation fails in our tests, not in a patient's chat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# --- Meta-imposed limits (Cloud API, interactive messages) ---
BODY_MAX = 1024
HEADER_MAX = 60
FOOTER_MAX = 60
BUTTONS_MAX = 3
BUTTON_TITLE_MAX = 20
LIST_ROWS_MAX = 10
LIST_BUTTON_TITLE_MAX = 20
ROW_TITLE_MAX = 24
ROW_DESC_MAX = 72
SECTION_TITLE_MAX = 24
ROW_ID_MAX = 200


def _clip(value: str, limit: int) -> str:
    """Truncate free-form display text that we do not fully control."""
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


class MessageTooLargeError(ValueError):
    """A structural limit was exceeded — always a bug in the calling code."""


# --------------------------------------------------------------------------
# Inbound
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class InboundMessage:
    """A normalised inbound message, independent of transport."""

    wa_id: str
    message_id: str
    profile_name: str = ""
    text: str = ""
    #: id of the tapped reply button or selected list row, if any
    reply_id: str | None = None
    #: display title of the tapped button/row, useful for logs
    reply_title: str = ""

    @property
    def is_interactive(self) -> bool:
        return self.reply_id is not None

    @property
    def payload(self) -> str:
        """What the router matches on: the tapped id, else the typed text."""
        return self.reply_id if self.reply_id is not None else self.text.strip()


# --------------------------------------------------------------------------
# Outbound
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Button:
    id: str
    title: str

    def __post_init__(self) -> None:
        if not self.id:
            raise MessageTooLargeError("button id must not be empty")
        object.__setattr__(self, "title", _clip(self.title, BUTTON_TITLE_MAX))


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            raise MessageTooLargeError("row id must not be empty")
        if len(self.id) > ROW_ID_MAX:
            raise MessageTooLargeError(f"row id exceeds {ROW_ID_MAX} chars: {self.id!r}")
        object.__setattr__(self, "title", _clip(self.title, ROW_TITLE_MAX))
        object.__setattr__(self, "description", _clip(self.description, ROW_DESC_MAX))


@dataclass(frozen=True)
class Section:
    title: str
    rows: list[Row]

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _clip(self.title, SECTION_TITLE_MAX))


@dataclass(frozen=True)
class OutboundMessage:
    """Base class. Never sent directly."""

    to: str


@dataclass(frozen=True)
class TextMessage(OutboundMessage):
    body: str
    preview_url: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", _clip(self.body, BODY_MAX))


@dataclass(frozen=True)
class ButtonMessage(OutboundMessage):
    body: str
    buttons: list[Button]
    header: str = ""
    footer: str = ""

    def __post_init__(self) -> None:
        if not self.buttons:
            raise MessageTooLargeError("a button message needs at least one button")
        if len(self.buttons) > BUTTONS_MAX:
            raise MessageTooLargeError(
                f"WhatsApp allows at most {BUTTONS_MAX} reply buttons, got {len(self.buttons)}"
            )
        ids = [b.id for b in self.buttons]
        if len(set(ids)) != len(ids):
            raise MessageTooLargeError(f"duplicate button ids: {ids}")
        object.__setattr__(self, "body", _clip(self.body, BODY_MAX))
        object.__setattr__(self, "header", _clip(self.header, HEADER_MAX))
        object.__setattr__(self, "footer", _clip(self.footer, FOOTER_MAX))


@dataclass(frozen=True)
class ListMessage(OutboundMessage):
    body: str
    button_title: str
    sections: list[Section]
    header: str = ""
    footer: str = ""

    def __post_init__(self) -> None:
        total = sum(len(s.rows) for s in self.sections)
        if total == 0:
            raise MessageTooLargeError("a list message needs at least one row")
        if total > LIST_ROWS_MAX:
            raise MessageTooLargeError(
                f"WhatsApp allows at most {LIST_ROWS_MAX} list rows in total, got {total}. "
                f"Paginate before building the message."
            )
        ids = [r.id for s in self.sections for r in s.rows]
        if len(set(ids)) != len(ids):
            raise MessageTooLargeError(f"duplicate row ids: {ids}")
        object.__setattr__(self, "body", _clip(self.body, BODY_MAX))
        object.__setattr__(self, "header", _clip(self.header, HEADER_MAX))
        object.__setattr__(self, "footer", _clip(self.footer, FOOTER_MAX))
        object.__setattr__(self, "button_title", _clip(self.button_title, LIST_BUTTON_TITLE_MAX))


@dataclass(frozen=True)
class ImageMessage(OutboundMessage):
    """Image sent by public URL. Meta fetches the URL, so it must be reachable."""

    image_url: str
    caption: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "caption", _clip(self.caption, BODY_MAX))


@dataclass
class Reply:
    """An ordered batch of outbound messages produced by one inbound message."""

    messages: list[OutboundMessage] = field(default_factory=list)

    def add(self, message: OutboundMessage) -> Reply:
        self.messages.append(message)
        return self

    def __len__(self) -> int:
        return len(self.messages)


# --------------------------------------------------------------------------
# Adapter interface
# --------------------------------------------------------------------------


@runtime_checkable
class WhatsAppAdapter(Protocol):
    """Anything that can deliver an OutboundMessage."""

    def send(self, message: OutboundMessage) -> str | None:
        """Deliver one message. Returns the provider message id if available."""
        ...

    def send_all(self, reply: Reply) -> None:
        """Deliver a batch in order."""
        ...
