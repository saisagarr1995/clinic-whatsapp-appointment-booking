"""Formatters, WhatsApp size limits, pagination and outbound payload shape."""

from __future__ import annotations

import datetime as dt

import pytest

from clinic_bot.flow.views import PAGE_SIZE, chunk_body, paginate, parse_more
from clinic_bot.whatsapp import messages as M
from clinic_bot.whatsapp.base import (
    BODY_MAX,
    BUTTON_TITLE_MAX,
    ROW_TITLE_MAX,
    Button,
    ButtonMessage,
    ListMessage,
    MessageTooLargeError,
    Row,
    Section,
    TextMessage,
)
from clinic_bot.whatsapp.cloud_api import build_payload

# --------------------------------------------------------------------------
# Formatters
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (300, "₹300"),
        (1200, "₹1,200"),
        (25000, "₹25,000"),
        (100000, "₹1,00,000"),
        (12345678, "₹1,23,45,678"),
    ],
)
def test_rupees_uses_indian_digit_grouping(amount, expected):
    assert M.rupees(amount) == expected


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [(9, 0, "9:00 AM"), (12, 0, "12:00 PM"), (0, 30, "12:30 AM"), (13, 30, "1:30 PM"),
     (20, 0, "8:00 PM")],
)
def test_time_formatting_is_twelve_hour(hour, minute, expected):
    assert M.fmt_time(dt.time(hour, minute)) == expected


def test_relative_dates_read_naturally():
    today = dt.date(2026, 8, 3)
    assert M.fmt_date(today, today=today).startswith("Today")
    assert M.fmt_date(today + dt.timedelta(days=1), today=today).startswith("Tomorrow")
    assert M.fmt_date(today + dt.timedelta(days=5), today=today) == "Sat, 8 Aug"


def test_date_titles_fit_the_row_limit():
    today = dt.date(2026, 8, 3)
    for offset in range(14):
        label = M.fmt_date_short(today + dt.timedelta(days=offset), today=today)
        assert len(label) <= ROW_TITLE_MAX


def test_day_ranges_collapse_when_contiguous():
    assert M.fmt_days(["mon", "tue", "wed", "thu", "fri", "sat"]) == "Mon - Sat"
    assert M.fmt_days(["mon", "wed", "fri"]) == "Mon, Wed, Fri"
    assert M.fmt_days(["sun"]) == "Sun"


# --------------------------------------------------------------------------
# Structural limits
# --------------------------------------------------------------------------


def test_more_than_three_buttons_is_refused():
    with pytest.raises(MessageTooLargeError):
        ButtonMessage(
            to="1",
            body="x",
            buttons=[Button(f"b{i}", f"B{i}") for i in range(4)],
        )


def test_duplicate_button_ids_are_refused():
    with pytest.raises(MessageTooLargeError):
        ButtonMessage(to="1", body="x", buttons=[Button("a", "A"), Button("a", "B")])


def test_more_than_ten_rows_is_refused():
    with pytest.raises(MessageTooLargeError):
        ListMessage(
            to="1",
            body="x",
            button_title="Go",
            sections=[Section("S", [Row(f"r{i}", f"R{i}") for i in range(11)])],
        )


def test_empty_list_is_refused():
    with pytest.raises(MessageTooLargeError):
        ListMessage(to="1", body="x", button_title="Go", sections=[Section("S", [])])


def test_long_titles_are_clipped_rather_than_rejected():
    button = Button("b", "A very long button title indeed")
    assert len(button.title) <= BUTTON_TITLE_MAX

    row = Row("r", "A very long row title that exceeds the limit")
    assert len(row.title) <= ROW_TITLE_MAX


def test_path_like_row_ids_are_allowed_but_empty_ids_are_not():
    with pytest.raises(MessageTooLargeError):
        Row("", "title")


# --------------------------------------------------------------------------
# Pagination and chunking
# --------------------------------------------------------------------------


