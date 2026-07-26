"""Recording adapter used by the test suite and the offline self-test.

Records everything the bot would have sent so tests can assert on exact button
ids, row ids and copy — with no network and no Meta credentials.
"""

from __future__ import annotations

from clinic_bot.whatsapp.base import (
    ButtonMessage,
    ListMessage,
    OutboundMessage,
    Reply,
    TextMessage,
)


class FakeAdapter:
    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []
        self._counter = 0

    def send(self, message: OutboundMessage) -> str | None:
        self.sent.append(message)
        self._counter += 1
        return f"fake.msg.{self._counter}"

    def send_all(self, reply: Reply) -> None:
        for message in reply.messages:
            self.send(message)

    # --- assertion helpers -------------------------------------------------

    def clear(self) -> None:
        self.sent.clear()

    @property
    def last(self) -> OutboundMessage | None:
        return self.sent[-1] if self.sent else None

    def texts(self) -> list[str]:
        return [
            m.body
            for m in self.sent
            if isinstance(m, TextMessage | ButtonMessage | ListMessage)
        ]

    def all_text(self) -> str:
        return "\n".join(self.texts())

    def button_ids(self) -> list[str]:
        return [b.id for m in self.sent if isinstance(m, ButtonMessage) for b in m.buttons]

    def row_ids(self) -> list[str]:
        return [
            r.id
            for m in self.sent
            if isinstance(m, ListMessage)
            for s in m.sections
            for r in s.rows
        ]

    def row_titles(self) -> list[str]:
        return [
            r.title
            for m in self.sent
            if isinstance(m, ListMessage)
            for s in m.sections
            for r in s.rows
        ]

    def has_button(self, button_id: str) -> bool:
        return button_id in self.button_ids()

    def has_row_prefix(self, prefix: str) -> bool:
        return any(r.startswith(prefix) for r in self.row_ids())

    def contains(self, needle: str) -> bool:
        return needle.lower() in self.all_text().lower()
