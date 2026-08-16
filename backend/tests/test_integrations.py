import pytest
from unittest.mock import patch
import json

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import google_calendar


@pytest.fixture
def client():
    return TestClient(app)


def _disconnect(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_PAT", "")


def _connect(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_PAT", "ghp_fake")


# ----------------------------------------------------------------------
# Disconnected state: no GitHub API calls, no 500s
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "url, key",
    [
        ("/integrations/github/issues?repo=owner/repo", "issues"),
        ("/integrations/github/prs?repo=owner/repo", "prs"),
        ("/integrations/github/commits?repo=owner/repo", "commits"),
    ],
)
def test_github_get_endpoints_disconnected(client, monkeypatch, url, key):
    _disconnect(monkeypatch)

    response = client.get(url)

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"connected": False, key: []}


def test_github_push_task_disconnected(client, monkeypatch):
    _disconnect(monkeypatch)

    response = client.post(
        "/integrations/github/push-task",
        json={"repo": "owner/repo", "title": "Task", "body": "body"},
    )

    assert response.status_code == 400
    assert "not connected" in response.json()["detail"]


def test_github_disconnected_never_calls_api(client, monkeypatch):
    """The GitHub API must not be invoked when disconnected."""
    _disconnect(monkeypatch)

    with patch("app.services.github_service.get_open_issues") as mock_issues:
        client.get("/integrations/github/issues?repo=owner/repo")
        mock_issues.assert_not_called()

    with patch("app.services.github_service.create_issue_from_task") as mock_create:
        client.post(
            "/integrations/github/push-task",
            json={"repo": "owner/repo", "title": "Task", "body": "body"},
        )
        mock_create.assert_not_called()


def test_github_repos_disconnected_matches_existing_format(client, monkeypatch):
    """/repos keeps its established not-connected shape."""
    _disconnect(monkeypatch)

    response = client.get("/integrations/github/repos")

    assert response.status_code == 200
    assert response.json() == {"connected": False, "repos": []}


# ----------------------------------------------------------------------
# Connected state: successful behavior preserved (service mocked)
# ----------------------------------------------------------------------
def test_github_issues_connected_preserves_list(client, monkeypatch):
    _connect(monkeypatch)

    fake_issues = [{"number": 1, "title": "Bug", "state": "open"}]
    with patch("app.services.github_service.get_open_issues", return_value=fake_issues):
        response = client.get("/integrations/github/issues?repo=owner/repo")

    assert response.status_code == 200
    assert response.json() == fake_issues


def test_github_push_task_connected_preserves_issue(client, monkeypatch):
    _connect(monkeypatch)

    fake_issue = {"number": 42, "title": "Task", "url": "https://github.com/o/r/issues/42"}
    with patch("app.services.github_service.create_issue_from_task", return_value=fake_issue):
        response = client.post(
            "/integrations/github/push-task",
            json={"repo": "owner/repo", "title": "Task", "body": "body", "labels": ["ecc-task"]},
        )

    assert response.status_code == 200
    assert response.json() == fake_issue


# ----------------------------------------------------------------------
# Google Calendar status: connected vs can_write
# ----------------------------------------------------------------------
def _token_json(scopes):
    return json.dumps({
        "token": "t", "refresh_token": "rt", "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "cid", "client_secret": "cs", "scopes": scopes,
    })


def test_status_readonly_token_connected_but_cannot_write(client, monkeypatch, tmp_path):
    token_file = tmp_path / "google_token.json"
    token_file.write_text(_token_json(["https://www.googleapis.com/auth/calendar.readonly"]))
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", token_file)

    response = client.get("/integrations/status")
    payload = response.json()

    assert payload["google_calendar"] is True
    assert payload["google_calendar_connected"] is True
    assert payload["google_calendar_can_write"] is False


def test_status_write_token_connected_and_can_write(client, monkeypatch, tmp_path):
    token_file = tmp_path / "google_token.json"
    token_file.write_text(_token_json(["https://www.googleapis.com/auth/calendar.events"]))
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", token_file)

    response = client.get("/integrations/status")
    payload = response.json()

    assert payload["google_calendar_connected"] is True
    assert payload["google_calendar_can_write"] is True


def test_status_disconnected_keeps_legacy_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", tmp_path / "missing.json")

    response = client.get("/integrations/status")
    payload = response.json()

    assert payload["google_calendar"] is False
    assert payload["google_calendar_connected"] is False
    assert payload["google_calendar_can_write"] is False
    assert "github" in payload