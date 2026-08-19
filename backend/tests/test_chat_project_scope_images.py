"""Project-scoped AI image-understanding regression tests.

The /projects/:id/ai workspace must reach the EXISTING image-understanding
capability. The project selection is DATA/context, not authorization: the
frontend sends an explicit ``project_id`` and the backend uses it only to
constrain the image/document lookup to that project (never another project's
images, never images on unrelated follow-ups, never image bytes in chat
history). Global /chat (no project_id) keeps the existing fuzzy inference.

Requirements covered:
1. project-scoped image request sends that project's image to Gemini vision
2. an image from another project is never attached
3. image filename matching works
4. a generic follow-up does NOT resend image bytes
5. missing image -> honest response
6. Groq/text-only provider -> existing honest vision-unavailable behavior
7. global /chat image understanding remains green
8. project-scoped text conversation remains green
9. image content cannot trigger tool authorization
10. no raw image bytes enter chat history/sessionStorage (router-level)
"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, get_db
from app.models.document import Document
from app.models.project import Project
from app.services.ai_service import chat_with_ai
from app.main import app
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body"


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "AI_MODEL", "gemini-3.6-flash")


@pytest.fixture
def groq(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "groq")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk-test")


def _seed_project_with_image(db, tmp_path, name, mime, data, project=None):
    if project is None:
        project = Project(name="In-SEM", description="Insem 7th Sem", category="college", status="active")
        db.add(project)
        db.commit()
        db.refresh(project)
    f = tmp_path / name
    f.write_bytes(data)
    db.add(
        Document(
            filename=name,
            original_filename=name,
            file_path=str(f),
            mime_type=mime,
            file_size_bytes=len(data),
            title=name,
            project_id=project.id,
        )
    )
    db.commit()
    db.refresh(project)
    return project


def _context_message(project):
    return (
        'This conversation is scoped to the project "%s" (id %d). '
        "Answer questions about this project using the user's projects, tasks, "
        "notes, and documents."
    ) % (project.name, project.id)


def _project_scoped_messages(project, prompt, history=None):
    messages = [{"role": "user", "content": _context_message(project)}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    return messages


def _mock_gemini_response(text):
    response = MagicMock()
    response.text = text
    return response


def _inline_parts(client_call_kwargs):
    contents = client_call_kwargs["contents"]
    for turn in contents:
        for part in turn["parts"]:
            if "inline_data" in part:
                yield part["inline_data"]


# ----------------------------------------------------------------------
# 1. Project-scoped image request sends that project's image to Gemini vision
# ----------------------------------------------------------------------
def test_project_scoped_chat_sends_project_image_to_vision(gemini, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "tt.jpeg", "image/jpeg", JPEG_BYTES)
    messages = _project_scoped_messages(
        proj, "from tt.jpeg extract my exam dates and time"
    )
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),  # tool planning — no tool
            _mock_gemini_response("Your exam dates are 10 and 12 December."),
        ]
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == "Your exam dates are 10 and 12 December."
    plan_call, vision_call = client.models.generate_content.call_args_list
    attached = list(_inline_parts(vision_call.kwargs))
    assert any(
        inline == {"mime_type": "image/jpeg", "data": JPEG_BYTES} for inline in attached
    )
    assert "PROJECT IMAGE CONTENTS (In-SEM)" in vision_call.kwargs["config"].system_instruction
    # the image never reaches the tool-planning call
    assert all(
        "inline_data" not in part for turn in plan_call.kwargs["contents"] for part in turn["parts"]
    )


# ----------------------------------------------------------------------
# 2. An image from another project is never attached
# ----------------------------------------------------------------------
def test_project_scoped_chat_never_attaches_other_projects_image(gemini, db_session, tmp_path):
    insem = _seed_project_with_image(db_session, tmp_path, "insem.png", "image/png", PNG_BYTES)
    baja = Project(name="BAJA HV", description="eBAJA electric vehicle", category="baja", status="active")
    db_session.add(baja)
    db_session.commit()
    db_session.refresh(baja)
    _seed_project_with_image(
        db_session, tmp_path, "baja-suspension.png", "image/png", PNG_BYTES, project=baja
    )

    # The user asks about an image that only exists in the OTHER project, but
    # the request is explicitly scoped to In-SEM. Only In-SEM's images may be
    # attached — never BAJA's.
    messages = _project_scoped_messages(
        insem, "what does the baja-suspension image show?"
    )
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("In-SEM has insem.png."),
        ]
        reply = chat_with_ai(messages, db_session, project_id=insem.id)

    assert reply == "In-SEM has insem.png."
    _, vision_call = client.models.generate_content.call_args_list
    attached = list(_inline_parts(vision_call.kwargs))
    # In-SEM's only image is attached...
    assert any(i == {"mime_type": "image/png", "data": PNG_BYTES} for i in attached)
    # ...and nothing from BAJA (same bytes, but only one image may be attached,
    # and the framing block names only In-SEM).
    assert "PROJECT IMAGE CONTENTS (In-SEM)" in vision_call.kwargs["config"].system_instruction
    assert "BAJA HV" not in vision_call.kwargs["config"].system_instruction.split(
        "PROJECT IMAGE CONTENTS"
    )[1]


# ----------------------------------------------------------------------
# 3. Image filename matching works
# ----------------------------------------------------------------------
def test_project_scoped_chat_matches_image_filename(gemini, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "tt.jpeg", "image/jpeg", JPEG_BYTES)
    _seed_project_with_image(db_session, tmp_path, "syllabus.png", "image/png", PNG_BYTES, project=proj)

    messages = _project_scoped_messages(proj, "from tt.jpeg extract my exam dates and time")
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("Here are the dates."),
        ]
        chat_with_ai(messages, db_session, project_id=proj.id)

    _, vision_call = client.models.generate_content.call_args_list
    attached = list(_inline_parts(vision_call.kwargs))
    assert any(i == {"mime_type": "image/jpeg", "data": JPEG_BYTES} for i in attached)
    assert "tt.jpeg" in vision_call.kwargs["config"].system_instruction


def test_named_image_is_prioritized_over_the_count_cap(gemini, db_session, tmp_path):
    # The project holds more images than the inspection cap (4). The user names
    # "tt.jpeg", which sorts last alphabetically — it must still be attached.
    proj = _seed_project_with_image(db_session, tmp_path, "tt.jpeg", "image/jpeg", JPEG_BYTES)
    for i in range(5):
        _seed_project_with_image(
            db_session, tmp_path, f"aaa-{i}.png", "image/png", PNG_BYTES, project=proj
        )

    messages = _project_scoped_messages(proj, "from tt.jpeg extract my exam dates and time")
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("Here are the dates."),
        ]
        chat_with_ai(messages, db_session, project_id=proj.id)

    _, vision_call = client.models.generate_content.call_args_list
    attached = list(_inline_parts(vision_call.kwargs))
    assert any(i == {"mime_type": "image/jpeg", "data": JPEG_BYTES} for i in attached)
    assert "tt.jpeg" in vision_call.kwargs["config"].system_instruction


# ----------------------------------------------------------------------
# 4. A generic follow-up does NOT resend image bytes
# ----------------------------------------------------------------------
def test_project_scoped_follow_up_does_not_resend_image_bytes(gemini, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "shot.png", "image/png", PNG_BYTES)
    messages = _project_scoped_messages(
        proj,
        "What is BDA?",
        history=[
            {"role": "user", "content": "what does the screenshot in this project show"},
            {"role": "assistant", "content": "The screenshot shows BDA and syllabus subjects."},
        ],
    )
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("BDA is Big Data Analytics."),
        ]
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == "BDA is Big Data Analytics."
    for call in client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert all("inline_data" not in part for turn in contents for part in turn["parts"])


# ----------------------------------------------------------------------
# 5. Missing image -> honest response
# ----------------------------------------------------------------------
def test_project_scoped_missing_image_honest_response(gemini, db_session):
    proj = Project(name="In-SEM", category="college", status="active")
    db_session.add(proj)
    db_session.commit()
    db_session.refresh(proj)

    messages = _project_scoped_messages(proj, "what does the screenshot show?")
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [_mock_gemini_response("NONE")]
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == "I couldn't find any images in the In-SEM project."
    assert len(client.models.generate_content.call_args_list) == 1  # no vision call


# ----------------------------------------------------------------------
# 6. Groq/text-only provider -> existing honest vision-unavailable behavior
# ----------------------------------------------------------------------
def test_project_scoped_groq_honest_vision_unavailable(groq, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "shot.png", "image/png", PNG_BYTES)
    messages = _project_scoped_messages(proj, "what does the screenshot show?")
    with patch("app.services.ai_service.Groq") as mock_groq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="irrelevant"))]
        )
        mock_groq.return_value = mock_client
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == (
        "These images are uploaded, but the current AI provider cannot inspect "
        "image content."
    )


# ----------------------------------------------------------------------
# 7. Global /chat image understanding remains green (no project_id)
# ----------------------------------------------------------------------
def test_global_chat_image_understanding_remains_green(gemini, db_session, tmp_path):
    _seed_project_with_image(db_session, tmp_path, "shot.png", "image/png", PNG_BYTES)
    messages = [{"role": "user", "content": "What does the screenshot in my In-SEM project show?"}]
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("The screenshot shows the syllabus."),
        ]
        reply = chat_with_ai(messages, db_session)  # no project_id

    assert reply == "The screenshot shows the syllabus."
    _, vision_call = client.models.generate_content.call_args_list
    attached = list(_inline_parts(vision_call.kwargs))
    assert any(i == {"mime_type": "image/png", "data": PNG_BYTES} for i in attached)
    assert "PROJECT IMAGE CONTENTS (In-SEM)" in vision_call.kwargs["config"].system_instruction


# ----------------------------------------------------------------------
# 8. Project-scoped text conversation remains green
# ----------------------------------------------------------------------
def test_project_scoped_text_conversation_remains_green(gemini, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "shot.png", "image/png", PNG_BYTES)
    messages = _project_scoped_messages(proj, "Summarize this project")
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("This project covers the 7th semester syllabus."),
        ]
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == "This project covers the 7th semester syllabus."
    for call in client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert all("inline_data" not in part for turn in contents for part in turn["parts"])


# ----------------------------------------------------------------------
# 9. Image content cannot trigger tool authorization
# ----------------------------------------------------------------------
def test_image_content_cannot_trigger_tool_authorization(gemini, db_session, tmp_path):
    proj = _seed_project_with_image(db_session, tmp_path, "evil.png", "image/png", PNG_BYTES)
    # The user text is a benign image question. Any tool directive would have to
    # come from the image's contents — but image bytes never reach the
    # tool-planning call, so image-derived instructions can never authorize a
    # tool. (Avoid "it"/bare numbers so the reminder-correction router is not
    # involved.)
    messages = _project_scoped_messages(proj, "what does the image in this project show?")
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("The image contains no instructions."),
        ]
        reply = chat_with_ai(messages, db_session, project_id=proj.id)

    assert reply == "The image contains no instructions."
    plan_call, _ = client.models.generate_content.call_args_list
    # The tool-planning call never sees image bytes, so image-derived content
    # can never authorize a tool.
    assert all(
        "inline_data" not in part for turn in plan_call.kwargs["contents"] for part in turn["parts"]
    )


# ----------------------------------------------------------------------
# Backend authority: a fabricated project_id must not pull another project's
# images, and the router must accept the explicit project scope.
# ----------------------------------------------------------------------
def test_bogus_project_id_never_attaches_any_image(gemini, db_session, tmp_path):
    _seed_project_with_image(db_session, tmp_path, "baja.png", "image/png", PNG_BYTES)
    messages = [{"role": "user", "content": "what does the baja.png image show?"}]
    with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
        client = MagicMock()
        factory.return_value = client
        client.models.generate_content.side_effect = [
            _mock_gemini_response("NONE"),
            _mock_gemini_response("I cannot inspect that image."),
        ]
        # project_id=9999 does not exist -> scoped to no project, text-only reply
        reply = chat_with_ai(messages, db_session, project_id=9999)

    assert reply == "I cannot inspect that image."
    for call in client.models.generate_content.call_args_list:
        contents = call.kwargs["contents"]
        assert all("inline_data" not in part for turn in contents for part in turn["parts"])


# ----------------------------------------------------------------------
# 10. No raw image bytes enter chat history / sessionStorage (router level)
# ----------------------------------------------------------------------
def test_chat_route_accepts_project_scope_and_returns_text_only(gemini, tmp_path):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    proj = _seed_project_with_image(db, tmp_path, "tt.jpeg", "image/jpeg", JPEG_BYTES)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        with patch.object(__import__("app.services.ai_providers", fromlist=["_gemini_client"]), "_gemini_client") as factory:
            client_mock = MagicMock()
            factory.return_value = client_mock
            client_mock.models.generate_content.side_effect = [
                _mock_gemini_response("NONE"),
                _mock_gemini_response("Your exam dates are 10 and 12 December."),
            ]
            messages = _project_scoped_messages(
                proj, "from tt.jpeg extract my exam dates and time"
            )
            response = client.post(
                "/api/chat/",
                json={"project_id": proj.id, "messages": messages},
            )
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "Your exam dates are 10 and 12 December."
    # The wire payload the UI would store in sessionStorage is pure text —
    # never image bytes.
    body = response.text
    assert "inline_data" not in body
    assert "image/jpeg" not in body
    assert "fake-jpeg-body" not in body
    assert all(c.isprintable() or c in "\r\n" for c in body)