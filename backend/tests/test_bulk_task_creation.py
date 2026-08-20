"""
Deterministic bulk task-creation regression tests.

Covers the pre-planner bulk-task handler that turns an explicitly provided list
of topics into one task per topic:
- explicit bulk requests create exactly one task per topic through the EXISTING
  create_task execution path;
- the requested prefix is applied verbatim ("saying study before them");
- project assignment uses the trusted mechanism (the project-scoped workspace
  id is authoritative; a named project is resolved by name through the same
  trusted resolution create_task uses; a message-supplied numeric project_id can
  never override it);
- empty/malformed lists and ordinary questions/statements containing a list are
  never intercepted;
- partial failures are reported honestly ("Created X of Y tasks");
- the LLM fallback can never claim success for a bulk request it didn't act on;
- existing single-task creation behavior is unchanged.
"""

import pytest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Project, Task
from app.services.ai_service import (
    chat_with_ai,
    _parse_bulk_task_request,
)

BULK_MSG = (
    "Now make these topics as individual tasks in the In-SEM project by saying "
    "study before them\n"
    "Introduction to Data Science: Definition\n"
    "Data Science in various fields\n"
    "Examples"
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _project(db, name="In-SEM"):
    p = Project(name=name, description="")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _tasks_in(db, project_id):
    return db.query(Task).filter(Task.project_id == project_id).all()


def _all_tasks(db):
    return db.query(Task).all()


def _task_created(t):
    return {"data": t}


# ----------------------------------------------------------------------
# Happy path through the existing create_task execution path
# ----------------------------------------------------------------------
def test_explicit_bulk_request_creates_one_task_per_topic(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError) as mock_plan, \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        reply = chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )

    assert mock_plan.call_count == 0  # planner is never reached
    assert reply.startswith("Created 3 of 3 tasks.")
    assert '- "Study Introduction to Data Science: Definition"' in reply
    assert '- "Study Data Science in various fields"' in reply
    assert '- "Study Examples"' in reply

    tasks = _tasks_in(db_session, p.id)
    assert len(tasks) == 3
    assert sorted(t.title for t in tasks) == sorted([
        "Study Introduction to Data Science: Definition",
        "Study Data Science in various fields",
        "Study Examples",
    ])


def test_correct_project_assignment(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )
    tasks = _tasks_in(db_session, p.id)
    assert len(tasks) == 3
    assert all(t.project_id == p.id for t in tasks)


def test_correct_requested_prefix(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )
    titles = [t.title for t in _tasks_in(db_session, p.id)]
    assert all(title.startswith("Study ") for title in titles)
    # "Study" is prefixed, not duplicated for topics that already carry it.
    assert "Study Study" not in " ".join(titles)


def test_each_topic_becomes_exactly_one_task(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )
    tasks = _tasks_in(db_session, p.id)
    assert len(tasks) == 3
    # No topic produced zero tasks and none produced more than one.
    assert len({t.title for t in tasks}) == 3


def test_no_giant_combined_task(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )
    tasks = _tasks_in(db_session, p.id)
    assert len(tasks) == 3
    combined = "Data Science in various fields, Examples"
    assert not any(combined in (t.title or "") for t in tasks)


# ----------------------------------------------------------------------
# Empty / malformed lists, and ordinary statements/questions
# ----------------------------------------------------------------------
@pytest.mark.parametrize("message", [
    "make these topics as individual tasks in the In-SEM project by saying study before them",
    "make these topics into tasks in the In-SEM project:",
    "now make these topics as individual tasks in the Insem Project by saying study before them like 'Study Role of a Data Scientist'",
])
def test_empty_or_malformed_list_creates_nothing(db_session, message):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool") as mock_exec, \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert "couldn't find a list of topics" in reply
    create_calls = [c for c in mock_exec.call_args_list if c.args[0] == "create_task"]
    assert create_calls == []
    assert _all_tasks(db_session) == []


