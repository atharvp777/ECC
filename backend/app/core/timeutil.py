"""System timezone helpers.

The system operates in a single timezone (Asia/Kolkata). Every stored
datetime is normalized to it so SQLite string comparisons (which are
lexicographic) remain chronologically correct across AI-created and
manually-created tasks.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

SYSTEM_TIMEZONE = "Asia/Kolkata"


def normalize_to_system(dt: datetime | None) -> datetime | None:
    """Return `dt` normalized to the system timezone, or None.

    Naive datetimes are assumed to already be in the system timezone (this is
    the documented API contract for date-only values like project deadlines);
    aware datetimes are converted to the system zone.
    """
    if dt is None:
        return None
    tz = ZoneInfo(SYSTEM_TIMEZONE)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)