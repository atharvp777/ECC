"""Pronoun-based reminder follow-up regression tests.

Regression for the dogfooding reproduction:

  Turn 1: "set a reminder for 29th august for selling DamCapital shares and
           buy HDFC"        → event must be 2026-08-29 (never today, the 19th).
  Turn 2: "set it for 29 August you did it for 19"
  Turn 2':"you did it for 19, set it for 29"

"it" must resolve to the reminder Orbit just created (the immediately
preceding successful action), never a Google Calendar title lookup, and must
UPDATE the existing event (or task + its linked event) without duplicating it.

The current-date fixture is fixed at 2026-08-19 Asia/Kolkata so the "today"
fallback can never silently satisfy these assertions on a later calendar day.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Task
from app.models.task import TaskType
from app.services import google_calendar
from app.services.ai_service import (
    chat_with_ai,
    _reminder_correction_when,
    _reminder_correction_day,
    _reminder_correction_intent,
    _reminder_correction_time,
    _reminder_correction_plan,
    _record_recent_calendar_event,
    _clear_recent_calendar_events,
)
from app.services.tools import SYSTEM_TIMEZONE


class _FrozenDatetime(datetime):
    """datetime subclass pinned to 2026-08-19 09:00 Asia/Kolkata."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 8, 19, 9, 0, 0, tzinfo=tz or ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def frozen_2026_08_19(monkeypatch):
    monkeypatch.setattr("app.services.tools.datetime", _FrozenDatetime)


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


def _mock_groq_response(text: str):
    mock_choice = MagicMock()
    mock_choice.message.content = text
    mock_choice.message.role = "assistant"
    mock = MagicMock()
    mock.choices = [mock_choice]
    return mock


# ----------------------------------------------------------------------
# A. Correction-phrase detection
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("set it for 29 August you did it for 19", "29 august"),
        ("set it for 29 August", "29 august"),
        ("change it to august 29", "august 29"),
        ("you did it for the 19th, set it for the 29th", None),  # bare day
    ],
)
def test_reminder_correction_when_pronoun_forms(text, expected):
    assert _reminder_correction_when(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("set it for 29 August you did it for 19", 29),
        ("you did it for 19, set it for 29", 29),
        ("it was the 19th, make it the 29th", 29),
        ("set it for tomorrow", None),
        ("no date here at all", None),
    ],
)
def test_reminder_correction_day(text, expected):
    assert _reminder_correction_day(text) == expected


def test_reminder_correction_when_still_ignores_fresh_creations():
    assert _reminder_correction_when("set a reminder for 29th august") is None
    assert _reminder_correction_when("remind me to sell shares on 29th august") is None
    assert _reminder_correction_when("create a task and set it for tomorrow") is None


# ----------------------------------------------------------------------
# B. Full create → pronoun correction: one create, one update, no duplicate
# ----------------------------------------------------------------------
def test_pronoun_correction_updates_recent_event(frozen_2026_08_19, db_session):
    """'set it for 29 August you did it for 19' after a 29-August creation must
    UPDATE the just-created event — never duplicate it, never look it up by
    title, never touch today."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "selling DamCapital shares and buy HDFC",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    }
                ],
                db_session,
            )
            reply2 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    },
                    {"role": "assistant", "content": reply1},
                    {
                        "role": "user",
                        "content": "set it for 29 August you did it for 19",
                    },
                ],
                db_session,
            )

    # The creation itself landed on 29 August, never on today (the 19th).
    created_body = mock_create.call_args.args[0]
    assert created_body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert created_body["start"]["timeZone"] == SYSTEM_TIMEZONE

    # Exactly one insert and one in-place update, both against evt_reminder.
    mock_create.assert_called_once()
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE
    assert "Updated calendar event" in reply2


def test_bare_day_correction_combines_with_reminder_month(
    frozen_2026_08_19, db_session
):
    """'you did it for 19, set it for 29' has no month word — the new day (29)
    must be combined with the reminder's own month (August)."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "selling DamCapital shares and buy HDFC",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    }
                ],
                db_session,
            )
            reply2 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    },
                    {"role": "assistant", "content": reply1},
                    {"role": "user", "content": "you did it for 19, set it for 29"},
                ],
                db_session,
            )

    mock_create.assert_called_once()
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE
    assert "Updated calendar event" in reply2