@pytest.mark.parametrize("message", [
    "What are these topics as individual tasks? Data Science: Definition, Examples",
    "Can you show me these topics as separate tasks: A, B, C?",
    "I really like these topics as separate tasks: A, B",
    "please don't make these topics into tasks: A, B",
])
def test_ordinary_question_or_statement_with_list_does_not_create(db_session, message):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", return_value=None), \
         patch("app.services.ai_service.execute_tool") as mock_exec, \
         patch("app.services.ai_service.complete_text", return_value="ordinary answer"):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert reply == "ordinary answer"
    create_calls = [c for c in mock_exec.call_args_list if c.args[0] == "create_task"]
    assert create_calls == []
    assert _all_tasks(db_session) == []


# ----------------------------------------------------------------------
# Trusted project resolution, isolation, spoofing
# ----------------------------------------------------------------------
def test_project_isolation_workspace_scope_is_authoritative(db_session):
    p_a = _project(db_session, "Alpha")
    _project(db_session, "Beta")
    message = "make these topics into tasks in the Beta project\nX topic\nY topic"

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p_a.id,
        )

    assert "Created 2 of 2 tasks." in reply
    assert len(_tasks_in(db_session, p_a.id)) == 2
    assert _all_tasks(db_session) == _tasks_in(db_session, p_a.id)  # nothing leaked to Beta


def test_project_id_spoofing_cannot_override_trusted_project(db_session):
    p_a = _project(db_session, "Alpha")
    message = "make these topics as individual tasks in the project 99\nX topic\nY topic"

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p_a.id,
        )

    assert "Created 2 of 2 tasks." in reply
    tasks = _all_tasks(db_session)
    assert len(tasks) == 2
    assert all(t.project_id == p_a.id for t in tasks)


def test_unresolvable_named_project_creates_nothing(db_session):
    _project(db_session, "Alpha")
    message = "make these topics into tasks in the NonExistent project\nX topic"

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool") as mock_exec:
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=None,
        )

    assert "Project not found" in reply
    assert "No tasks were created" in reply
    assert mock_exec.call_count == 0
    assert _all_tasks(db_session) == []


# ----------------------------------------------------------------------
# Honest partial-failure reporting
# ----------------------------------------------------------------------
def test_partial_failure_reported_honestly(db_session):
    p = _project(db_session)
    message = "make these topics into tasks in the In-SEM project\nA\nB\nC"
    counters = {"n": 0}

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_task":
            counters["n"] += 1
            if counters["n"] <= 2:
                t = Task(title=args["title"], project_id=args["project_id"])
                db.add(t)
                db.commit()
                db.refresh(t)
                return {"data": t}
            return {"data": {"error": "boom"}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert "Created 2 of 3 tasks." in reply
    assert "Couldn't create:" in reply
    assert '"C": boom' in reply
    assert "Created 3 of 3" not in reply
    assert len(_tasks_in(db_session, p.id)) == 2


def test_zero_tasks_created_reported_honestly(db_session):
    p = _project(db_session)
    message = "make these topics into tasks in the In-SEM project\nA\nB"

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_task":
            return {"data": {"error": "boom"}}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert "I couldn't create any tasks." in reply
    assert "Created 0 of 2 tasks." in reply
    assert "Couldn't create:" in reply
    assert _all_tasks(db_session) == []


# ----------------------------------------------------------------------
# The existing create_task path is reused (never a second implementation)
# ----------------------------------------------------------------------
def test_existing_create_task_path_reused(db_session):
    p = _project(db_session)
    message = "add the following tasks to the In-SEM project\nX\nY"
    calls = []

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_task":
            calls.append((tool_name, dict(args)))
            t = Task(title=args["title"], project_id=args["project_id"])
            db.add(t)
            db.commit()
            db.refresh(t)
            return {"data": t}
        return {"data": {}}

    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        reply = chat_with_ai(
            [{"role": "user", "content": message}],
            db_session,
            project_id=p.id,
        )

    assert "Created 2 of 2 tasks." in reply
    assert len(calls) == 2
    for tool_name, args in calls:
        assert tool_name == "create_task"
        assert args["project_id"] == p.id
    assert sorted(args["title"] for _, args in calls) == ["X", "Y"]


def test_planner_not_required_for_valid_bulk_request(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError) as mock_plan, \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError):
        reply = chat_with_ai(
            [{"role": "user", "content": BULK_MSG}],
            db_session,
            project_id=p.id,
        )
    assert mock_plan.call_count == 0
    assert "Created 3 of 3 tasks." in reply


