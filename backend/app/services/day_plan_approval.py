"""Approved DayPlan → Google Calendar (Step 6).

The lifecycle is deliberately three separate states:

    RECOMMENDED   plan_my_day produces a DayPlan; nothing is written.
    APPROVED      the user explicitly confirms; apply_day_plan runs.
    SCHEDULED     only after the backend confirms each calendar write.

This module owns the explicit scheduling action:

1. Backend authorization gate (``is_scheduling_authorization``). Confirmation
   must come from the user's real conversational intent; it is independently
   enforced here, never left to the LLM prompt alone.
2. Freshness. The plan is always regenerated from authoritative database +
   calendar state and compared (by deterministic signature) against the plan
   that was last presented. A stale approval is never scheduled silently —
   the fresh plan is returned for re-confirmation instead.
3. Per-block validation against the fresh plan and the current calendar
   snapshot (task exists / not done / duration matches / still inside its
   free window).
4. Idempotency: a task already linked to an event at the same slot is treated
   as already scheduled; a conflicting link is surfaced, never overwritten.
5. Compensation on partial failure: if any write fails, events created by THIS
   operation are deleted best-effort and the task fields are restored. Events
   that predate the operation are never touched.
6. Task ↔ calendar fields (``google_calendar_event_id``, ``scheduled_start``,
   ``scheduled_end``) are persisted only after a successful write. Tasks are
   never marked done just because they were scheduled.

The write path reuses ``google_calendar`` (including ``_require_write_access``)
and the existing task-calendar event body conventions — no second abstraction.
"""

import hashlib
import re
from typing import Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from app.core.timeutil import SYSTEM_TIMEZONE, normalize_to_system
from app.models.task import Task, TaskStatus
from app.schemas.day_plan import (
    DayPlan,
    ScheduledBlock,
    ScheduledBlockOutcome,
    DayPlanApprovalResult,
)
from app.services import google_calendar


# ----------------------------------------------------------------------
# Backend authorization gate
# ----------------------------------------------------------------------
# The planner decides WHEN to call apply_day_plan; this gate is the independent
# server-side backstop. It must never treat task/project/calendar text as an
# instruction — only the user's actual conversational message counts.

_EXPLICIT_SCHEDULE_PATTERNS = (
    # "schedule it / this / that / today's plan / the recommended plan ..."
    re.compile(
        r"\bschedule\s+(it|this|that|them|today'?s\s+plan|the\s+plan|"
        r"the\s+recommended\s+plan|these\s+blocks|those\s+blocks)\b"
    ),
    # "yes, schedule ..." (affirmation immediately followed by a scheduling verb)
    re.compile(
        r"\b(yes|yeah|yep|yup|sure|okay|ok|go\s+ahead|confirmed|approved)\b"
        r"[^.!?]{0,40}\bschedule\b"
    ),
    # "add / put / apply these blocks to my calendar"
    re.compile(
        r"\b(add|put|apply|book)\s+(it|them|these\s+blocks|those\s+blocks|"
        r"this\s+plan|that\s+plan|the\s+plan|the\s+recommended\s+plan|today'?s\s+plan|that)\s+"
        r"(to|on)\s+(my|the|your)\s+calendar\b"
    ),
    # "put that plan on my calendar"
    re.compile(
        r"\bput\s+(it|this|that|this\s+plan|that\s+plan|the\s+plan|the\s+recommended\s+plan|"
        r"these\s+blocks)\s+on\s+(my|the)\s+calendar\b"
    ),
    # "add / apply the recommended plan"
    re.compile(r"\b(add|apply)\s+(the\s+recommended\s+plan|this\s+plan|the\s+plan|today'?s\s+plan)\b"),
    # "apply it", "book it"
    re.compile(r"\b(apply|book)\s+it\b"),
    # "confirm scheduling / the plan"
    re.compile(r"\bconfirm\s+(scheduling|the\s+plan|this\s+plan)\b"),
)

_AFFIRMATIONS = {
    "yes", "yeah", "yep", "yup", "ok", "okay", "sure",
    "sounds good", "go ahead", "do it", "please do", "confirmed", "approved",
}


def _is_explicit_schedule(lower: str) -> bool:
    return any(pattern.search(lower) for pattern in _EXPLICIT_SCHEDULE_PATTERNS)


