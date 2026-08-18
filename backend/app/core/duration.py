"""Duration parsing and task-effort validation helpers (Step 5).

Human-friendly duration phrases ("1 hour", "45 min", "1.5 hours") are parsed
deterministically into integer minutes. Ambiguous values — a bare number with
no unit ("make it 2") — are rejected instead of silently becoming minutes.

``validate_estimated_minutes`` is the single authority for what a stored task
estimate may be. It is used by the AI tool layer (which returns clear error
messages) and by the REST schemas (which surface FastAPI validation errors).
"""

import re

# A single task estimate is capped at one full day of focused work (24 hours).
# Anything larger is project-sized work the user should split into smaller
# tasks; the Day Planner only ever schedules estimates that fit a free window.
MAX_ESTIMATED_MINUTES = 24 * 60

_WORD_NUMBERS = {
    "one": 1, "a": 1, "an": 1,
    "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

_UNIT_MINUTES = {
    "hour": 60, "hours": 60, "hr": 60, "hrs": 60, "h": 60,
    "minute": 1, "minutes": 1, "min": 1, "mins": 1, "m": 1,
}

_DURATION_RE = re.compile(r"^(?P<amount>\d+(?:\.\d+)?|[a-z]+)\s*(?P<unit>[a-z]+)$")


def parse_duration_to_minutes(phrase) -> int | None:
    """Return integer minutes for a human-friendly duration phrase.

    Supports "30 minutes", "45 min", "1 hour", "2 hours", "1.5 hours",
    "90 minutes", "one hour", "an hour", etc. Returns None when the phrase is
    ambiguous (a bare number with no unit), unparseable, or empty — callers
    must ask for clarification rather than guessing a unit.
    """
    if not phrase or not isinstance(phrase, str):
        return None
    text = " ".join(phrase.strip().lower().split())
    if not text:
        return None
    match = _DURATION_RE.match(text)
    if not match:
        return None
    amount_raw, unit = match.group("amount"), match.group("unit")
    multiplier = _UNIT_MINUTES.get(unit)
    if multiplier is None:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", amount_raw):
        amount = float(amount_raw)
    else:
        amount = float(_WORD_NUMBERS[amount_raw]) if amount_raw in _WORD_NUMBERS else None
        if amount is None:
            return None
    minutes = amount * multiplier
    if minutes <= 0:
        return None
    return int(round(minutes))


def validate_estimated_minutes(value) -> int:
    """Validate an explicit task estimate (already an integer number of minutes).

    Raises ValueError with a clear message on negative/zero/absurd values or
    non-integer input. Invalid values are never silently clamped.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("estimated_minutes must be a whole number of minutes")
    if value <= 0:
        raise ValueError("estimated_minutes must be a positive number of minutes")
    if value > MAX_ESTIMATED_MINUTES:
        raise ValueError(
            f"estimated_minutes is too large — the maximum is "
            f"{MAX_ESTIMATED_MINUTES} minutes (24 hours). "
            "Split larger work into smaller tasks."
        )
    return value