def test_repeated_correction_is_idempotent(frozen_2026_08_19, db_session):
    """Two consecutive corrections still never create a second event."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "selling DamCapital shares and buy HDFC",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [{"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"}],
                db_session,
            )
            base = [
                {"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"},
                {"role": "assistant", "content": reply1},
            ]
            reply2 = chat_with_ai(
                base + [{"role": "user", "content": "set it for 29 August you did it for 19"}],
                db_session,
            )
            reply3 = chat_with_ai(
                base
                + [{"role": "user", "content": "set it for 29 August you did it for 19"},
                   {"role": "assistant", "content": reply2},
                   {"role": "user", "content": "you did it for the 19th, set it for the 29th"}],
                db_session,
            )

    mock_create.assert_called_once()
    # One in-place update per correction turn, all against the same event.
    assert mock_update.call_count == 2
    for call in mock_update.call_args_list:
        assert call.args[0] == "evt_reminder"
        assert call.args[1]["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"


# ----------------------------------------------------------------------
# C. Pronoun correction when the reminder is a TASK with a linked event
# ----------------------------------------------------------------------
def test_pronoun_correction_updates_task_linked_event(
    frozen_2026_08_19, db_session
):
    """When the reminder is stored as a task with a linked event, 'set it for
    29 August' updates the task's schedule AND its linked event — no second
    event, no Aug-19 event left behind."""
    task = Task(
        title="selling DamCapital shares and buy HDFC",
        task_type=TaskType.REMINDER.value,
        google_calendar_event_id="evt_from_task",
        scheduled_start=datetime(2026, 8, 19, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
        scheduled_end=datetime(2026, 8, 19, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
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
            "id": "evt_duplicate",
            "summary": "selling DamCapital shares and buy HDFC",
            "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "status": "confirmed",
        }
        mock_update.return_value = {
            "id": "evt_from_task",
            "summary": "selling DamCapital shares and buy HDFC",
            "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "status": "confirmed",
        }

        reply = chat_with_ai(
            [{"role": "user", "content": "set it for 29 August you did it for 19"}],
            db_session,
        )

    db_session.refresh(task)
    # The existing linked event was UPDATED; nothing was inserted.
    mock_update.assert_called_once()
    mock_create.assert_not_called()
    assert task.google_calendar_event_id == "evt_from_task"
    assert task.scheduled_start.year == 2026
    assert task.scheduled_start.month == 8
    assert task.scheduled_start.day == 29
    assert "Google Calendar" in reply


# ----------------------------------------------------------------------
# D. Planner emits an explicit date → backend preserves it (create path)
# ----------------------------------------------------------------------
def test_planner_explicit_date_reaches_created_task(frozen_2026_08_19, db_session):
    """create_task with schedule_on_calendar and when='29th august' must store
    the task's schedule AND its calendar event on 29 August, never today."""
    create_payload = {
        "tool": "create_task",
        "args": {
            "title": "selling DamCapital shares and buy HDFC",
            "priority": "medium",
            "task_type": "reminder",
            "deadline_when": None,
            "project_name": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "schedule_on_calendar": True,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch.object(
            google_calendar, "create_calendar_event"
        ) as mock_create:
            mock_create.return_value = {
                "id": "evt_from_task",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            chat_with_ai(
                [{"role": "user", "content": "create a task to sell DamCapital shares on the 29th of august"}],
                db_session,
            )

    task = db_session.query(Task).one()
    assert task.scheduled_start.year == 2026
    assert task.scheduled_start.month == 8
    assert task.scheduled_start.day == 29
    assert task.google_calendar_event_id == "evt_from_task"
    inserted = mock_create.call_args.args[0]
    assert inserted["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert inserted["start"]["timeZone"] == SYSTEM_TIMEZONE


def test_planner_explicit_date_reaches_created_event(frozen_2026_08_19, db_session):
    """create_calendar_event with when='29th august' sends 2026-08-29 to
    Google Calendar, never today's 19th."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "selling DamCapital shares and buy HDFC",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "selling DamCapital shares and buy HDFC",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            chat_with_ai(
                [{"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"}],
                db_session,
            )

    inserted = mock_create.call_args.args[0]
    assert inserted["start"]["dateTime"] == "2026-08-29T09:00:00+05:30"
    assert inserted["start"]["timeZone"] == SYSTEM_TIMEZONE


# ----------------------------------------------------------------------
# C. Over-match regression: arbitrary numeric messages never reroute
# ----------------------------------------------------------------------
def test_non_correction_numeric_messages_never_reroute(db_session):
    """Messages that merely contain a number must never be rerouted to a
    calendar write, even when a recent event exists in this process."""
    _record_recent_calendar_event(
        "evt_recent", "selling DamCapital shares and buy HDFC",
        {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
    )
    assert _reminder_correction_when("complete task 1") is None
    assert _reminder_correction_when("Add a task called Test Demo assignment to Demo 1") is None
    assert (
        _reminder_correction_when(
            "The BE SEM 1 syllabus exam dates are 10 and 12 December."
        )
        is None
    )
    assert _reminder_correction_plan(db_session, "complete task 1") is None
    assert _reminder_correction_plan(db_session, "Add a task called Test Demo assignment to Demo 1") is None
    assert _reminder_correction_plan(
        db_session, "The BE SEM 1 syllabus exam dates are 10 and 12 December."
    ) is None


# ----------------------------------------------------------------------
# E. Deictic "that/this" corrections (the dogfooding bug: "Actually make
#    that 30th August" was never recognized as a correction, so the free-form
#    chat merely CLAIMED an update without touching Google Calendar)
# ----------------------------------------------------------------------
def _recent_event_record(
    event_id="evt_reminder", summary="sell DamCapital shares and buy hdfc"
):
    _record_recent_calendar_event(
        event_id,
        summary,
        {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
    )


@pytest.mark.parametrize(
    "text,expected_start",
    [
        ("Actually make that 30th August", "2026-08-30T09:00:00+05:30"),
        ("Actually make that 31st August", "2026-08-31T09:00:00+05:30"),
    ],
)
def test_deictic_that_correction_targets_recent_event_by_id(
    frozen_2026_08_19, db_session, text, expected_start
):
    """'Actually make that 30th August' must be recognized as a correction and
    deterministically UPDATE the just-created event's exact event_id to
    2026-08-30T09:00:00+05:30 — never a title lookup, never a duplicate."""
    _recent_event_record()
    assert _reminder_correction_intent(text) is True
    plan = _reminder_correction_plan(db_session, text)
    assert plan is not None
    assert plan["tool"] == "update_calendar_event"
    assert plan["args"]["event_id"] == "evt_reminder"
    body = plan["args"]["event_data"]
    assert body["start"]["dateTime"] == expected_start
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE


def test_create_then_deictic_that_correction_updates_event(
    frozen_2026_08_19, db_session
):
    """Full dogfooding flow: create on 29th august, then 'Actually make that
    30th August' — exactly one create and one in-place update to 2026-08-30,
    never a duplicate, never a free-form chat that claims success without a
    backend mutation."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "sell DamCapital shares and buy hdfc",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "sell DamCapital shares and buy hdfc",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "sell DamCapital shares and buy hdfc",
                "start": {"dateTime": "2026-08-30T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-30T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    }
                ],
                db_session,
            )
            reply2 = chat_with_ai(
                [
                    {
                        "role": "user",
                        "content": (
                            "set a reminder for 29th august for selling "
                            "DamCapital shares and buy HDFC"
                        ),
                    },
                    {"role": "assistant", "content": reply1},
                    {"role": "user", "content": "Actually make that 30th August"},
                ],
                db_session,
            )

    mock_create.assert_called_once()
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-30T09:00:00+05:30"
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE
    # The reply must be backed by the authoritative Google response (30 Aug).
    assert "Updated calendar event" in reply2
    assert "2026-08-30" in reply2


def test_deictic_repeated_corrections_are_idempotent(
    frozen_2026_08_19, db_session
):
    """Two consecutive deictic corrections still never create a second event:
    each turn is an in-place update of the same event_id."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "sell DamCapital shares and buy hdfc",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "sell DamCapital shares and buy hdfc",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            def _update_response(start):
                return {
                    "id": "evt_reminder",
                    "summary": "sell DamCapital shares and buy hdfc",
                    "start": {"dateTime": start, "timeZone": SYSTEM_TIMEZONE},
                    "end": {"dateTime": start.replace("09:00", "10:00"), "timeZone": SYSTEM_TIMEZONE},
                    "status": "confirmed",
                }

            mock_update.side_effect = [
                _update_response("2026-08-30T09:00:00+05:30"),
                _update_response("2026-08-31T09:00:00+05:30"),
            ]

            reply1 = chat_with_ai(
                [{"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"}],
                db_session,
            )
            base = [
                {"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"},
                {"role": "assistant", "content": reply1},
            ]
            reply2 = chat_with_ai(
                base + [{"role": "user", "content": "Actually make that 30th August"}],
                db_session,
            )
            reply3 = chat_with_ai(
                base
                + [{"role": "user", "content": "Actually make that 30th August"},
                   {"role": "assistant", "content": reply2},
                   {"role": "user", "content": "Actually make that 31st August"}],
                db_session,
            )

    mock_create.assert_called_once()
    assert mock_update.call_count == 2
    for call in mock_update.call_args_list:
        assert call.args[0] == "evt_reminder"
    assert mock_update.call_args_list[0].args[1]["start"]["dateTime"] == "2026-08-30T09:00:00+05:30"
    assert mock_update.call_args_list[1].args[1]["start"]["dateTime"] == "2026-08-31T09:00:00+05:30"
    assert "Updated calendar event" in reply2
    assert "Updated calendar event" in reply3


# ----------------------------------------------------------------------
# F. "It still shows the 29th" is a complaint, not a command to change to 29th
# ----------------------------------------------------------------------
def test_calendar_still_shows_complaint_is_not_a_correction(
    frozen_2026_08_19, db_session
):
    """'but the calendar still shows it on 29th' is a question/complaint about
    the current state — it must NOT be rerouted into a no-op 'update' to the
    29th that pretends to be a change (which is what produced the fake
    'Updated calendar event k6p9m3f0...' in the dogfooding session)."""
    _recent_event_record()
    assert _reminder_correction_intent("but the calendar still shows it on 29th") is False
    assert (
        _reminder_correction_plan(db_session, "but the calendar still shows it on 29th")
        is None
    )

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response('"NONE"')
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            reply = chat_with_ai(
                [{"role": "user", "content": "but the calendar still shows it on 29th"}],
                db_session,
            )

    mock_update.assert_not_called()
    assert "Updated calendar event" not in reply


# ----------------------------------------------------------------------
# G. Time-only corrections ("Actually make it 11 AM")
# ----------------------------------------------------------------------
def test_time_only_correction_keeps_the_reminders_date(
    frozen_2026_08_19, db_session
):
    """'Actually make it 11 AM' must move the reminder's clock time to 11:00 on
    ITS OWN date (29 August) — never reinterpret '11' as day-of-month 11 (which
    previously produced a bogus 2027-08-11 event)."""
    _recent_event_record()
    assert _reminder_correction_intent("Actually make it 11 AM") is True
    assert _reminder_correction_time("Actually make it 11 AM") == "11:00:00"
    plan = _reminder_correction_plan(db_session, "Actually make it 11 AM")
    assert plan is not None
    assert plan["args"]["event_id"] == "evt_reminder"
    start = plan["args"]["event_data"]["start"]
    assert start["dateTime"] == "2026-08-29T11:00:00+05:30"
    assert start["timeZone"] == SYSTEM_TIMEZONE


def test_time_only_correction_full_flow(frozen_2026_08_19, db_session):
    """Full flow: create on 29th, then 'Actually make it 11 AM' → one update
    with start 2026-08-29T11:00:00+05:30, and the reply shows the authoritative
    start from Google's response."""
    create_payload = {
        "tool": "create_calendar_event",
        "args": {
            "summary": "sell DamCapital shares and buy hdfc",
            "description": None,
            "when": "29th august",
            "start_time": None,
            "duration_minutes": 60,
            "timezone": SYSTEM_TIMEZONE,
        },
    }

    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_groq_response(
            json.dumps(create_payload)
        )
        mock_groq.return_value = mock_client

        with patch("app.services.ai_service.is_connected", return_value=False), \
             patch("app.services.tools.gc_create_calendar_event") as mock_create, \
             patch("app.services.tools.gc_update_calendar_event") as mock_update:
            mock_create.return_value = {
                "id": "evt_reminder",
                "summary": "sell DamCapital shares and buy hdfc",
                "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }
            mock_update.return_value = {
                "id": "evt_reminder",
                "summary": "sell DamCapital shares and buy hdfc",
                "start": {"dateTime": "2026-08-29T11:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "end": {"dateTime": "2026-08-29T12:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
                "status": "confirmed",
            }

            reply1 = chat_with_ai(
                [{"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"}],
                db_session,
            )
            reply2 = chat_with_ai(
                [
                    {"role": "user", "content": "set a reminder for 29th august for selling DamCapital shares and buy HDFC"},
                    {"role": "assistant", "content": reply1},
                    {"role": "user", "content": "Actually make it 11 AM"},
                ],
                db_session,
            )

    mock_create.assert_called_once()
    mock_update.assert_called_once()
    event_id, body = mock_update.call_args.args
    assert event_id == "evt_reminder"
    assert body["start"]["dateTime"] == "2026-08-29T11:00:00+05:30"
    assert body["start"]["timeZone"] == SYSTEM_TIMEZONE
    assert "2026-08-29T11:00:00" in reply2
    assert "Updated calendar event" in reply2


# ----------------------------------------------------------------------
# H. Honest success: no "Updated" claim unless Google confirms the change
# ----------------------------------------------------------------------
def test_update_claim_only_when_response_matches_request(
    frozen_2026_08_19, db_session
):
    """If Google's authoritative response shows a start different from what was
    requested, the app must NOT claim success — it reports that the update did
    not apply and logs the mismatch."""
    _recent_event_record()
    with patch("app.services.ai_service.is_connected", return_value=False), \
         patch("app.services.ai_service.logger") as mock_logger, \
         patch("app.services.tools.gc_update_calendar_event") as mock_update:
        mock_update.return_value = {
            "id": "evt_reminder",
            "summary": "sell DamCapital shares and buy hdfc",
            "start": {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "end": {"dateTime": "2026-08-29T10:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
            "status": "confirmed",
        }
        reply = chat_with_ai(
            [{"role": "user", "content": "Actually make that 30th August"}],
            db_session,
        )

    mock_update.assert_called_once()
    assert "Updated calendar event" not in reply
    assert "couldn't update" in reply.lower()
    assert mock_logger.warning.called


def test_correction_targets_most_recent_event_by_id_not_title(
    frozen_2026_08_19, db_session
):
    """Two same-titled recent events: the correction targets the exact event_id
    of the most recent one (index 0), never a title lookup against the older
    event."""
    _record_recent_calendar_event(
        "older_event", "sell DamCapital shares and buy hdfc",
        {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
    )
    _record_recent_calendar_event(
        "newest_event", "sell DamCapital shares and buy hdfc",
        {"dateTime": "2026-08-29T09:00:00+05:30", "timeZone": SYSTEM_TIMEZONE},
    )
    plan = _reminder_correction_plan(db_session, "Actually make that 30th August")
    assert plan is not None
    assert plan["args"]["event_id"] == "newest_event"