def test_short_lists_are_returned_whole():
    rows = [Row(f"r{i}", f"R{i}") for i in range(10)]
    assert len(paginate(rows, offset=0, kind="svc")) == 10


def test_long_lists_gain_a_show_more_row():
    rows = [Row(f"r{i}", f"R{i}") for i in range(25)]
    page = paginate(rows, offset=0, kind="svc")

    assert len(page) == 10
    assert page[-1].id.startswith("more:")
    assert parse_more(page[-1].id) == ("svc", PAGE_SIZE)


def test_show_more_walks_to_the_end_without_looping():
    rows = [Row(f"r{i}", f"R{i}") for i in range(25)]
    seen: list[str] = []
    offset, guard = 0, 0

    while True:
        guard += 1
        assert guard < 20, "pagination did not terminate"
        page = paginate(rows, offset=offset, kind="svc")
        more = [r for r in page if r.id.startswith("more:")]
        seen.extend(r.id for r in page if not r.id.startswith("more:"))
        if not more:
            break
        offset = parse_more(more[0].id)[1]

    assert seen == [r.id for r in rows], "every row must be reachable exactly once"


def test_parse_more_rejects_rubbish():
    assert parse_more("svc:1") is None
    assert parse_more("more:svc:notanint") is None


def test_chunk_body_splits_on_blank_lines():
    text = "\n\n".join(["block " + "x" * 200 for _ in range(10)])
    chunks = chunk_body(text)

    assert len(chunks) > 1
    assert all(len(c) <= BODY_MAX for c in chunks)
    # Nothing is lost.
    assert sum(c.count("block") for c in chunks) == 10


def test_chunk_body_leaves_short_text_alone():
    assert chunk_body("short") == ["short"]


def test_chunk_body_hard_splits_one_oversized_block():
    chunks = chunk_body("y" * (BODY_MAX * 2 + 5))
    assert all(len(c) <= BODY_MAX for c in chunks)
    assert "".join(chunks) == "y" * (BODY_MAX * 2 + 5)


# --------------------------------------------------------------------------
# Cloud API payload shape
# --------------------------------------------------------------------------


def test_text_payload_shape():
    payload = build_payload(TextMessage(to="919812345678", body="hello"))
    assert payload["messaging_product"] == "whatsapp"
    assert payload["to"] == "919812345678"
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "hello"


def test_button_payload_matches_the_cloud_api_schema():
    payload = build_payload(
        ButtonMessage(to="1", body="pick", buttons=[Button("a", "A"), Button("b", "B")])
    )
    assert payload["type"] == "interactive"
    interactive = payload["interactive"]
    assert interactive["type"] == "button"
    assert interactive["body"]["text"] == "pick"
    assert interactive["action"]["buttons"][0] == {
        "type": "reply",
        "reply": {"id": "a", "title": "A"},
    }


def test_list_payload_matches_the_cloud_api_schema():
    payload = build_payload(
        ListMessage(
            to="1",
            header="H",
            body="pick",
            button_title="Open",
            sections=[Section("S", [Row("r1", "R1", "desc")])],
        )
    )
    interactive = payload["interactive"]
    assert interactive["type"] == "list"
    assert interactive["header"] == {"type": "text", "text": "H"}
    assert interactive["action"]["button"] == "Open"
    row = interactive["action"]["sections"][0]["rows"][0]
    assert row == {"id": "r1", "title": "R1", "description": "desc"}


def test_row_without_description_omits_the_key():
    payload = build_payload(
        ListMessage(
            to="1", body="b", button_title="Open",
            sections=[Section("S", [Row("r1", "R1")])],
        )
    )
    assert "description" not in payload["interactive"]["action"]["sections"][0]["rows"][0]


def test_unknown_message_type_is_refused():
    class Weird:
        to = "1"

    with pytest.raises(TypeError):
        build_payload(Weird())  # type: ignore[arg-type]
