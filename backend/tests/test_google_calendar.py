"""Google Calendar service tests (API fully mocked — no live calls).

Covers write-scope enforcement, create/update/delete event wrappers (including
the insufficient-permission → PermissionError mapping), and the upcoming-events
listing with its timezone/all-day/defensive filtering.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Task
from app.services import google_calendar
from app.services.google_calendar import (
    has_write_scope,
    _token_scopes,
    _require_write_access,
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
    get_upcoming_events,
)
from app.services.task_calendar_sync import (
    unlink_event,
    delete_event_best_effort,
)

EVENT_BODY = {
    "summary": "Wind test",
    "start": {"dateTime": "2026-08-20T10:00:00+05:30"},
    "end": {"dateTime": "2026-08-20T10:30:00+05:30"},
}


@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "google_token.json"
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", path)
    return path


def _write_token(token_file, scopes):
    token_file.write_text(
        json.dumps({"token": "t", "refresh_token": "r", "token_uri": "u",
                    "client_id": "c", "client_secret": "s", "scopes": scopes})
    )


# ----------------------------------------------------------------------
# Scope detection
# ----------------------------------------------------------------------

def test_no_token_means_no_write_scope(token_file):
    assert has_write_scope() is False


def test_writable_scope_detected(token_file):
    _write_token(token_file, ["https://www.googleapis.com/auth/calendar.events"])
    assert has_write_scope() is True


def test_readonly_scope_not_writable(token_file):
    _write_token(token_file, ["https://www.googleapis.com/auth/calendar.readonly"])
    assert has_write_scope() is False


def test_scopes_as_string_handled(token_file):
    _write_token(token_file, "https://www.googleapis.com/auth/calendar.events")
    assert has_write_scope() is True


def test_token_scopes_empty_list(token_file):
    _write_token(token_file, [])
    assert _token_scopes() == []


def test_token_scopes_invalid_json(token_file):
    token_file.write_text("{not json")
    assert _token_scopes() is None


# ----------------------------------------------------------------------
# Write access guard
# ----------------------------------------------------------------------

def test_require_write_access_raises_when_disconnected():
    with patch.object(google_calendar, "is_connected", return_value=False):
        with pytest.raises(PermissionError):
            _require_write_access()


def test_require_write_access_raises_without_write_scope():
    with patch.object(google_calendar, "is_connected", return_value=True), \
         patch.object(google_calendar, "has_write_scope", return_value=False):
        with pytest.raises(PermissionError):
            _require_write_access()


def test_require_write_access_passes_with_write_scope():
    with patch.object(google_calendar, "is_connected", return_value=True), \
         patch.object(google_calendar, "has_write_scope", return_value=True):
        _require_write_access()


# ----------------------------------------------------------------------
# Create / update / delete wrappers
# ----------------------------------------------------------------------

def _mock_service(insert=None, update=None, delete=None):
    events = MagicMock()
    if insert is not None:
        events.insert.return_value.execute.return_value = insert
    if update is not None:
        events.update.return_value.execute.return_value = update
    if delete is not None:
        events.delete.return_value.execute.return_value = delete
    service = MagicMock()
    service.events.return_value = events
    return service


def _mock_failing_service(op, message):
    events = MagicMock()
    getattr(events, op).return_value.execute.side_effect = RuntimeError(message)
    service = MagicMock()
    service.events.return_value = events
    return service


def test_create_calendar_event_success():
    service = _mock_service(insert={"id": "evt-1", "summary": "Wind test", "start": {}, "end": {}, "status": "confirmed"})
    with patch.object(google_calendar, "_require_write_access"), \
         patch.object(google_calendar, "_get_service", return_value=service):
        result = create_calendar_event(EVENT_BODY)
    assert result["id"] == "evt-1"
    assert result["status"] == "confirmed"


def test_create_calendar_event_insufficient_permission_maps_to_permission_error():
    service = _mock_failing_service("insert", "Insufficient Permission")
    with patch.object(google_calendar, "_require_write_access"), \
         patch.object(google_calendar, "_get_service", return_value=service):
        with pytest.raises(PermissionError):
            create_calendar_event(EVENT_BODY)


def test_update_calendar_event_success():
    service = _mock_service(update={"id": "evt-1", "summary": "Renamed", "status": "confirmed"})
    with patch.object(google_calendar, "_require_write_access"), \
         patch.object(google_calendar, "_get_service", return_value=service):
        result = update_calendar_event("evt-1", EVENT_BODY)
    assert result["id"] == "evt-1"
    assert result["summary"] == "Renamed"


def test_delete_calendar_event_success():
    service = _mock_service(delete={"deleted": True})
    with patch.object(google_calendar, "_require_write_access"), \
         patch.object(google_calendar, "_get_service", return_value=service):
        result = delete_calendar_event("evt-1")
    assert result == {"status": "deleted", "event_id": "evt-1"}


def test_delete_calendar_event_insufficient_permission_maps_to_permission_error():
    service = _mock_failing_service("delete", "insufficient")
    with patch.object(google_calendar, "_require_write_access"), \
         patch.object(google_calendar, "_get_service", return_value=service):
        with pytest.raises(PermissionError):
            delete_calendar_event("evt-1")


# ----------------------------------------------------------------------
# Upcoming events listing
# ----------------------------------------------------------------------

def _mock_credentials():
    return MagicMock(expired=False)


def _mock_list_service(items):
    events = MagicMock()
    events.list.return_value.execute.return_value = {"items": items}
    service = MagicMock()
    service.events.return_value = events
    return service


def test_get_upcoming_events_returns_empty_when_disconnected():
    with patch.object(google_calendar, "_load_credentials", return_value=None):
        assert get_upcoming_events() == []


def test_get_upcoming_events_lists_with_all_day_flag():
    items = [
        {
            "id": "a1",
            "summary": "Timed event",
            "start": {"dateTime": "2026-08-20T10:00:00+05:30"},
            "end": {"dateTime": "2026-08-20T11:00:00+05:30"},
            "htmlLink": "http://link",
        },
        {
            "id": "a2",
            "summary": "All-day event",
            "start": {"date": "2026-08-21"},
            "end": {"date": "2026-08-22"},
        },
    ]
    with patch.object(google_calendar, "_load_credentials", return_value=_mock_credentials()), \
         patch.object(google_calendar, "build", return_value=_mock_list_service(items)):
        events = get_upcoming_events(days=7)

    assert len(events) == 2
    assert events[0]["id"] == "a1"
    assert events[0]["all_day"] is False
    assert events[0]["html_link"] == "http://link"
    assert events[1]["all_day"] is True


def test_get_upcoming_events_drops_events_ended_before_today():
    # Ended yesterday → must be filtered out defensively.
    items = [
        {
            "id": "old",
            "summary": "Old event",
            "start": {"dateTime": "2026-08-01T10:00:00+05:30"},
            "end": {"dateTime": "2026-08-01T11:00:00+05:30"},
        },
        {
            "id": "future",
            "summary": "Future event",
            "start": {"dateTime": "2099-08-20T10:00:00+05:30"},
            "end": {"dateTime": "2099-08-20T11:00:00+05:30"},
        },
    ]
    with patch.object(google_calendar, "_load_credentials", return_value=_mock_credentials()), \
         patch.object(google_calendar, "build", return_value=_mock_list_service(items)):
        events = get_upcoming_events(days=7)

    ids = {e["id"] for e in events}
    assert "old" not in ids
    assert "future" in ids


# ----------------------------------------------------------------------
# task_calendar_sync — unlink / cleanup failure branches
# ----------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _task(db, **kwargs):
    t = Task(title="Wind test", priority="medium", status="todo", **kwargs)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def test_unlink_event_without_link_just_clears_fields(db_session):
    t = _task(db_session, scheduled_start=None)
    result = unlink_event(db_session, t)
    assert result["event_id"] is None and result["error"] is None
    assert t.calendar_sync_error is None


def test_unlink_event_failure_preserves_link_and_records_error(db_session):
    t = _task(db_session, google_calendar_event_id="evt-1", scheduled_start=None)
    with patch.object(google_calendar, "delete_calendar_event", side_effect=RuntimeError("down")):
        result = unlink_event(db_session, t)
    assert result["event_id"] == "evt-1"
    assert "down" in result["error"]
    db_session.refresh(t)
    assert t.google_calendar_event_id == "evt-1"
    assert t.calendar_sync_error


def test_delete_event_best_effort_never_raises_on_google_failure(db_session):
    t = _task(db_session, google_calendar_event_id="evt-1")
    with patch.object(google_calendar, "delete_calendar_event", side_effect=RuntimeError("down")):
        delete_event_best_effort(t)  # must not raise


def test_delete_event_best_effort_noop_when_unlinked(db_session):
    t = _task(db_session, google_calendar_event_id=None)
    with patch.object(google_calendar, "delete_calendar_event") as mock_del:
        delete_event_best_effort(t)
    mock_del.assert_not_called()