def _is_bare_affirmation(lower: str) -> bool:
    return lower.strip().strip("!.").strip() in _AFFIRMATIONS


def _assistant_asked_to_schedule(reply: str) -> bool:
    """True when the assistant's last reply asked for confirmation to schedule."""
    low = reply.lower()
    has_schedule_signal = ("calendar" in low) or ("schedule" in low)
    has_ask = (
        ("?" in reply)
        or any(m in low for m in ("want me to", "should i", "shall i", "can i", "confirm"))
    )
    return has_schedule_signal and has_ask


def is_scheduling_authorization(
    user_message: str,
    last_assistant_reply: Optional[str] = None,
) -> bool:
    """Backend-enforced gate: is this an explicit approval to schedule?

    A bare acknowledgement ("okay") only authorizes scheduling when the
    assistant's immediately preceding reply explicitly asked for confirmation.
    """
    text = (user_message or "").strip()
    if not text:
        return False
    lower = text.lower()
    if _is_explicit_schedule(lower):
        return True
    if last_assistant_reply and _is_bare_affirmation(lower):
        return _assistant_asked_to_schedule(last_assistant_reply)
    return False


# ----------------------------------------------------------------------
# Plan identity / freshness
# ----------------------------------------------------------------------
# Lightweight, in-process fingerprint of the plan that is currently on the
# table. This is tool context, not a persistence system: it lets the backend
# decide whether an approval still refers to the plan the user actually saw.

_last_presented_signatures: Dict[str, str] = {}


def plan_signature(day_plan: DayPlan) -> str:
    """Deterministic fingerprint of a DayPlan's scheduled content.

    Only the date and the actual blocks (task, start, end, duration) matter —
    unscheduled reasons, summaries and presentation text do not.
    """
    blocks = sorted(
        (
            b.task_id,
            b.start.isoformat(),
            b.end.isoformat(),
            b.duration_minutes,
        )
        for b in day_plan.scheduled_blocks
    )
    digest = hashlib.sha256()
    digest.update(day_plan.date.encode("utf-8"))
    for part in blocks:
        digest.update(repr(part).encode("utf-8"))
    return digest.hexdigest()


def remember_presented_plan(day_plan: DayPlan) -> str:
    """Record the plan the user was just shown; returns its signature."""
    signature = plan_signature(day_plan)
    _last_presented_signatures[day_plan.date] = signature
    return signature


def presented_signature(plan_date: str) -> Optional[str]:
    """The signature of the plan last presented for ``plan_date`` (if any)."""
    return _last_presented_signatures.get(plan_date)


def clear_presented_plan(plan_date: str) -> None:
    _last_presented_signatures.pop(plan_date, None)


# ----------------------------------------------------------------------
# Applying the approved plan
# ----------------------------------------------------------------------

def _same_slot(task, block: ScheduledBlock) -> bool:
    """True when the task's linked event already covers the exact same slot."""
    start = normalize_to_system(getattr(task, "scheduled_start", None))
    end = normalize_to_system(getattr(task, "scheduled_end", None))
    return start == block.start and end == block.end


def _block_in_free_windows(block: ScheduledBlock, overview) -> bool:
    """True when the block still fits inside the current calendar's free space."""
    return any(
        window.start <= block.start and block.end <= window.end
        for window in overview.calendar.free_windows
    )


def _event_description(block: ScheduledBlock) -> str:
    parts = [f'Work block for "{block.title}" from your ECC day plan.']
    if block.project:
        parts.append(f"Project: {block.project}.")
    return " ".join(parts)


def _event_body(block: ScheduledBlock, timezone: str) -> Dict:
    """Google event body for a scheduled work block.

    Summary stays the task title (existing task-calendar convention) while the
    description makes it clear this is a planned work block, not a meeting.
    """
    return {
        "summary": block.title,
        "description": _event_description(block),
        "start": {"dateTime": block.start.isoformat(), "timeZone": timezone},
        "end": {"dateTime": block.end.isoformat(), "timeZone": timezone},
    }


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return (text or "Unknown Google Calendar error")[:500]


