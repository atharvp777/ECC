"""
Contextual reference resolution regression tests.

Covers the calendar/date reference case:
- bounded backend registry keyed by the EXACT preceding assistant reply text;
- deterministic date extraction from authoritative project-context rows only;
- deterministic resolver (never the LLM, never dates from the user's NEW
  message);
- project_id scope isolation in both directions;
- first reference request creates ZERO events and returns a proposal listing the
  exact dates;
- only an explicit confirmation tied to that exact pending proposal authorizes
  the write; bare affirmations without a prior confirmation question do NOT;
- confirmed writes reuse the EXISTING create_calendar_event path (one call per
  referent), require a real Google event id, and report partial failures
  honestly;
- free-form LLM text is never a referent source; context can never manufacture
  write authorization.
"""

import datetime as _dt
from datetime import datetime, date
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.services import reference_resolution as rr
from app.services.ai_service import chat_with_ai, _handle_reference_turn, _register_reply_referents
from app.core.database import Base
from app.models.project import Project
from app.models.project_context import ProjectContext
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


EXAM_SCHEDULE = (
    "EXAM SCHEDULE \nExam time: 2:00 PM to 3:00 PM.\n"
    "25-08 DSV(410341) / 27-08 WT(410342) / 29-08 IoT(410343) / "
    "31-08 BDA(410344A) Elective-III / 01-09 HCI(410345B) Elective-IV"
)

