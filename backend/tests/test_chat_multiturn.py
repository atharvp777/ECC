"""AI multi-turn conversation tests.

Cover the follow-up behavior of the chat layer:
  * a follow-up turn plans a tool call from the LATEST user message only;
  * stale `/tool` JSON in a prior assistant reply is never re-executed;
  * the LLM fallback receives bounded history with roles/order intact,
    including the assistant reply from a prior tool turn;
  * the caller's message list is never mutated;
  * a cross-turn tool action writes to the DB;
  * the calendar-write guard still applies on a follow-up turn.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.services import ai_service
from app.services.ai_service import chat_with_ai
from app.models import Task, TaskStatus
from app.models.project import Project


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _planner_json(tool: str, args: dict) -> str:
    import json

    return json.dumps({"tool": tool, "args": args})


# ----------------------------------------------------------------------
# Follow-up tool turns
# ----------------------------------------------------------------------

def test_follow_up_tool_turn_plans_from_latest_user_message(db_session):
    """After a first turn created a task, the second turn's tool plan must be
    based on the latest user message — never on the earlier turn."""
    messages = [
        {"role": "user", "content": "create a task called Wiring Diagram"},
        {"role": "assistant", "content": 'Created task "Wiring Diagram".'},
        {"role": "user", "content": "complete it now"},
    ]

    def fake_complete(system, messages, **kwargs):
        prompt = messages[0]["content"]
        assert "complete it now" in prompt
        assert "create a task called" not in prompt
        return _planner_json("complete_task", {"task_id": 1, "task_title": "it"})

    with patch.object(ai_service, "complete_text", side_effect=fake_complete) as mock_llm:
        with patch.object(ai_service, "execute_tool", return_value={"data": None}) as mock_exec:
            chat_with_ai(messages, db_session)

    mock_exec.assert_called_once()
    assert mock_exec.call_args.args[0] == "complete_task"


def test_prior_assistant_tool_json_is_not_replanned(db_session):
    """A `/tool` block inside an OLD assistant reply must never be executed."""
    messages = [
        {"role": "user", "content": "create a task called Wiring"},
        {
            "role": "assistant",
            "content": '/tool create_task {"title": "Wiring"}',
        },
        {"role": "user", "content": "thanks"},
    ]

    with patch.object(
        ai_service, "complete_text", return_value="no problem"
    ) as mock_llm:
        with patch.object(ai_service, "execute_tool") as mock_exec:
            reply = chat_with_ai(messages, db_session)

    assert "no problem" in reply
    mock_exec.assert_not_called()
    # The planner is consulted, and the fallback still receives the full
    # conversation including the (inert) assistant tool block.
    assert mock_llm.call_count == 2
    sent = mock_llm.call_args_list[-1].kwargs["messages"]
    assert sent == messages


def test_cross_turn_complete_task_executes_against_db(db_session):
    """Turn 2 completes the task created in turn 1 — real tool execution."""
    proj = Project(name="BAJA HV", category="baja", status="active")
    db_session.add(proj)
    db_session.commit()
    task = Task(
        title="Wiring Diagram",
        priority="medium",
        status="todo",
        project_id=proj.id,
        deadline=datetime(2026, 9, 1),
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    messages = [
        {"role": "user", "content": "create a task called Wiring Diagram"},
        {"role": "assistant", "content": 'Created task "Wiring Diagram".'},
        {"role": "user", "content": "complete the Wiring Diagram task"},
    ]

    with patch.object(
        ai_service,
        "complete_text",
        return_value=_planner_json("complete_task", {"task_id": task.id, "task_title": "Wiring Diagram"}),
    ):
        reply = chat_with_ai(messages, db_session)

    assert "completed" in reply.lower()
    db_session.refresh(task)
    assert task.status is TaskStatus.DONE


# ----------------------------------------------------------------------
# Fallback history handling
# ----------------------------------------------------------------------

def test_fallback_bounded_history_preserves_roles_and_order(db_session):
    """Only the last N messages reach the model; the newest user turn is last."""
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        for i in range(ai_service._MAX_HISTORY_MESSAGES + 5)
    ]
    history[-1] = {"role": "user", "content": "hello"}

    with patch.object(ai_service, "complete_text", return_value="ok") as mock_llm:
        chat_with_ai(history, db_session)

    sent = mock_llm.call_args.kwargs["messages"]
    expected = history[-ai_service._MAX_HISTORY_MESSAGES:]
    assert sent == expected
    assert len(sent) == ai_service._MAX_HISTORY_MESSAGES
    assert sent[0]["content"] == "msg 5"
    assert sent[-1] == {"role": "user", "content": "hello"}


def test_prior_assistant_reply_is_included_in_fallback_history(db_session):
    """The model sees the assistant's earlier reply, so follow-ups can refer
    to it."""
    prior_reply = 'Created task "Wiring Diagram".'
    messages = [
        {"role": "user", "content": "create a task called Wiring Diagram"},
        {"role": "assistant", "content": prior_reply},
        {"role": "user", "content": "tell me more"},
    ]

    with patch.object(ai_service, "complete_text", return_value="sure") as mock_llm:
        chat_with_ai(messages, db_session)

    sent = mock_llm.call_args.kwargs["messages"]
    assert sent == messages


def test_planner_none_on_follow_up_falls_back_with_history(db_session):
    """When the planner declines a follow-up, the LLM fallback still receives
    the full (bounded) conversation."""
    messages = [
        {"role": "user", "content": "create a task called Wiring Diagram"},
        {"role": "assistant", "content": 'Created task "Wiring Diagram".'},
        {"role": "user", "content": "what else can you do?"},
    ]
    calls = []

    def fake_complete(system, messages, **kwargs):
        calls.append(messages)
        return "NONE" if len(calls) == 1 else "I can manage tasks."

    with patch.object(ai_service, "complete_text", side_effect=fake_complete):
        with patch.object(ai_service, "execute_tool") as mock_exec:
            reply = chat_with_ai(messages, db_session)

    assert "I can manage tasks." in reply
    mock_exec.assert_not_called()
    assert len(calls) == 2
    assert calls[1] == messages


# ----------------------------------------------------------------------
# Input immutability and guards
# ----------------------------------------------------------------------

def test_chat_with_ai_does_not_mutate_input_messages(db_session):
    messages = [
        {"role": "user", "content": "hello"},
    ]
    snapshot = [dict(m) for m in messages]

    with patch.object(ai_service, "complete_text", return_value="hi"):
        chat_with_ai(messages, db_session)

    assert messages == snapshot


def test_calendar_write_guard_applies_on_follow_up_turn(db_session):
    """A calendar-write follow-up is still blocked when Google Calendar is not
    connected — no tool runs and no event is claimed."""
    messages = [
        {"role": "user", "content": "list my tasks"},
        {"role": "assistant", "content": "Tasks: [MEDIUM] Wiring"},
        {"role": "user", "content": "schedule a meeting tomorrow at 3pm"},
    ]

    with patch.object(ai_service, "complete_text", return_value="NONE"):
        with patch.object(ai_service, "is_connected", return_value=False):
            with patch.object(ai_service, "execute_tool") as mock_exec:
                reply = chat_with_ai(messages, db_session)

    assert "isn't connected" in reply.lower()
    mock_exec.assert_not_called()


def test_two_separate_turns_tool_path(db_session):
    """Two real turns: create_task then list_tasks — each plans from its own
    latest message and the conversation accumulates normally."""
    proj = Project(name="BAJA HV", category="baja", status="active")
    db_session.add(proj)
    db_session.commit()
    task = Task(
        title="Wiring",
        priority="medium",
        status="todo",
        project_id=proj.id,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    turn1 = [{"role": "user", "content": "create a task called Wiring"}]
    turn2 = [
        {"role": "user", "content": "create a task called Wiring"},
        {"role": "assistant", "content": 'Created task "Wiring".'},
        {"role": "user", "content": "show my tasks"},
    ]

    calls = []

    def fake_complete(system, messages, **kwargs):
        prompt = messages[0]["content"]
        calls.append(prompt)
        if "create a task called Wiring" in prompt:
            return _planner_json("create_task", {"title": "Wiring", "project_name": "BAJA HV"})
        return _planner_json("list_tasks", {})

    with patch.object(ai_service, "complete_text", side_effect=fake_complete):
        with patch.object(
            ai_service, "execute_tool", side_effect=[{"data": task}, {"data": []}]
        ) as mock_exec:
            reply1 = chat_with_ai(turn1, db_session)
            reply2 = chat_with_ai(turn2, db_session)

    assert "created" in reply1.lower()
    assert "no tasks found" in reply2.lower() or "tasks:" in reply2.lower()
    assert mock_exec.call_count == 2
    assert mock_exec.call_args_list[0].args[0] == "create_task"
    assert mock_exec.call_args_list[1].args[0] == "list_tasks"
    # The planner only ever saw the latest user turn of each request.
    assert "create a task called Wiring" in calls[0]
    assert "show my tasks" in calls[1]
    assert "show my tasks" not in calls[0]