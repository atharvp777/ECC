from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/integrations", tags=["integrations"])


# ══════════════════════════════════════════════════════════
# STATUS
# ═════════════════════════════════════════════════════════

@router.get("/status")
def integrations_status():
    """Which integrations are currently connected."""
    from app.services.google_calendar import is_connected as gcal_connected
    from app.services.google_calendar import has_write_scope as gcal_can_write
    from app.services.github_service  import is_connected as gh_connected
    gcal_ok = gcal_connected()
    return {
        "google_calendar":            gcal_ok,
        "google_calendar_connected":  gcal_ok,
        "google_calendar_can_write":  gcal_ok and gcal_can_write(),
        "github":                     gh_connected(),
    }


# ═════════════════════════════════════════════════════════
# GOOGLE CALENDAR
# ══════════════════════════════════════════════════════════

@router.get("/google/auth")
def google_auth():
    """Redirect user to Google OAuth2 consent screen."""
    from app.services.google_calendar import get_auth_url
    try:
        url = get_auth_url()
        return RedirectResponse(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/google/callback")
def google_callback(
    code: str = Query(...),
    state: str = Query(...)
):
    """Handle the Google OAuth2 callback and store tokens."""
    from app.services.google_calendar import handle_callback

    try:
        handle_callback(code, state)
        return RedirectResponse("http://localhost:1420/#/integrations?google=connected")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {e}")


@router.get("/google/events")
def google_events(days: int = Query(14), max_results: int = Query(20)):
    """Fetch upcoming Google Calendar events."""
    from app.services.google_calendar import get_upcoming_events, is_connected
    if not is_connected():
        return {"connected": False, "events": []}
    try:
        events = get_upcoming_events(days=days, max_results=max_results)
        return {"connected": True, "events": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/google/disconnect")
def google_disconnect():
    """Remove saved Google tokens."""
    from app.services.google_calendar import TOKEN_FILE
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    return {"status": "disconnected"}


# ══════════════════════════════════════════════════════════
# GITHUB
# ══════════════════════════════════════════════════════════

@router.get("/github/repos")
def github_repos(limit: int = Query(30)):
    from app.services.github_service import get_user_repos, is_connected
    if not is_connected():
        return {"connected": False, "repos": []}
    try:
        return {"connected": True, "repos": get_user_repos(limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/issues")
def github_issues(repo: str = Query(...), limit: int = Query(20)):
    from app.services.github_service import get_open_issues, is_connected
    if not is_connected():
        return {"connected": False, "issues": []}
    try:
        return get_open_issues(repo, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/prs")
def github_prs(repo: str = Query(...), limit: int = Query(20)):
    from app.services.github_service import get_open_prs, is_connected
    if not is_connected():
        return {"connected": False, "prs": []}
    try:
        return get_open_prs(repo, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/github/commits")
def github_commits(repo: str = Query(...), limit: int = Query(15)):
    from app.services.github_service import get_recent_commits, is_connected
    if not is_connected():
        return {"connected": False, "commits": []}
    try:
        return get_recent_commits(repo, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PushTaskRequest(BaseModel):
    repo: str          # e.g. "atharv/ebaja-code"
    title: str
    body: str
    labels: Optional[list[str]] = ["ecc-task"]


@router.post("/github/push-task")
def push_task_to_github(payload: PushTaskRequest):
    """Create a GitHub issue from a task."""
    from app.services.github_service import create_issue_from_task, is_connected
    if not is_connected():
        raise HTTPException(
            status_code=400,
            detail="GitHub is not connected. Add GITHUB_PAT to backend/.env and restart the backend.",
        )
    try:
        issue = create_issue_from_task(
            repo_full_name=payload.repo,
            title=payload.title,
            body=payload.body,
            labels=payload.labels,
        )
        return issue
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
