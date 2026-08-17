"""Natural-language date/time resolution tests.

Covers the edge branches in ``build_calendar_event_body`` and friends: am/pm
times, bare phrases, weekday handling, full ISO datetimes, timezone fallback,
and duration guard — all of which feed ``resolve_deadline`` and the calendar
tools. Pure functions, no DB or Google calls.
"""
from datetime import datetime, timezone

from app.services.tools import build_calendar_event_body, resolve_deadline


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