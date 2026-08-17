import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services import google_calendar


@pytest.fixture
def client():
    return TestClient(app)


# ----------------------------------------------------------------------
# GitHub integration was removed: no endpoints, no settings, no status key
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "/integrations/github/repos",
        "/integrations/github/issues?repo=owner/repo",
        "/integrations/github/prs?repo=owner/repo",
        "/integrations/github/commits?repo=owner/repo",
    ],
)
def test_github_endpoints_do_not_exist(client, url):
    response = client.get(url)
    assert response.status_code == 404


def test_github_push_task_endpoint_does_not_exist(client):
    response = client.post(
        "/integrations/github/push-task",
        json={"repo": "owner/repo", "title": "Task", "body": "body"},
    )
    assert response.status_code == 404


def test_github_settings_removed():
    assert not hasattr(settings, "GITHUB_PAT")
    assert not hasattr(settings, "GITHUB_USERNAME")


def test_status_has_no_github_key(client, monkeypatch, tmp_path):
    monkeypatch.setattr(google_calendar, "TOKEN_FILE", tmp_path / "missing.json")

    response = client.get("/integrations/status")
    payload = response.json()

    assert payload["google_calendar"] is False
    assert payload["google_calendar_connected"] is False
    assert payload["google_calendar_can_write"] is False
    assert "github" not in payload


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