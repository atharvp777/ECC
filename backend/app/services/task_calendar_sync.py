"""Central task ↔ Google Calendar sync logic.

All Google Calendar calls go through the existing ``google_calendar`` service;
this module owns the orchestration between a Task row and its linked event:

- create_or_update_event   – idempotent create (when unlinked) / update (when linked)
- unlink_event             – best-effort removal of the linked event
- delete_event_best_effort – cleanup used by task deletion

Invariant: a task row is NEVER rolled back or deleted because a Google
Calendar write failed. Failures are recorded in ``calendar_sync_error`` so the
task stays safe in the ECC database and can be retried later.
"""

from datetime import datetime
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.services import google_calendar


TASK_NOT_LINKED_MESSAGE = (
    "That task isn't currently linked to a Google Calendar event."
)


def _parse_datetime_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    if not text:
        return "Unknown Google Calendar error"
    return text[:500]


def create_or_update_event(db: Session, task, event_data: Dict) -> Dict:
    """Create or update the Google event linked to ``task``.

    Idempotent: when ``task.google_calendar_event_id`` already exists the
    existing event is updated — never a second insert. On success the task's
    event id, schedule and (cleared) sync error are persisted. On failure the
    previous event id (if any) is preserved and the failure is stored in
    ``calendar_sync_error``. Never raises; never deletes the task.
    """
    start_dt = _parse_datetime_iso((event_data.get("start") or {}).get("dateTime"))
    end_dt = _parse_datetime_iso((event_data.get("end") or {}).get("dateTime"))

    try:
        if task.google_calendar_event_id:
            updated = google_calendar.update_calendar_event(
                task.google_calendar_event_id, event_data
            )
            task.google_calendar_event_id = updated.get("id") or task.google_calendar_event_id
        else:
            created = google_calendar.create_calendar_event(event_data)
            task.google_calendar_event_id = created.get("id")
        task.scheduled_start = start_dt
        task.scheduled_end = end_dt
        task.calendar_sync_error = None
        db.commit()
        db.refresh(task)
        return {"event_id": task.google_calendar_event_id, "error": None}
    except Exception as exc:
        task.calendar_sync_error = _safe_error(exc)
        db.commit()
        db.refresh(task)
        return {"event_id": task.google_calendar_event_id, "error": task.calendar_sync_error}


def unlink_event(db: Session, task) -> Dict:
    """Best-effort removal of the linked Google event.

    The task is always kept. When there is nothing linked (or Google deletion
    succeeds) the event id / schedule fields are cleared. When Google deletion
    fails, the link is preserved (so it can be retried) and the failure is
    recorded in ``calendar_sync_error``.
    """
    if not task.google_calendar_event_id:
        task.scheduled_start = None
        task.scheduled_end = None
        task.calendar_sync_error = None
        db.commit()
        db.refresh(task)
        return {"event_id": None, "error": None}
    try:
        google_calendar.delete_calendar_event(task.google_calendar_event_id)
        task.google_calendar_event_id = None
        task.scheduled_start = None
        task.scheduled_end = None
        task.calendar_sync_error = None
        db.commit()
        db.refresh(task)
        return {"event_id": None, "error": None}
    except Exception as exc:
        task.calendar_sync_error = _safe_error(exc)
        db.commit()
        db.refresh(task)
        return {"event_id": task.google_calendar_event_id, "error": task.calendar_sync_error}


def delete_event_best_effort(task) -> None:
    """Delete the linked Google event before a task row is deleted.

    Never raises — the task must remain deletable even when Google Calendar
    is unavailable.
    """
    if not task.google_calendar_event_id:
        return
    try:
        google_calendar.delete_calendar_event(task.google_calendar_event_id)
    except Exception:
        pass