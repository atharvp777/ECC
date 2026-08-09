"""
Google Calendar integration.

OAuth2 flow:
  1. GET /integrations/google/auth      → redirect user to Google consent screen
  2. GET /integrations/google/callback  → exchange code for tokens, save to disk
  3. GET /integrations/google/events    → fetch upcoming events using saved tokens
"""

import json
import secrets
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.core.config import settings

TOKEN_FILE = settings.KNOWLEDGE_DIR / "google_token.json"
OAUTH_STATE_FILE = settings.KNOWLEDGE_DIR / "google_oauth_state.json"
SCOPES     = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_flow():
    from google_auth_oauthlib.flow import Flow
    client_config = {
        "web": {
            "client_id":     settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }
    return Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
    )


def get_auth_url() -> str:
    """Generate Google OAuth2 consent URL and preserve PKCE verifier."""

    if not settings.GOOGLE_CLIENT_ID:
        raise ValueError("GOOGLE_CLIENT_ID not configured in .env")

    flow = _get_flow()

    # Generate and preserve the PKCE verifier.
    flow.code_verifier = secrets.token_urlsafe(64)

    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Save the verifier (and the generated state) so the callback can use the same one.
    OAUTH_STATE_FILE.write_text(
        json.dumps({
            "state": state,
            "code_verifier": flow.code_verifier,
        })
    )

    return url


def handle_callback(code: str, state: str) -> bool:
    """Exchange Google OAuth code for tokens and save them."""

    if not OAUTH_STATE_FILE.exists():
        raise ValueError("Google OAuth state file not found")

    oauth_state = json.loads(OAUTH_STATE_FILE.read_text())
    saved_state = oauth_state.get("state")
    saved_verifier = oauth_state.get("code_verifier")

    # Validate that the state returned by Google matches the one we stored.
    if saved_state != state:
        # Clean up any stale state file to avoid repeated mismatches.
        OAUTH_STATE_FILE.unlink(missing_ok=True)
        raise ValueError("State mismatch – possible replay attack or stale session")

    flow = _get_flow()
    # Restore the exact PKCE verifier that was generated for this authorization attempt.
    flow.code_verifier = saved_verifier

    # Exchange the authorization code for tokens.
    flow.fetch_token(
        code=code,
        code_verifier=saved_verifier,
    )

    creds = flow.credentials

    # Persist the credentials (including refreshed token if applicable).
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    TOKEN_FILE.write_text(json.dumps(data))

    # Remove the state file – it is no longer needed.
    OAUTH_STATE_FILE.unlink(missing_ok=True)

    return True


def _load_credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_FILE.exists():
        return None

    data  = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(
        token=data["token"],
        refresh_token=data.get("refresh_token"),
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token
        data["token"] = creds.token
        TOKEN_FILE.write_text(json.dumps(data))

    return creds


def get_upcoming_events(days: int = 14, max_results: int = 20) -> list[dict]:
    """Step 3 — fetch upcoming events from primary calendar."""
    creds = _load_credentials()
    if not creds:
        return []

    from googleapiclient.discovery import build

    service  = build("calendar", "v3", credentials=creds)
    now      = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days)

    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=time_max.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = []
    for e in result.get("items", []):
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        end   = e["end"].get("dateTime",   e["end"].get("date",   ""))
        events.append({
            "id":          e.get("id"),
            "title":       e.get("summary", "(no title)"),
            "start":       start,
            "end":         end,
            "location":    e.get("location"),
            "description": e.get("description"),
            "html_link":   e.get("htmlLink"),
            "all_day":     "T" not in e["start"].get("dateTime", "T"),
        })
    return events


def is_connected() -> bool:
    return TOKEN_FILE.exists()
