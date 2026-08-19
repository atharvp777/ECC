"""Natural-language date/time resolution tests.

Covers the edge branches in ``build_calendar_event_body`` and friends: am/pm
times, bare phrases, weekday handling, full ISO datetimes, timezone fallback,
day-of-month + month-name phrases, and duration guard — all of which feed
``resolve_deadline`` and the calendar tools. Pure functions, no DB or Google
calls.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.tools import (
    build_calendar_event_body,
    resolve_deadline,
    _resolve_event_date,
)


def _body(**kwargs):
    return build_calendar_event_body({
        "summary": "s",
        "duration_minutes": 60,
        "timezone": "Asia/Kolkata",
        **kwargs,
    })


def test_ampm_time_resolution():
    body = _body(when="tomorrow", start_time="2pm")
    assert body["start"]["dateTime"].endswith("T14:00:00+05:30")


def test_am_time_resolution():
    body = _body(when="tomorrow", start_time="9am")
    assert body["start"]["dateTime"].endswith("T09:00:00+05:30")


def test_bare_phrase_defaults_to_default_hour():
    body = _body(when="next friday")
    assert "T09:00:00" in body["start"]["dateTime"]


def test_full_iso_datetime_passed_in_when():
    body = _body(when="2026-08-20T18:30:00")
    assert "2026-08-20T18:30:00" in body["start"]["dateTime"]


def test_struct_start_end_passed_verbatim():
    body = build_calendar_event_body({
        "summary": "meeting",
        "start": {"dateTime": "2026-08-20T10:00:00"},
        "end": {"dateTime": "2026-08-20T11:00:00"},
        "description": "d",
        "location": "room 1",
    })
    assert body["summary"] == "meeting"
    assert body["start"]["dateTime"] == "2026-08-20T10:00:00"
    assert body["location"] == "room 1"


def test_invalid_timezone_falls_back_to_system():
    body = build_calendar_event_body({
        "summary": "s",
        "when": "tomorrow",
        "timezone": "Not/AZone",
        "duration_minutes": 60,
    })
    # Asia/Kolkata default: +05:30.
    assert body["start"]["dateTime"].endswith("+05:30")


def test_nonpositive_duration_reset_to_default():
    body = _body(when="tomorrow", duration_minutes=0)
    assert body["end"]["dateTime"].endswith("T10:00:00+05:30")  # 60m later


def test_resolve_deadline_empty_returns_none():
    assert resolve_deadline(None) is None
    assert resolve_deadline("") is None


def test_resolve_deadline_full_iso():
    result = resolve_deadline("2026-09-01T17:00:00")
    # The parsed value keeps its source offset (Asia/Kolkata default).
    assert result.year == 2026 and result.month == 9 and result.day == 1
    assert result.hour == 17 and result.minute == 0
    assert result.tzinfo is not None


def test_weekday_next_and_plain():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)  # Tuesday
    # "next monday" is the Monday after the coming one.
    body = _body(when="next monday")
    monday = datetime.fromisoformat(body["start"]["dateTime"]).date()
    assert monday.weekday() == 0

    # A plain weekday name also resolves (never the same-day).
    body = _body(when="tuesday")
    tuesday = datetime.fromisoformat(body["start"]["dateTime"]).date()
    assert tuesday.weekday() == 1
    assert tuesday != now.date()


# ----------------------------------------------------------------------
# Day-of-month + month-name phrases (regression: 29 August → 19 August)
# ----------------------------------------------------------------------
FROZEN_NOW = datetime(2026, 8, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))  # Wednesday


def test_month_day_phrase_never_defaults_to_today():
    """Regression test for the reminder bug: 'on 29th on august remind me …'
    created the event on 2026-08-19 (today) because the phrase fell through
    the resolver. Every natural spelling of 29 August must resolve to
    2026-08-29, never to the frozen 'today'."""
    for phrase in (
        "29th august",
        "29 august",
        "29th of august",
        "29th on august",
        "on 29th on august",
        "august 29",
        "august 29th",
    ):
        assert _resolve_event_date(phrase, FROZEN_NOW) == date(2026, 8, 29), (
            f"{phrase!r} resolved to {_resolve_event_date(phrase, FROZEN_NOW)!s}"
        )


def test_month_day_phrase_full_event_body():
    body = build_calendar_event_body(
        {"summary": "s", "when": "29th on august", "timezone": "Asia/Kolkata"},
        now=FROZEN_NOW,
    )
    assert "2026-08-29T09:00:00+05:30" in body["start"]["dateTime"]


def test_resolve_deadline_month_day_phrase():
    result = resolve_deadline("29th august", now=FROZEN_NOW)
    assert result.year == 2026 and result.month == 8 and result.day == 29
    assert result.tzinfo is not None


def test_month_day_past_date_rolls_to_next_year():
    # 15 August is before the frozen 19 August 2026 → next year.
    assert _resolve_event_date("15th august", FROZEN_NOW) == date(2027, 8, 15)
    # 25 August is still in 2026.
    assert _resolve_event_date("25th august", FROZEN_NOW) == date(2026, 8, 25)


@pytest.mark.parametrize(
    "phrase,expected",
    [
        ("29 August", date(2026, 8, 29)),
        ("29th August", date(2026, 8, 29)),
        ("August 29", date(2026, 8, 29)),
        ("August 29th", date(2026, 8, 29)),
        # Different months and days — not an August-specific patch.
        ("29 September", date(2026, 9, 29)),
        ("September 29th", date(2026, 9, 29)),
        ("4 October", date(2026, 10, 4)),
        ("October 4th", date(2026, 10, 4)),
        ("31 December", date(2026, 12, 31)),
        ("1 January", date(2027, 1, 1)),      # past this year → rolls
        ("June 5", date(2027, 6, 5)),         # past this year → rolls
    ],
)
def test_month_day_variants_and_other_months(phrase, expected):
    """Every spelling of an explicit day+month resolves to that exact date at
    the frozen 2026-08-19 system date — the current day (19) can never
    overwrite an explicitly supplied day."""
    assert _resolve_event_date(phrase, FROZEN_NOW) == expected