_NOW = datetime(2026, 8, 16, 22, 30, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

_PRESENTING_REPLY = (
    "Your exam schedule is: 25 August DSV(410341), 27 August WT(410342), "
    "29 August IoT(410343), 31 August BDA(410344A), 1 September HCI(410345B)."
)


@pytest.fixture(autouse=True)
def _clean_reference_state():
    rr.clear_reference_registry()
    yield
    rr.clear_reference_registry()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _seed_project(db, name="In-SEM"):
    p = Project(name=name, description="")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _seed_context(db, project_id, content, category="note"):
    item = ProjectContext(
        project_id=project_id, content=content, category=category, source="user"
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _context_referents(project_id=3):
    return [
        {
            "type": "context_date",
            "date": "2026-08-25",
            "date_text": "August 25, 2026",
            "label": "DSV(410341)",
            "source": "project_context",
            "project_id": project_id,
        },
        {
            "type": "context_date",
            "date": "2026-08-27",
            "date_text": "August 27, 2026",
            "label": "WT(410342)",
            "source": "project_context",
            "project_id": project_id,
        },
        {
            "type": "context_date",
            "date": "2026-08-29",
            "date_text": "August 29, 2026",
            "label": "IoT(410343)",
            "source": "project_context",
            "project_id": project_id,
        },
        {
            "type": "context_date",
            "date": "2026-08-31",
            "date_text": "August 31, 2026",
            "label": "BDA(410344A) Elective-III",
            "source": "project_context",
            "project_id": project_id,
        },
        {
            "type": "context_date",
            "date": "2026-09-01",
            "date_text": "September 01, 2026",
            "label": "HCI(410345B) Elective-IV",
            "source": "project_context",
            "project_id": project_id,
        },
    ]


def _present(db, project_id, reply=_PRESENTING_REPLY):
    """Simulate the assistant having just presented the dates: the same
    capture helper chat_with_ai uses to register the reply's referents."""
    _register_reply_referents(reply, db, project_id)


# ----------------------------------------------------------------------
# Deterministic date extraction (authoritative rows only)
# ----------------------------------------------------------------------
def test_extract_date_referents_exam_schedule():
    refs = rr.extract_date_referents(EXAM_SCHEDULE, _NOW)
    dates = [(r["date"], r["label"]) for r in refs]
    assert dates == [
        ("2026-08-25", "DSV(410341)"),
        ("2026-08-27", "WT(410342)"),
        ("2026-08-29", "IoT(410343)"),
        ("2026-08-31", "BDA(410344A) Elective-III"),
        ("2026-09-01", "HCI(410345B) Elective-IV"),
    ]


def test_extract_date_referents_supports_iso_and_month_names():
    refs = rr.extract_date_referents(
        "2026-08-25 release, August 29 review, 25/08 sprint", _NOW
    )
    dates = sorted(r["date"] for r in refs)
    assert dates == ["2026-08-25", "2026-08-29"]


def test_project_context_referents_only_include_dates_the_reply_presented(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)

    shown = rr.referents_from_project_context(db_session, p.id, _PRESENTING_REPLY, now=_NOW)
    assert {r["date"] for r in shown} == {
        "2026-08-25", "2026-08-27", "2026-08-29", "2026-08-31", "2026-09-01",
    }

    # A reply that does NOT surface the dates yields nothing — a free-form
    # answer about something else can never become referents.
    hidden = rr.referents_from_project_context(
        db_session, p.id, "No, let's focus on the design first.", now=_NOW
    )
    assert hidden == []


def test_calendar_event_referents_from_live_result():
    events = [
        {"id": "e1", "title": "IoT Exam", "start": "2026-08-29T14:00:00+05:30", "end": "2026-08-29T15:00:00+05:30", "location": None},
        {"id": "e2", "title": "All Day", "start": "2026-08-30", "end": "2026-08-31", "location": None},
    ]
    refs = rr.referents_from_calendar_events(events, project_id=3)
    assert {r["date"] for r in refs} == {"2026-08-29", "2026-08-30"}
    assert all(r["type"] == "calendar_event" for r in refs)


# ----------------------------------------------------------------------
# Registry + resolver
# ----------------------------------------------------------------------
def test_register_then_resolve_ok():
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    resolution = rr.resolve_reference_set(_PRESENTING_REPLY, 3, action="create_calendar")
    assert resolution["kind"] == "ok"
    assert len(resolution["referents"]) == 5
    assert {r["date"] for r in resolution["referents"]} == {
        "2026-08-25", "2026-08-27", "2026-08-29", "2026-08-31", "2026-09-01",
    }


def test_resolve_requires_exact_preceding_assistant_reply():
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    resolution = rr.resolve_reference_set(
        "a different assistant reply", 3, action="create_calendar"
    )
    assert resolution["kind"] == "no_candidate"


def test_resolve_without_any_prior_reply_is_no_candidate():
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    resolution = rr.resolve_reference_set(None, 3, action="create_calendar")
    assert resolution["kind"] == "no_candidate"


def test_resolve_enforces_project_scope_both_directions():
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    # Project 3 entry never resolves in project 4 or in global chat.
    assert rr.resolve_reference_set(_PRESENTING_REPLY, 4, action="create_calendar")["kind"] == "no_candidate"
    assert rr.resolve_reference_set(_PRESENTING_REPLY, None, action="create_calendar")["kind"] == "no_candidate"

    # Global entry never resolves in a project.
    rr.clear_reference_registry()
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(None), None)
    assert rr.resolve_reference_set(_PRESENTING_REPLY, 3, action="create_calendar")["kind"] == "no_candidate"
    assert rr.resolve_reference_set(_PRESENTING_REPLY, None, action="create_calendar")["kind"] == "ok"


def test_ambiguous_resolution_is_clarification_not_guess():
    # Two distinct presentations share the SAME reply text -> cannot pick.
    rr.register_structured_referents(
        "Duplicate reply",
        [dict(_context_referents(3)[0], date="2026-08-25", label="A")],
        3,
    )
    rr.register_structured_referents(
        "Duplicate reply",
        [dict(_context_referents(3)[0], date="2026-08-26", label="B")],
        3,
    )
    resolution = rr.resolve_reference_set("Duplicate reply", 3, action="create_calendar")
    assert resolution["kind"] == "ambiguous"

    outcome = rr.propose_reference_calendar("Set those dates on my calendar", "Duplicate reply", 3)
    assert outcome["kind"] == "clarify"
    assert "Which one" in outcome["reply"]


def test_calendar_event_referents_are_never_writable():
    events = [{"id": "e1", "title": "IoT Exam", "start": "2026-08-29T14:00:00+05:30", "end": "2026-08-29T15:00:00+05:30", "location": None}]
    rr.register_structured_referents(
        _PRESENTING_REPLY, rr.referents_from_calendar_events(events, 3), 3
    )
    outcome = rr.propose_reference_calendar("Set those dates on my calendar", _PRESENTING_REPLY, 3)
    assert outcome["kind"] == "clarify"
    assert "already on your Google Calendar" in outcome["reply"]


# ----------------------------------------------------------------------
# Reference-phrase detection (never dates from the new message)
# ----------------------------------------------------------------------
def test_reference_write_phrases_detected():
    assert rr.is_reference_calendar_write("Set those dates on my calendar")
    assert rr.is_reference_calendar_write("schedule the above")
    assert rr.is_reference_calendar_write("add them to my calendar")
    assert rr.is_reference_calendar_write("put these events on my calendar")


def test_read_requests_are_never_reference_writes():
    assert not rr.is_reference_calendar_write("what are those dates again?")
    assert not rr.is_reference_calendar_write("list the events on my calendar")
    assert not rr.is_reference_calendar_write("show me those dates")


def test_new_message_dates_are_never_parsed_for_reference_resolution():
    # A brand-new explicit date in the user's message means this is NOT a pure
    # deictic reference — the resolver must never grab dates from the message.
    assert not rr.is_reference_calendar_write("add those dates for 30 august to my calendar")
    assert not rr.is_reference_calendar_write("set those events on 25/08")
    assert not rr.is_reference_calendar_write("schedule the above tomorrow")


def test_non_calendar_deictic_phrases_are_not_writes():
    assert not rr.is_reference_calendar_write("make them my priority")
    assert not rr.is_reference_calendar_write("complete those tasks")


# ----------------------------------------------------------------------
# Proposal + confirmation gate
# ----------------------------------------------------------------------
def test_first_request_proposes_and_lists_exact_dates_creates_zero_events(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)
    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool") as mock_exec:
        reply = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )
    assert reply.startswith("I found these 5 dates:")
    assert "DSV(410341) — August 25, 2026" in reply
    assert "HCI(410345B) Elective-IV — September 01, 2026" in reply
    assert "Add all 5 to your Google Calendar?" in reply
    # ZERO events were created on the first request.
    create_calls = [c for c in mock_exec.call_args_list if c.args[0] == "create_calendar_event"]
    assert create_calls == []


