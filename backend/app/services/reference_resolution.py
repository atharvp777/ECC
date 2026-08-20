"""Deterministic, in-process contextual reference resolution.

When Orbit presents structured data (a calendar read, a project's saved exam
schedule) it records a bounded, in-memory reference entry keyed by the EXACT
reply text the user just saw. A follow-up that points back at that data with a
deictic phrase ("set those dates on my calendar", "schedule the above") is
resolved deterministically against that registry — never by the LLM, and never
by parsing dates out of the user's NEW message.

Safety invariants
-----------------
- Referents come only from authoritative backend data: Google Calendar event
  results and the project's saved ``project_context`` rows. Free-form LLM text
  is never registered.
- An entry resolves only when its ``reply_text`` EXACTLY equals the assistant
  message immediately preceding the current request, the project scope matches,
  and the entry is fresh (bounded TTL).
- A write is never performed from a bare reference: the first turn returns a
  proposal and stores a single-use pending proposal. Only an explicit
  confirmation whose immediately preceding assistant message asked for
  confirmation executes the write.
- No cross-project resolution; project context can never authorize a write.
- Ambiguous or missing references always produce clarification, never a guess.

This phase implements only the calendar/date reference case. The registry and
capture primitives are intentionally generic (calendar events, context dates,
tasks) so future phases (e.g. "mark those tasks complete") can reuse them
without changing the resolution model.
"""

import re
import time
from datetime import date, datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from app.core.timeutil import SYSTEM_TIMEZONE

# ----------------------------------------------------------------------
# Bounded in-process stores
# ----------------------------------------------------------------------
_MAX_REFERENCE_ENTRIES = 20
_REFERENCE_TTL_SECONDS = 900  # 15 minutes
_MAX_PENDING_PROPOSALS = 5

_REFERENCE_REGISTRY: List[dict] = []  # newest first
_PENDING_PROPOSALS: List[dict] = []  # newest first

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_TO_NAME = {num: name for name, num in _MONTHS.items()}
_MONTH_ABBREV = {name[:3]: num for name, num in _MONTHS.items()}
_MONTH_ALT = "|".join(list(_MONTHS.keys()) + list(_MONTH_ABBREV.keys()))

# ----------------------------------------------------------------------
# Deterministic date extraction from authoritative context strings
# ----------------------------------------------------------------------
# Supports DD-MM-YYYY / DD-MM (day first, Indian convention), DD/MM[-YYYY],
# ISO YYYY-MM-DD, and month-name phrases ("25 August", "August 25").
_DATE_MASTER = re.compile(
    r"\b(?P<iso>\d{4}-(?:\d{1,2})-(?:\d{1,2}))\b"
    r"|\b(?P<dmy>(?:\d{1,2})[-/](?:\d{1,2})[-/](?:\d{2,4}))\b"
    r"|\b(?P<dm>(?:\d{1,2})[-/](?:\d{1,2}))\b"
    r"|\b(?P<daymonth>(?:\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+|on\s+)?(" + _MONTH_ALT + r")[a-z]*)\b"
    r"|\b(?P<monthday>(" + _MONTH_ALT + r")[a-z]*\s+(?:\d{1,2})(?:st|nd|rd|th)?)\b",
    re.IGNORECASE,
)


def _parse_year_digits(year_str: str) -> int:
    """Interpret a 1-4 digit year token (2-digit years map to 2000+)."""
    year = int(year_str)
    if year < 100:
        year += 2000
    return year


def _month_number(name: str) -> Optional[int]:
    return _MONTHS.get(name.lower()) or _MONTH_ABBREV.get(name.lower())


