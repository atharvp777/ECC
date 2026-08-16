import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings


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