def test_confirmation_authorizes_exact_reference_set_via_existing_path(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)

    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append(args["event_data"])
            return {"data": {
                "id": f"evt-{len(create_calls)}",
                "summary": args["event_data"]["summary"],
                "start": args["event_data"]["start"],
                "end": args["event_data"]["end"],
            }}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        # 1) Proposal turn.
        proposal = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )
        assert proposal.startswith("I found these 5 dates:")
        assert create_calls == []

        # 2) Confirmation turn.
        result = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
                {"role": "assistant", "content": proposal},
                {"role": "user", "content": "Yes"},
            ],
            db_session,
            project_id=p.id,
        )

    assert len(create_calls) == 5
    summaries = sorted(c["summary"] for c in create_calls)
    assert summaries == sorted(
        ["DSV(410341)", "WT(410342)", "IoT(410343)", "BDA(410344A) Elective-III", "HCI(410345B) Elective-IV"]
    )
    assert "Added 5 events to your Google Calendar:" in result
    assert "evt-1" in result or "starting at" in result


def test_confirmation_words_other_than_bare_yes_also_authorize(db_session):
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    proposal = rr.propose_reference_calendar("Set those dates on my calendar", _PRESENTING_REPLY, 3)["reply"]

    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append(args["event_data"])
            return {"data": {"id": "x", "summary": args["event_data"]["summary"], "start": args["event_data"]["start"], "end": args["event_data"]["end"]}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        result = chat_with_ai(
            [
                {"role": "assistant", "content": proposal},
                {"role": "user", "content": "Go ahead"},
            ],
            db_session,
            project_id=3,
        )
    assert len(create_calls) == 5
    assert "Added 5 events" in result


def test_bare_yes_without_preceding_confirmation_question_never_writes(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)

    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append(args)
            return {"data": {"id": "x"}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute) as mock_exec, \
         patch("app.services.ai_service.complete_text", return_value="Alright, I'll keep those in mind."):
        result = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "yes"},
            ],
            db_session,
            project_id=p.id,
        )

    assert create_calls == []
    assert mock_exec.call_count == 0
    assert result  # ordinary LLM answer, no write


def test_confirmation_is_tied_to_exact_pending_proposal():
    rr.register_structured_referents(_PRESENTING_REPLY, _context_referents(3), 3)
    proposal = rr.propose_reference_calendar("Set those dates on my calendar", _PRESENTING_REPLY, 3)["reply"]

    # A confirmation answering a DIFFERENT prior reply does not authorize.
    outcome = rr.resolve_confirmation("yes", "That sounds good, do you want me to continue?", 3)
    assert outcome == {"kind": "not_pending"}

    # The correct proposal authorizes exactly once; the proposal is consumed.
    outcome1 = rr.resolve_confirmation("yes", proposal, 3)
    assert outcome1["kind"] == "execute"
    assert len(outcome1["referents"]) == 5
    outcome2 = rr.resolve_confirmation("okay", proposal, 3)
    assert outcome2 == {"kind": "not_pending"}