# ----------------------------------------------------------------------
# The LLM fallback can never claim success for an un-dispatched bulk request
# ----------------------------------------------------------------------
def test_llm_fallback_cannot_falsely_claim_success(db_session):
    p = _project(db_session)
    with patch("app.services.ai_service.plan_tool_call", side_effect=AssertionError), \
         patch("app.services.ai_service.execute_tool") as mock_exec, \
         patch("app.services.ai_service.complete_text", side_effect=AssertionError) as mock_ct:
        reply = chat_with_ai(
            [{"role": "user", "content": "make these topics as individual tasks in the In-SEM project"}],
            db_session,
            project_id=p.id,
        )

    assert "couldn't find a list of topics" in reply
    assert "successfully" not in reply.lower()
    assert mock_ct.call_count == 0
    assert mock_exec.call_count == 0


# ----------------------------------------------------------------------
# Existing single-task creation behavior is unchanged
# ----------------------------------------------------------------------
def test_single_task_creation_behavior_unchanged(db_session):
    p = _project(db_session)

    def fake_execute(tool_name, args, db, **kwargs):
        if tool_name == "create_task":
            t = Task(title=args["title"], project_id=args.get("project_id"))
            db.add(t)
            db.commit()
            db.refresh(t)
            return {"data": t}
        return {"data": {}}

    with patch(
        "app.services.ai_service.plan_tool_call",
        return_value={"tool": "create_task", "args": {"title": "Study Data Science", "project_name": "In-SEM"}},
    ) as mock_plan, \
         patch("app.services.ai_service.execute_tool", side_effect=fake_execute):
        reply = chat_with_ai(
            [{"role": "user", "content": "create a task called Study Data Science in the In-SEM project"}],
            db_session,
            project_id=p.id,
        )

    # A single-task request is NOT a bulk request: the planner still runs.
    assert mock_plan.call_count == 1
    assert reply.startswith("Created task")
    assert len(_all_tasks(db_session)) == 1


# ----------------------------------------------------------------------
# Deterministic list parsing
# ----------------------------------------------------------------------
def test_parser_inline_comma_list():
    msg = ("make these topics as individual tasks in the In-SEM project by saying "
           "study before them: Data Science: Definition, Examples, Impact of Data Science")
    parsed = _parse_bulk_task_request(msg)
    assert parsed is not None
    assert parsed["prefix"] == "study"
    assert parsed["project_name"] == "In-SEM"
    assert parsed["topics"] == ["Data Science: Definition", "Examples", "Impact of Data Science"]


def test_parser_bullets():
    msg = ("make these topics into tasks in the In-SEM project:\n"
           "- Intro to DS: Definition\n"
           "- Data Science in various fields")
    parsed = _parse_bulk_task_request(msg)
    assert parsed["topics"] == ["Intro to DS: Definition", "Data Science in various fields"]


def test_parser_quoted_example_not_a_topic():
    msg = ("now make these topics as individual tasks in the Insem Project by saying "
           "study before them like 'Study Role of a Data Scientist'\n"
           "Introduction to Data Science: Definition\n"
           "Data Science in various fields")
    parsed = _parse_bulk_task_request(msg)
    assert parsed is not None
    assert parsed["prefix"] == "study"
    assert parsed["project_name"] == "Insem"
    assert parsed["topics"] == [
        "Introduction to Data Science: Definition",
        "Data Science in various fields",
    ]


def test_parser_project_name_after_the_word_project():
    msg = "add following tasks to the project Introduction to Data Science: Definition, Examples"
    parsed = _parse_bulk_task_request(msg)
    assert parsed is not None
    assert parsed["project_name"] == "Introduction to Data Science"
    assert parsed["topics"] == ["Definition", "Examples"]


def test_parser_topic_containing_project_words_is_not_a_project_selector():
    msg = ("make these topics into tasks in the In-SEM project:\n"
           "- in the machine learning project\n"
           "- Data Science")
    parsed = _parse_bulk_task_request(msg)
    assert parsed is not None
    assert parsed["project_name"] == "In-SEM"
    assert parsed["topics"] == ["in the machine learning project", "Data Science"]