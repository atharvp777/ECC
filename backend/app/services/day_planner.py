"""Deterministic Day Planning Engine (Step 4).

Turns a TodayOverview (from planning_service) into a recommended schedule:

    TodayOverview -> build_day_plan -> DayPlan

This module is pure computation: it performs no database or calendar queries
and knows nothing about any AI model. Given a complete TodayOverview it is a
pure function of its input, so identical inputs always produce identical
plans.

Scheduling algorithm (deliberately simple, greedy, deterministic):

1. Only unfinished tasks with a usable estimate are eligible
   (estimated_minutes > 0). Missing/zero/negative estimates go to the
   unscheduled list with reason "needs_time_estimate".
2. Eligible tasks are ordered by the Step 2 focus-tier precedence (overdue >
   critical/high/other due today > critical/high/other upcoming > high-value
   later), then priority within the urgency class, then earlier deadline,
   then higher estimated effort, then stable task id.
3. For each free window (chronological, from the planning service), fill the
   remaining space with the highest-priority eligible task that fits
   completely inside the current window's remaining time, restarting the scan
   from the top after every placement. This avoids wasting a window just
   because the top task is too big, without splitting tasks or sacrificing
   priority excessively.
4. A task is never split across windows. Whatever remains of each window is
   reported as an unused window. Every unscheduled eligible task is reported
   with a deterministic reason.

Breaks, lunch, Pomodoro and work-hour preferences are NOT introduced — the
plan only uses the free windows the planning service actually computed, so
calendar events (including all-day and overlapping ones, which are already
merged into free windows upstream) are always respected.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.timeutil import SYSTEM_TIMEZONE
from app.models.task import TaskPriority
from app.schemas.planning import TodayOverview
from app.schemas.day_plan import (
    DayPlan,
    DayPlanSummary,
    ScheduledBlock,
    UnscheduledTask,
    UnusedWindow,
)

_IST = ZoneInfo(SYSTEM_TIMEZONE)
_MAX_DEADLINE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=_IST)

# Urgency tiers mirror the Step 2 focus-candidate precedence:
#   0 overdue+critical, 1 overdue+high, 2 other overdue,
#   3 critical due today, 4 high due today, 5 other due today,
#   6 critical upcoming, 7 high upcoming, 8 medium upcoming, 9 low upcoming,
#   10 critical (no near deadline), 11 high (no near deadline).
_PRIORITY_RANK = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}

# Human-readable scheduling reasons (structured, model-agnostic).
_REASON_NEEDS_ESTIMATE = "needs_time_estimate"
_REASON_NO_WINDOW = "no_available_calendar_window"
_REASON_INSUFFICIENT_TIME = "insufficient_remaining_time"


def build_day_plan(overview: TodayOverview) -> DayPlan:
    """Compute the deterministic recommended DayPlan for a TodayOverview."""
    partitions = (
        (overview.tasks.overdue, _overdue_tier),
        (overview.tasks.due_today, _due_today_tier),
        (overview.tasks.upcoming, _upcoming_tier),
        (overview.tasks.critical, _critical_tier),
    )

    tiered = []
    for tasks, tier_fn in partitions:
        for t in tasks:
            tiered.append((tier_fn(t.priority), t))

    eligible = [
        (tier, t) for tier, t in tiered
        if t.estimated_minutes is not None and t.estimated_minutes > 0
    ]
    needs_estimate = [
        (tier, t) for tier, t in tiered
        if t.estimated_minutes is None or t.estimated_minutes <= 0
    ]

    # Deterministic ordering: urgency tier, priority within the class, earlier
    # deadline, higher estimated effort, then stable id.
    eligible.sort(key=_order_key)
    needs_estimate.sort(key=_order_key)

    windows = [w for w in overview.calendar.free_windows if w.duration_minutes > 0]
    blocks = []
    scheduled_ids = set()
    unused_windows = []

    for window in windows:
        cursor = window.start
        remaining = window.duration_minutes
        while remaining > 0:
            placed = False
            for tier, task in eligible:
                if task.task_id in scheduled_ids:
                    continue
                duration = task.estimated_minutes
                if duration > remaining:
                    continue
                end = cursor + timedelta(minutes=duration)
                blocks.append(
                    ScheduledBlock(
                        task_id=task.task_id,
                        title=task.title,
                        project=task.project_name,
                        start=cursor,
                        end=end,
                        duration_minutes=duration,
                        reasons=_task_reasons(tier, task.priority),
                    )
                )
                scheduled_ids.add(task.task_id)
                cursor = end
                remaining -= duration
                placed = True
                break
            if not placed:
                break
        if remaining > 0:
            unused_windows.append(
                UnusedWindow(
                    start=cursor,
                    end=window.end,
                    duration_minutes=remaining,
                )
            )

    unscheduled = [
        UnscheduledTask(
            task_id=t.task_id,
            title=t.title,
            estimated_minutes=t.estimated_minutes,
            priority=t.priority,
            deadline=t.deadline,
            reason=_unscheduled_reason(windows, t),
        )
        for tier, t in eligible
        if t.task_id not in scheduled_ids
    ]
    unscheduled.extend(
        UnscheduledTask(
            task_id=t.task_id,
            title=t.title,
            estimated_minutes=t.estimated_minutes,
            priority=t.priority,
            deadline=t.deadline,
            reason=_REASON_NEEDS_ESTIMATE,
        )
        for tier, t in needs_estimate
    )
    # Report unscheduled work in the same deterministic priority order.
    unscheduled.sort(key=_unscheduled_order_key)

    scheduled_minutes = sum(b.duration_minutes for b in blocks)
    available_minutes = sum(w.duration_minutes for w in overview.calendar.free_windows)
    unused_minutes = sum(u.duration_minutes for u in unused_windows)

    return DayPlan(
        date=overview.generated_at.date().isoformat(),
        timezone=overview.timezone,
        generated_at=overview.generated_at,
        scheduled_blocks=blocks,
        unscheduled_tasks=unscheduled,
        unused_windows=unused_windows,
        summary=DayPlanSummary(
            total_tasks=len(eligible) + len(needs_estimate),
            scheduled_tasks=len(blocks),
            unscheduled_tasks=len(unscheduled),
            total_scheduled_minutes=scheduled_minutes,
            total_available_minutes=available_minutes,
            unused_minutes=unused_minutes,
            calendar_connected=overview.calendar.connected,
        ),
    )


def _overdue_tier(priority: TaskPriority) -> int:
    if priority == TaskPriority.CRITICAL:
        return 0
    if priority == TaskPriority.HIGH:
        return 1
    return 2


def _due_today_tier(priority: TaskPriority) -> int:
    if priority == TaskPriority.CRITICAL:
        return 3
    if priority == TaskPriority.HIGH:
        return 4
    return 5


def _upcoming_tier(priority: TaskPriority) -> int:
    if priority == TaskPriority.CRITICAL:
        return 6
    if priority == TaskPriority.HIGH:
        return 7
    if priority == TaskPriority.MEDIUM:
        return 8
    return 9


def _critical_tier(priority: TaskPriority) -> int:
    if priority == TaskPriority.CRITICAL:
        return 10
    return 11


def _order_key(item):
    tier, task = item
    return (
        tier,
        _PRIORITY_RANK[task.priority],
        task.deadline or _MAX_DEADLINE,
        -(task.estimated_minutes or 0),
        task.task_id,
    )


def _unscheduled_order_key(task: UnscheduledTask) -> tuple:
    # Needs-estimate tasks never carry a partition, so their tier cannot be
    # reconstructed exactly; fall back to priority-first ordering so the list
    # stays stable and deterministic.
    return (
        _PRIORITY_RANK[task.priority],
        task.deadline or _MAX_DEADLINE,
        -(task.estimated_minutes or 0),
        task.task_id,
    )


def _base_reason(tier: int) -> str:
    if tier <= 2:
        return "overdue"
    if tier <= 5:
        return "due_today"
    if tier <= 9:
        return "upcoming"
    return "high_value"


def _task_reasons(tier: int, priority: TaskPriority) -> list[str]:
    reasons = [_base_reason(tier)]
    if priority == TaskPriority.CRITICAL:
        reasons.append("critical")
    elif priority == TaskPriority.HIGH:
        reasons.append("high")
    return reasons


def _unscheduled_reason(windows: list, task) -> str:
    """Deterministic reason a usable-estimate task could not be scheduled.

    The greedy scheduler fills each window maximally (restarting from the top
    after every placement), so any eligible task left unscheduled never fit the
    remaining space of any window. With zero usable windows there is simply no
    availability to schedule into.
    """
    if not windows:
        return _REASON_NO_WINDOW
    return _REASON_INSUFFICIENT_TIME