def test_confirmation_rejects_questions_and_negations():
    assert rr._is_confirmation_text("no") is False
    assert rr._is_confirmation_text("don't add them") is False
    assert rr._is_confirmation_text("what?") is False
    assert rr._is_confirmation_text("cancel") is False


# ----------------------------------------------------------------------
# Cross-project isolation through the full chat path
# ----------------------------------------------------------------------
def test_cross_project_reference_never_resolves(db_session):
    p3 = _seed_project(db_session, "In-SEM")
    _seed_project(db_session, "Other")
    _seed_context(db_session, p3.id, EXAM_SCHEDULE)
    _present(db_session, p3.id)

    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append(args)
            return {"data": {"id": "x"}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        # Presentation in project 3.
        chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p3.id,
        )
        # Same request in another project scope (no prior presentation there).
        reply_other = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p3.id + 100,
        )

    assert "I don't have a recent set of dates" in reply_other
    assert create_calls == []


# ----------------------------------------------------------------------
# Honest write reporting through the full chat path
# ----------------------------------------------------------------------
def test_write_requires_real_event_id_never_claims_success(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            # No event id -> success must NOT be claimed.
            return {"data": {"summary": args["event_data"]["summary"]}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        proposal = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )
        result = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
                {"role": "assistant", "content": proposal},
                {"role": "user", "content": "Yes"},
            ],
            db_session,
            project_id=p.id,
        )

    assert "Added" not in result
    assert "Couldn't add 5 events" in result


def test_partial_failure_reported_honestly(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)
    counters = {"n": 0}

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            counters["n"] += 1
            if counters["n"] <= 3:
                return {"data": {
                    "id": f"evt-{counters['n']}",
                    "summary": args["event_data"]["summary"],
                    "start": args["event_data"]["start"],
                    "end": args["event_data"]["end"],
                }}
            return {"data": {"error": "Google Calendar is unavailable right now"}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        proposal = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )
        result = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
                {"role": "assistant", "content": proposal},
                {"role": "user", "content": "Yes"},
            ],
            db_session,
            project_id=p.id,
        )

    assert "Added 3 events to your Google Calendar:" in result
    assert "Couldn't add 2 events:" in result
    assert "Added 5" not in result


# ----------------------------------------------------------------------
# Context can never manufacture write authorization; free-form text is not
# a referent source; the write path stays the single calendar-write path.
# ----------------------------------------------------------------------
def test_context_alone_cannot_authorize_a_write(db_session):
    # Project context exists, but no assistant reply presented it -> nothing
    # is registered, so a deictic request must clarify instead of resolving.
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool") as mock_exec:
        reply = chat_with_ai(
            [
                {"role": "assistant", "content": "Let's talk about the architecture instead."},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )

    assert "I don't have a recent set of dates" in reply
    create_calls = [c for c in mock_exec.call_args_list if c.args[0] == "create_calendar_event"]
    assert create_calls == []


def test_reference_registry_is_bounded():
    for i in range(30):
        rr.register_structured_referents(f"reply-{i}", [{"type": "context_date", "date": "2026-08-25", "date_text": "x", "label": f"L{i}", "source": "project_context", "project_id": 3}], 3)
    assert len(rr._REFERENCE_REGISTRY) <= rr._MAX_REFERENCE_ENTRIES


def test_reference_write_uses_existing_create_calendar_event_request_shape(db_session):
    # The confirmed write must call the exact existing tool name with an
    # event_data body — the same shape the planner would produce.
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)
    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append((tool_name, args))
            return {"data": {"id": "id", "summary": args["event_data"]["summary"], "start": args["event_data"]["start"], "end": args["event_data"]["end"]}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        proposal = chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
            ],
            db_session,
            project_id=p.id,
        )
        chat_with_ai(
            [
                {"role": "assistant", "content": _PRESENTING_REPLY},
                {"role": "user", "content": "Set those dates on my calendar"},
                {"role": "assistant", "content": proposal},
                {"role": "user", "content": "yes"},
            ],
            db_session,
            project_id=p.id,
        )

    assert create_calls
    for tool_name, args in create_calls:
        assert tool_name == "create_calendar_event"
        assert set(args.keys()) == {"event_data"}
        assert "start" in args["event_data"] and "end" in args["event_data"]
        assert args["event_data"]["start"]["timeZone"] == "Asia/Kolkata"


