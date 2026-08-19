"""Reminder-correction follow-up regression tests.

Regression for the dogfooding bug: 'on 29th on august remind me of selling
DamCapital shares' created the event on 2026-08-19 (today) instead of
2026-08-29, and the follow-up 'add that reminder for 29th august not 19th'
was treated as a calendar lookup.

These tests pin the deterministic server-side correction flow:

  A. ``_reminder_correction_when`` detects correction phrasing and extracts
     the corrected date (never a fresh-create false positive).
  B. Correction of a recent CALENDAR EVENT (reminders are events) → the
     event is UPDATED to 29 August, never duplicated.
  C. Full create → correct flow: exactly one create, one update (no dup).
  D. Correction of a recent reminder TASK → routed through
     add_task_to_calendar; task is not marked done.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Task
from app.models.task import TaskType, TaskStatus
from app.services import google_calendar
from app.services.ai_service import (
    chat_with_ai,
    _reminder_correction_when,
    _clear_recent_calendar_events,
    _record_recent_calendar_event,
)
from app.services.tools import SYSTEM_TIMEZONE


def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=None
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_recent_events():
    _clear_recent_calendar_events()
    yield
    _clear_recent_calendar_events()


# ----------------------------------------------------------------------
# A. Correction phrasing detection
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("add that reminder for 29th august not 19th", "29th august"),
        ("add that reminder for 29th on august not 19th", "29th on august"),
        ("change that reminder to august 29", "august 29"),
        ("move that reminder to the 29th of august", "29th of august"),
        ("the reminder should be on august 29th", "august 29th"),
    ],
)
def test_reminder_correction_when_extracts_date(text, expected):
    assert _reminder_correction_when(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # Fresh creation is NOT a correction.
        "remind me to sell DamCapital shares on 29th august",
        "set a reminder for 29th august",
        # Not about a reminder at all.
        "add that meeting for 29th august not 19th",
        # No date correction.
        "remind me about that on friday",
    ],
)
def test_reminder_correction_when_ignores_non_corrections(text):
    assert _reminder_correction_when(text) is None


# ----------------------------------------------------------------------
# B. Correction of a recent calendar event (reminders are events)
# ----------------------------------------------------------------------
def test_reminder_correction_updates_recent_event(db_session):
    """'add that reminder for 29th august not 19th' updates the event the user
    just made to 2026-08-29 — never a lookup, never a duplicate create."""
    _record_recent_calendar_event("evt_reminder", "Sell DamCapital shares and buy HDFC")

    with patch("app.services.ai_service.is_connected", return_value=False), \
         patch("app.services.tools.gc_update_calendar_event") as mock_update, \
         patch("app.services.tools.gc_create_calendar_event") as mock_create:
        mock_update.return_value = {
            "id": "evt_reminder",
            "summary": "Sell DamCapital shares and buy HDFC",
            "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "status": "confirmed",
        }
        reply = chat_with_ai(
            [{"role": "user", "content": "add that reminder for 29th august not 19th"}],
            db_session,
        )

    # The existing event was updated, never duplicated.
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE
    mock_create.assert_not_called()
    assert "Updated calendar event" in reply


# ----------------------------------------------------------------------
# C. Full create → correct flow: one create, one update, no duplicate
# ----------------------------------------------------------------------
def test_create_then_correct_reminder_no_duplicate(db_session):
    """The full two-turn dogfooding flow: create on 29th august, then correct
    to 'not 19th' — the second turn UPDATES, it never inserts a second event."""
    planner_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "Sell DamCapital shares and buy HDFC",
            "description": None,
            "when": "29th on august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(planner_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "Sell DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "Sell DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [{"role": "user", "content": "on 29th on august remind me of selling DamCapital shares and buy HDFC"}],
                db_session,
            )

            reply2 = chat_with_ai(
                [
                    {"role": "user", "content": "on 29th on august remind me of selling DamCapital shares and buy HDFC"},
                    {"role": "assistant", "content": reply1},
                    {"role": "user", "content": "add that reminder for 29th august not 19th"},
                ],
                db_session,
            )

    assert "Created calendar event" in reply1
    # One insert happened (the original create) — the correction only updated.
    mock_create.assert_called_once()
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert "Updated calendar event" in reply2


# ----------------------------------------------------------------------
# D. Correction of a recent reminder TASK (task-calendar path)
# ----------------------------------------------------------------------
def test_reminder_correction_reroutes_to_reminder_task(db_session):
    """When the reminder is stored as a task, the correction goes through
    add_task_to_calendar: the linked event is created once, the task is NOT
    marked done, and the corrected start is 29 August Asia/Kolkata."""
    task = Task(
        title="Sell DamCapital shares and buy HDFC",
        task_type=TaskType.REMINDER.value,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    with patch("app.services.ai_service.is_connected", return_value=False), \
         patch.object(
        google_calendar, "create_calendar_event"
    ) as mock_create, patch.object(
        google_calendar, "update_calendar_event"
    ) as mock_update:
        mock_create.return_value = {
            "id": "evt_from_task",
            "summary": "Sell DamCapital shares and buy HDFC",
            "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "status": "confirmed",
        }
        reply = chat_with_ai(
            [{"role": "user", "content": "add that reminder for 29th august not 19th"}],
            db_session,
        )

    db_session.refresh(task)
    # Event linked once; nothing duplicated; task untouched by completion.
    mock_create.assert_called_once()
    mock_update.assert_not_called()
    assert task.google_calendar_event_id == "evt_from_task"
    assert task.status == TaskStatus.TODO
    assert task.completed_at is None
    insert_body = mock_create.call_args.args[0]
    assert insert_body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert insert_body["start"]["timeZone"] == SYSTEM_TIMEZONE
    assert "Google Calendar" in reply