def _date_from_parts(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _label_after(content: str, end: int, next_start: Optional[int]) -> str:
    """The text immediately following a date token, used as the event label."""
    tail = content[end:] if next_start is None else content[end:next_start]
    label = re.sub(r"\s+", " ", tail).strip()
    label = re.sub(r"^[\s\-—/•:.,;|]+", "", label)
    label = re.sub(r"[\s\-—/•:.,;|]+$", "", label)
    return label[:120]


def extract_date_referents(content: str, now: Optional[datetime] = None) -> List[dict]:
    """Deterministically extract ``{date, label}`` referents from a string.

    Each referent's ``date`` is a concrete ``YYYY-MM-DD`` local date resolved
    from the token; ``label`` is the text following the token (up to the next
    date token or a separator). Bare day-month tokens without a year roll to
    next year when they already passed.
    """
    if not content:
        return []
    now = now or datetime.now(ZoneInfo(SYSTEM_TIMEZONE))
    today = now.date()

    matches = list(_DATE_MASTER.finditer(content))
    referents: List[dict] = []
    seen: set = set()
    for index, match in enumerate(matches):
        resolved = None
        if match.group("iso"):
            resolved = date.fromisoformat(match.group("iso"))
        elif match.group("dmy"):
            parts = re.split(r"[-/]", match.group("dmy"))
            day, month, year = int(parts[0]), int(parts[1]), _parse_year_digits(parts[2])
            resolved = _date_from_parts(year, month, day)
        elif match.group("dm"):
            parts = re.split(r"[-/]", match.group("dm"))
            day, month = int(parts[0]), int(parts[1])
            resolved = _date_from_parts(today.year, month, day)
            if resolved is not None and resolved < today:
                resolved = _date_from_parts(today.year + 1, month, day)
        elif match.group("daymonth"):
            day = int(re.search(r"\d{1,2}", match.group("daymonth")).group())
            month = _month_number(match.group(5))
            resolved = _date_from_parts(today.year, month, day) if month else None
            if resolved is not None and resolved < today:
                resolved = _date_from_parts(today.year + 1, month, day)
        elif match.group("monthday"):
            month = _month_number(match.group(7))
            day = int(re.search(r"\d{1,2}", match.group("monthday")).group())
            resolved = _date_from_parts(today.year, month, day) if month else None
            if resolved is not None and resolved < today:
                resolved = _date_from_parts(today.year + 1, month, day)

        if resolved is None:
            continue
        iso = resolved.isoformat()
        next_start = matches[index + 1].start() if index + 1 < len(matches) else None
        label = _label_after(content, match.end(), next_start)
        if iso in seen:
            continue
        seen.add(iso)
        referents.append({"date": iso, "label": label})
    return referents


def _date_tokens(iso: str) -> set:
    """String forms of a date that may legitimately appear in an assistant reply."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return {iso}
    name = _MONTH_TO_NAME[d.month]
    short = name[:3]
    tokens = {
        iso,
        f"{d.day:02d}-{d.month:02d}-{d.year}", f"{d.day}-{d.month}-{d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}", f"{d.day}/{d.month}/{d.year}",
        f"{d.day:02d}-{d.month:02d}", f"{d.day}-{d.month}",
        f"{d.day:02d}/{d.month:02d}", f"{d.day}/{d.month}",
        f"{d.day} {name}", f"{name} {d.day}",
        f"{d.day} {short}", f"{short} {d.day}",
        f"{d.day}th {name}", f"{name} {d.day}th",
        f"{d.day}th {short}", f"{short} {d.day}th",
    }
    return tokens


def _date_in_text(iso: str, text: str) -> bool:
    lowered = (text or "").lower()
    return any(token.lower() in lowered for token in _date_tokens(iso))


def _event_local_date_iso(start: str) -> Optional[date]:
    """Local calendar day of an event start string (timed or all-day)."""
    if not start:
        return None
    tz = ZoneInfo(SYSTEM_TIMEZONE)
    if "T" in start:
        try:
            return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(tz).date()
        except (ValueError, TypeError):
            return None
    try:
        return date.fromisoformat(start)
    except (ValueError, TypeError):
        return None


def _pretty_date(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        return date.fromisoformat(iso).strftime("%B %d, %Y")
    except (TypeError, ValueError):
        return iso


def _dedupe_referents(referents: List[dict]) -> List[dict]:
    seen: set = set()
    out: List[dict] = []
    for r in referents:
        key = (r.get("type"), r.get("date"), (r.get("label") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# ----------------------------------------------------------------------
# Registration (capture before deterministic rendering discards data)
# ----------------------------------------------------------------------
def referents_from_calendar_events(
    events: List[dict], project_id: Optional[int] = None
) -> List[dict]:
    """Structured referents for a live Google Calendar read result."""
    referents: List[dict] = []
    for event in events or []:
        local_date = _event_local_date_iso(event.get("start"))
        if local_date is None:
            continue
        referents.append({
            "type": "calendar_event",
            "date": local_date.isoformat(),
            "date_text": _pretty_date(local_date.isoformat()),
            "label": event.get("title") or "(no title)",
            "start": event.get("start"),
            "end": event.get("end"),
            "id": event.get("id"),
            "source": "calendar",
            "project_id": project_id,
        })
    return _dedupe_referents(referents)


def referents_from_project_context(
    db, project_id: Optional[int], reply_text: str, now: Optional[datetime] = None
) -> List[dict]:
    """Context-date referents from the project's saved rows that the reply
    actually presented. Dates that never appear in the reply are not captured —
    the assistant must have surfaced them to make them referable."""
    if project_id is None:
        return []
    from app.services.project_context_service import list_project_context

    items = list_project_context(db, project_id, active_only=True, limit=15)
    now = now or datetime.now(ZoneInfo(SYSTEM_TIMEZONE))
    referents: List[dict] = []
    for item in items:
        for ref in extract_date_referents(item.content or "", now):
            if not _date_in_text(ref["date"], reply_text):
                continue
            referents.append({
                "type": "context_date",
                "date": ref["date"],
                "date_text": _pretty_date(ref["date"]),
                "label": (ref.get("label") or "").strip() or f"Event on {_pretty_date(ref['date'])}",
                "source": "project_context",
                "project_id": project_id,
            })
    return _dedupe_referents(referents)


def register_structured_referents(
    reply_text: str, referents: List[dict], project_id: Optional[int] = None
) -> None:
    """Record the structured referents behind a reply the user just saw.

    Single in-memory bounded registry (newest first). The reply text is the
    exact assistant message the user saw, so a later deictic turn can be matched
    against it.
    """
    if not reply_text or not referents:
        return
    cleaned = _dedupe_referents(referents)
    if not cleaned:
        return
    now_ts = time.monotonic()
    _prune_expired(now_ts)
    _REFERENCE_REGISTRY.insert(0, {
        "reply_text": reply_text,
        "referents": cleaned,
        "project_id": project_id,
        "recorded_at": now_ts,
    })
    del _REFERENCE_REGISTRY[_MAX_REFERENCE_ENTRIES:]


def clear_reference_registry() -> None:
    """Test hook only."""
    _REFERENCE_REGISTRY.clear()
    _PENDING_PROPOSALS.clear()


def _prune_expired(now_ts: float) -> None:
    for store in (_REFERENCE_REGISTRY, _PENDING_PROPOSALS):
        store[:] = [
            e for e in store
            if now_ts - e.get("recorded_at", 0) <= _REFERENCE_TTL_SECONDS
        ]


# ----------------------------------------------------------------------
# Deterministic resolution (never the LLM, never the user's new message)
# ----------------------------------------------------------------------
def _entry_signature(entry: dict) -> tuple:
    return tuple(
        sorted(
            (r.get("type"), r.get("date"), (r.get("label") or "").strip().lower())
            for r in entry["referents"]
        )
    )


def resolve_reference_set(
    last_assistant_reply: Optional[str],
    project_id: Optional[int] = None,
    action: str = "create_calendar",
) -> dict:
    """Resolve the deictic reference to a writable referent set.

    Match conditions (all required):
      1. ``entry.reply_text`` EXACTLY equals the immediately preceding
         assistant message.
      2. ``entry.project_id`` equals the current project scope (None == global;
         a project entry never resolves in another project).
      3. The entry is fresh (within the bounded TTL).
      4. Exactly one unambiguous candidate (entries with identical referent
         signatures count as one).

    Returns ``{"kind": "ok", "referents": [...]}``, or a ``no_candidate`` /
    ``ambiguous`` dict — never a guess.
    """
    if not last_assistant_reply:
        return {"kind": "no_candidate", "reason": "no_prior_reply", "referents": []}
    now_ts = time.monotonic()
    _prune_expired(now_ts)
    matches = [
        entry for entry in _REFERENCE_REGISTRY
        if entry.get("reply_text") == last_assistant_reply
        and entry.get("project_id") == project_id
    ]
    if not matches:
        return {"kind": "no_candidate", "reason": "no_match", "referents": []}

    signatures = {_entry_signature(entry) for entry in matches}
    if len(signatures) > 1:
        return {"kind": "ambiguous", "referents": []}
    entry = matches[0]

    referents = entry["referents"]
    if action == "create_calendar":
        writable = [r for r in referents if r.get("type") == "context_date"]
        if not writable:
            return {
                "kind": "no_candidate",
                "reason": "not_writable",
                "has_calendar_events": any(
                    r.get("type") == "calendar_event" for r in referents
                ),
                "referents": [],
            }
        return {"kind": "ok", "referents": _dedupe_referents(writable)}
    return {"kind": "ok", "referents": _dedupe_referents(referents)}


# ----------------------------------------------------------------------
# Reference-phrase detection
# ----------------------------------------------------------------------
_REFERENCE_PHRASE_RE = re.compile(
    r"\b(those|these|them|the above|the dates|the events|the schedule|"
    r"the calendar|the list|the ones above|that schedule|this schedule|"
    r"that event|that day|those days|those dates|these dates|those events|"
    r"these events|all of those|all of them|above dates)\b",
    re.IGNORECASE,
)

_READ_MARKERS = (
    "what", "list", "show", "view", "display", "check", "are there",
    "do i have", "next event", "tell me",
)
_CALENDAR_SIGNAL_WORDS = ("calendar", "schedule", "scheduling")
_WRITE_VERBS = ("add", "set", "put", "book", "create", "schedule", "make", "update", "move")
_WEEKDAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)


def _is_reference_phrase(text: str) -> bool:
    return bool(_REFERENCE_PHRASE_RE.search(text or ""))


def _has_explicit_date(text: str, now: Optional[datetime] = None) -> bool:
    if not text:
        return False
    lower = text.lower()
    now = now or datetime.now(ZoneInfo(SYSTEM_TIMEZONE))
    if extract_date_referents(text, now):
        return True
    if "tomorrow" in lower or "today" in lower:
        return True
    return any(day in lower for day in _WEEKDAYS)


def is_reference_calendar_write(text: str) -> bool:
    """True when the message points back at presented data for a calendar write.

    A pure read ("what are those dates again?") and a message that introduces
    brand-new explicit dates are never reference writes.
    """
    lower = (text or "").lower().strip()
    if not lower:
        return False
    if not _is_reference_phrase(lower):
        return False
    if any(marker in lower for marker in _READ_MARKERS):
        return False
    if not any(word in lower for word in _CALENDAR_SIGNAL_WORDS):
        return False
    if not any(verb in lower for verb in _WRITE_VERBS):
        return False
    if _has_explicit_date(lower):
        return False
    return True


# ----------------------------------------------------------------------
# Confirmation gate (backend-authoritative, single-use)
# ----------------------------------------------------------------------
_AFFIRMATIONS = {
    "yes", "yeah", "yep", "yup", "ok", "okay", "sure",
    "sounds good", "go ahead", "do it", "please do", "confirmed", "approved",
}

_NEGATIONS_RE = re.compile(r"\b(no|nope|don'?t|dont|not|cancel|nevermind|never mind|wait|hold on)\b", re.IGNORECASE)
_AFFIRM_ACTION_RE = re.compile(
    r"\b(add|put|schedule|book|create|set)\s+(them|it|those|these|all|the dates|the above)\b",
    re.IGNORECASE,
)
_BARE_AFFIRMATION_RE = re.compile(r"\b(yes|yeah|yep|yup|okay|ok|sure|go ahead|do it|please do|confirmed|approved|sounds good)\b", re.IGNORECASE)


def _is_confirmation_text(text: str) -> bool:
    if not text:
        return False
    if "?" in text:
        return False
    if _NEGATIONS_RE.search(text):
        return False
    return bool(_AFFIRM_ACTION_RE.search(text) or _BARE_AFFIRMATION_RE.search(text))


def _assistant_asked_confirmation(reply: Optional[str]) -> bool:
    low = (reply or "").lower()
    if not low:
        return False
    has_signal = any(
        word in low for word in ("calendar", "schedule", "add", "date", "dates")
    )
    has_ask = ("?" in (reply or "")) or any(
        m in low for m in ("want me to", "should i", "shall i", "do you want", "can i", "confirm")
    )
    return has_signal and has_ask


def resolve_confirmation(
    user_message: str,
    last_assistant_reply: Optional[str],
    project_id: Optional[int] = None,
) -> Optional[dict]:
    """Return the referent set when the message confirms the pending proposal.

    A confirmation only authorizes the EXACT reference set whose proposal text
    equals the immediately preceding assistant message, in the same project
    scope, and still fresh. Matching consumes the single-use proposal.
    """
    if not _is_confirmation_text((user_message or "").lower()):
        return None
    now_ts = time.monotonic()
    _prune_expired(now_ts)
    if not _assistant_asked_confirmation(last_assistant_reply):
        return {"kind": "not_pending"}
    matches = [
        p for p in _PENDING_PROPOSALS
        if p.get("proposal_reply_text") == last_assistant_reply
        and p.get("project_id") == project_id
    ]
    if not matches:
        return {"kind": "not_pending"}
    proposal = matches[0]
    _PENDING_PROPOSALS.remove(proposal)
    return {"kind": "execute", "referents": proposal["referents"]}


# ----------------------------------------------------------------------
# Proposal flow
# ----------------------------------------------------------------------
def _build_proposal_text(referents: List[dict]) -> str:
    lines = []
    for ref in referents:
        label = (ref.get("label") or "").strip()
        pretty = ref.get("date_text") or _pretty_date(ref.get("date"))
        lines.append(f"- {label} — {pretty}" if label else f"- {pretty}")
    count = len(referents)
    noun = "date" if count == 1 else "dates"
    return (
        f"I found these {count} {noun}:\n" + "\n".join(lines) + "\n\n"
        f"Each would be added to your Google Calendar at 9:00 AM for 1 hour "
        f"({SYSTEM_TIMEZONE}). Add all {count} to your Google Calendar?"
    )


def propose_reference_calendar(
    user_message: str,
    last_assistant_reply: Optional[str],
    project_id: Optional[int] = None,
) -> Optional[dict]:
    """Turn a deictic calendar-write request into a proposal or clarification.

    The first request NEVER writes. It returns either a confirmation proposal
    (with the exact referenced dates) or an honest clarification.
    """
    if not _is_reference_phrase(user_message):
        return None
    if not is_reference_calendar_write(user_message):
        return None
    if not last_assistant_reply:
        return {
            "kind": "clarify",
            "reply": (
                "I don't have a recent set of dates in front of me to add. "
                "Ask me to show you the dates (for example 'what is my exam "
                "schedule?') and then I can add them to your calendar."
            ),
        }

    resolution = resolve_reference_set(last_assistant_reply, project_id, action="create_calendar")
    if resolution["kind"] == "no_candidate":
        if resolution.get("has_calendar_events"):
            return {
                "kind": "clarify",
                "reply": (
                    "Those dates are already on your Google Calendar, so I "
                    "didn't create any new events. If you meant a different "
                    "set of dates, tell me which ones."
                ),
            }
        return {
            "kind": "clarify",
            "reply": (
                "I don't have a recent set of dates in front of me to add. "
                "Ask me to show you the dates (for example 'what is my exam "
                "schedule?') and then I can add them to your calendar."
            ),
        }
    if resolution["kind"] == "ambiguous":
        return {
            "kind": "clarify",
            "reply": "I found a few recent sets of dates. Which one should I add to your Google Calendar?",
        }

    referents = resolution["referents"]
    proposal = _build_proposal_text(referents)
    _PENDING_PROPOSALS.insert(0, {
        "proposal_reply_text": proposal,
        "referents": referents,
        "project_id": project_id,
        "recorded_at": time.monotonic(),
    })
    del _PENDING_PROPOSALS[_MAX_PENDING_PROPOSALS:]
    return {"kind": "proposal", "reply": proposal}