def test_recent_calendar_events_recorded_after_confirmed_write(db_session):
    # The confirmed write flows through the same success recording used by any
    # other calendar event, so a follow-up correction can still target it.
    from app.services import ai_service
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            return {"data": {"id": "recent-1", "summary": args["event_data"]["summary"], "start": args["event_data"]["start"], "end": args["event_data"]["end"]}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        proposal = chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": "Set those dates on my calendar"}],
            db_session, project_id=p.id,
        )
        chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": "Set those dates on my calendar"}, {"role": "assistant", "content": proposal}, {"role": "user", "content": "yes"}],
            db_session, project_id=p.id,
        )

    ids = [e["event_id"] for e in ai_service._RECENT_CALENDAR_EVENTS[:5]]
    assert "recent-1" in ids


# ----------------------------------------------------------------------
# Corrective-fix regression tests (planner "none" sentinel + phrase variants)
# ----------------------------------------------------------------------
def test_planner_none_sentinel_is_never_dispatched(db_session):
    # The Gemini json_mode "no tool" answer may arrive as the object sentinel
    # {"tool": "none", "args": {}} instead of the bare NONE token. It must be
    # treated exactly as no tool and NEVER reach execute_tool.
    p = _seed_project(db_session)
    with patch("app.services.ai_service.plan_tool_call", return_value={"tool": "none", "args": {}}), \
         patch("app.services.ai_service.execute_tool") as mock_exec, \
         patch("app.services.ai_service.complete_text", return_value="hello from the fallback") as mock_ct:
        reply = chat_with_ai(
            [{"role": "user", "content": "say hi"}],
            db_session,
            project_id=p.id,
        )

    assert mock_exec.call_count == 0
    assert "Unknown tool" not in reply
    assert reply == "hello from the fallback"
    assert mock_ct.called


def test_planner_uppercase_none_sentinel_is_never_dispatched(db_session):
    p = _seed_project(db_session)
    with patch("app.services.ai_service.plan_tool_call", return_value={"tool": "NONE", "args": {}}), \
         patch("app.services.ai_service.execute_tool") as mock_exec, \
         patch("app.services.ai_service.complete_text", return_value="fallback") as mock_ct:
        reply = chat_with_ai(
            [{"role": "user", "content": "anything"}],
            db_session,
            project_id=p.id,
        )

    assert mock_exec.call_count == 0
    assert reply == "fallback"


@pytest.mark.parametrize("message", [
    "Set those dates on my calendar",
    "set the exam dates on my calendar",
    "add those exam dates to my calendar",
    "put these exam dates on my calendar",
])
def test_reference_phrase_variants_propose_same_dates_zero_writes(db_session, message):
    # All equivalent deictic variants must resolve to the SAME proposal with
    # ZERO writes on the first request.
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)
    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool") as mock_exec:
        reply = chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert reply.startswith("I found these 5 dates:")
    assert "DSV(410341) — August 25, 2026" in reply
    assert "Add all 5 to your Google Calendar?" in reply
    create_calls = [c for c in mock_exec.call_args_list if c.args[0] == "create_calendar_event"]
    assert create_calls == []


def test_second_confirmation_creates_no_additional_writes(db_session):
    p = _seed_project(db_session)
    _seed_context(db_session, p.id, EXAM_SCHEDULE)
    _present(db_session, p.id)
    create_calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_calendar_event":
            create_calls.append(args["event_data"])
            return {"data": {"id": f"e-{len(create_calls)}", "summary": args["event_data"]["summary"], "start": args["event_data"]["start"], "end": args["event_data"]["end"]}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute), \
         patch("app.services.ai_service.complete_text", return_value="already done"):
        proposal = chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": "Set those dates on my calendar"}],
            db_session, project_id=p.id,
        )
        first = chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": "Set those dates on my calendar"}, {"role": "assistant", "content": proposal}, {"role": "user", "content": "Yes"}],
            db_session, project_id=p.id,
        )
        second = chat_with_ai(
            [{"role": "assistant", "content": _PRESENTING_REPLY}, {"role": "user", "content": "Set those dates on my calendar"}, {"role": "assistant", "content": proposal}, {"role": "user", "content": "Yes"}, {"role": "assistant", "content": first}, {"role": "user", "content": "Okay"}],
            db_session, project_id=p.id,
        )

    assert len(create_calls) == 5
    assert "Added 5 events" in first
    assert second == "already done"
    assert len(create_calls) == 5