def _compensate(db: Session, created_events: List) -> Dict:
    """Best-effort rollback of events created by the current operation.

    Only events created here are deleted; pre-existing calendar events are
    never touched. When a deletion fails the task keeps its link and the
    failure is recorded so it can be recovered.
    """
    cleaned: List[int] = []
    failures: List[Dict] = []
    for event_id, task in created_events:
        try:
            google_calendar.delete_calendar_event(event_id)
        except Exception as exc:
            task.calendar_sync_error = f"compensation cleanup failed: {_safe_error(exc)}"
            db.commit()
            failures.append({"task_id": task.id, "error": task.calendar_sync_error})
            continue
        task.google_calendar_event_id = None
        task.scheduled_start = None
        task.scheduled_end = None
        task.calendar_sync_error = None
        db.commit()
        cleaned.append(task.id)
    return {"cleaned_task_ids": cleaned, "cleanup_failures": failures}


def _outcome(block: ScheduledBlock, status: str, reason: str = None, event_id: str = None):
    return ScheduledBlockOutcome(
        task_id=block.task_id,
        title=block.title,
        start=block.start,
        end=block.end,
        status=status,
        reason=reason,
        event_id=event_id,
    )


def apply_approved_plan(db: Session, plan_date: str) -> DayPlanApprovalResult:
    """Regenerate, validate and (on approval match) schedule the day plan.

    Never trusts the LLM's reconstructed times or any client-supplied plan:
    the plan is always rebuilt from the database and the current calendar.
    """
    # Existing write guard: no connection / no write scope → no writes, honest error.
    google_calendar._require_write_access()

    # 1. Fresh, authoritative plan (database + current calendar snapshot).
    from app.services.planning_service import get_today_overview as build_today_overview
    from app.services.day_planner import build_day_plan

    overview = build_today_overview(db)
    fresh_plan = build_day_plan(overview)

    # 2. Freshness: the approval must match the plan currently on the table.
    remembered = presented_signature(plan_date)
    if remembered is None or plan_signature(fresh_plan) != remembered:
        remember_presented_plan(fresh_plan)
        return DayPlanApprovalResult(
            plan_date=plan_date,
            status="plan_changed",
            plan_changed=True,
            fresh_plan=fresh_plan,
            message=(
                "Your schedule has changed since I generated that plan. I "
                "refreshed it — here's the updated plan. Schedule this one?"
            ),
        )

    # 3. Validate every block and create events.
    outcomes: List[ScheduledBlockOutcome] = []
    created_events: List = []

    for block in fresh_plan.scheduled_blocks:
        task = (
            db.query(Task)
            .options(joinedload(Task.project))
            .filter(Task.id == block.task_id)
            .first()
        )
        if task is None:
            outcomes.append(_outcome(block, "skipped", "task no longer exists"))
            continue
        if task.status == TaskStatus.DONE:
            outcomes.append(_outcome(block, "skipped", "task is already completed"))
            continue
        if (task.estimated_minutes or 0) != block.duration_minutes:
            outcomes.append(_outcome(block, "skipped", "task duration changed since planning"))
            continue
        if not _block_in_free_windows(block, overview):
            outcomes.append(_outcome(block, "skipped", "slot is no longer available"))
            continue

        # Idempotency: never create a duplicate linked event.
        if task.google_calendar_event_id:
            if _same_slot(task, block):
                outcomes.append(
                    _outcome(block, "already_scheduled", event_id=task.google_calendar_event_id)
                )
                continue
            outcomes.append(
                _outcome(
                    block,
                    "skipped",
                    "task already has a linked calendar event at a different time",
                    event_id=task.google_calendar_event_id,
                )
            )
            continue

        # Create the event through the existing write path.
        body = _event_body(block, overview.timezone)
        try:
            created = google_calendar.create_calendar_event(body)
        except Exception as exc:
            compensation = _compensate(db, created_events)
            return DayPlanApprovalResult(
                plan_date=plan_date,
                status="failed",
                message=_safe_error(exc),
                outcomes=outcomes + [_outcome(block, "failed", _safe_error(exc))],
                cleanup_failed_task_ids=[
                    f["task_id"] for f in compensation["cleanup_failures"]
                ],
            )

        task.google_calendar_event_id = created.get("id")
        task.scheduled_start = block.start
        task.scheduled_end = block.end
        task.calendar_sync_error = None
        db.commit()
        created_events.append((created.get("id"), task))
        outcomes.append(_outcome(block, "scheduled", event_id=created.get("id")))

    return DayPlanApprovalResult(
        plan_date=plan_date,
        status="scheduled",
        outcomes=outcomes,
    )
