"""Routing / stateful-action audit regression tests.

Each test in this file reproduces a candidate correctness or idempotency
failure in the tool-routing and stateful action flows (calendar events,
reminders/tasks, natural-language date/time handling). Tests were written to
fail on the current behavior where a confirmed bug exists, then fixed together
with the production code.
"""
import json
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Task
from app.models.task import TaskStatus
from app.services import google_calendar
from app.services.tool_dispatcher import execute_tool
from app.services.tools import (
    _resolve_event_date,
    update_task as update_task_tool,
    UpdateTaskRequest,
    add_task_to_calendar as add_task_to_calendar_tool,
    AddTaskToCalendarRequest,
    _MONTHS,
    _resolve_month_day,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _task(db, title="Wiring Diagram"):
    task = Task(title=title)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ----------------------------------------------------------------------
# A. update_task must never erase an existing deadline via planner nulls
# ----------------------------------------------------------------------
def test_update_task_null_deadline_when_preserves_deadline(db_session):
    """The planner routinely emits deadline_when:null when a task update does
    not touch the deadline. That spurious null must not erase the existing
    deadline (mirroring the null-guard applied to title/status/priority)."""
    task = _task(db_session)
    task.deadline = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    db_session.commit()

    result = update_task_tool(
        db_session,
        UpdateTaskRequest(
            task_id=task.id,
            priority="high",
            deadline_when=None,
        ),
    )

    assert not isinstance(result.get("data"), dict) or "error" not in result["data"]
    db_session.refresh(task)
    assert task.priority.value == "high"
    # The deadline must survive a spurious null.
    assert task.deadline is not None
    assert task.deadline.year == 2026 and task.deadline.month == 9


def test_update_task_null_deadline_iso_keeps_explicit_clear(db_session):
    """A direct, intentional deadline:null (ISO field) remains an explicit
    clear — the natural-language deadline_when null is the spurious one."""
    task = _task(db_session)
    task.deadline = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    db_session.commit()

    update_task_tool(
        db_session,
        UpdateTaskRequest(task_id=task.id, deadline=None),
    )

    db_session.refresh(task)
    assert task.deadline is None


# ----------------------------------------------------------------------
# B. Date/time parsing: explicit years and times inside `when`
# ----------------------------------------------------------------------
def test_month_day_phrase_with_explicit_year_keeps_year():
    """'29 august 2027' names a specific year — the resolver must not drop it
    and silently use the current year (or roll a past date to next year)."""
    frozen = datetime(2026, 8, 19, 10, 0)  # naive anchor date is enough here
    assert _resolve_event_date("29 august 2027", frozen) == date(2027, 8, 29)
    assert _resolve_event_date("29th august 2027", frozen) == date(2027, 8, 29)


def test_month_day_phrase_with_past_explicit_year_stays_in_that_year():
    frozen = datetime(2026, 8, 19, 10, 0)
    # 29 august 2025 is explicitly in the past → keep 2025, never roll to 2027.
    assert _resolve_event_date("29 august 2025", frozen) == date(2025, 8, 29)


def test_month_day_phrase_with_year_and_month_first():
    frozen = datetime(2026, 8, 19, 10, 0)
    assert _resolve_event_date("august 29 2027", frozen) == date(2027, 8, 29)


def test_month_day_phrase_time_in_when_is_preserved():
    """A time embedded in the when phrase ('29th august at 15:00') must be used
    for the event time, not the 09:00 default."""
    from app.services.tools import _resolve_event_datetime

    frozen = datetime(2026, 8, 19, 10, 0)
    start = _resolve_event_datetime(
        {"when": "29th august at 15:00", "start_time": ""}, frozen
    )
    assert start.date() == date(2026, 8, 29)
    assert start.hour == 15 and start.minute == 0


def test_resolve_month_day_ignores_non_month_numbers():
    """The year '2026' inside a phrase must never be consumed as a day."""
    assert _resolve_month_day("in august 2026", date(2026, 8, 19)) is None


# ----------------------------------------------------------------------
# C. Idempotency: re-applying calendar writes never duplicates
# ----------------------------------------------------------------------
def test_add_task_to_calendar_rerun_without_schedule_never_duplicates(db_session):
    """Calling add_task_to_calendar again without a date returns a clarification
    and performs NO Google write (no duplicate, no defaulted past slot)."""
    task = _task(db_session)

    with patch.object(
        google_calendar, "create_calendar_event"
    ) as mock_create, patch.object(
        google_calendar, "update_calendar_event"
    ) as mock_update:
        mock_create.return_value = {
            "id": "evt_x",
            "summary": "Wiring Diagram",
            "start": {"dateTime": "2026-08-20T09:00:00+05:30"},
            "end": {"dateTime": "2026-08-20T10:00:00+05:30"},
        }
        first = add_task_to_calendar_tool(
            db_session, AddTaskToCalendarRequest(task_id=task.id, when="tomorrow")
        )
        second = add_task_to_calendar_tool(
            db_session, AddTaskToCalendarRequest(task_id=task.id)
        )

    assert first["data"].google_calendar_event_id == "evt_x"
    # The no-date call asks for a time and never touches Google.
    assert second["data"].get("reply_direct") is True
    assert mock_create.call_count == 1
    mock_update.assert_not_called()


def test_update_task_schedule_change_syncs_without_schedule_on_calendar(db_session):
    """An update that changes a linked task's schedule must sync to Google even
    when the planner omitted schedule_on_calendar (it is not the trigger)."""
    task = _task(db_session)
    task.google_calendar_event_id = "evt_linked"
    task.scheduled_start = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    task.scheduled_end = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    db_session.commit()

    with patch.object(
        google_calendar, "update_calendar_event"
    ) as mock_update, patch.object(
        google_calendar, "create_calendar_event"
    ) as mock_create:
        mock_update.return_value = {
            "id": "evt_linked",
            "summary": "Wiring Diagram",
            "start": {"dateTime": "2026-08-21T09:00:00+05:30"},
            "end": {"dateTime": "2026-08-21T10:00:00+05:30"},
        }
        execute_tool(
            "update_task",
            {"task_id": task.id, "when": "21 august", "start_time": "09:00"},
            db_session,
        )

    mock_update.assert_called_once()
    mock_create.assert_not_called()
    db_session.refresh(task)
    assert task.scheduled_start.date().day == 21