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
from typing import Optional, List, Dict, Any

from app.core.config import settings

# Import the Google API client library function used to build the service.
# This import is required for type checking and to avoid the F821 undefined‑name error.
from googleapiclient.discovery import build

TOKEN_FILE = settings.KNOWLEDGE_DIR / "google_token.json"
OAUTH_STATE_FILE = settings.KNOWLEDGE_DIR / "google_oauth_state.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]  # writable scope

# Scopes that grant write access to calendar events. calendar.readonly is
# deliberately NOT included.
WRITE_SCOPES = {
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
}

# Message shown when the stored token can read but cannot write events.
WRITE_SCOPE_ERROR_MESSAGE = (
    "Google Calendar is connected, but write access isn't authorized. "
    "Please reconnect Google Calendar to grant calendar write access."
)

# Locations where tokens were stored by older versions of the app.
_LEGACY_TOKEN_PATHS = [
    Path(__file__).resolve().parents[2] / "knowledge" / "google_token.json",
]


def _migrate_legacy_token() -> None:
    """Preserve an existing Google token that lives in a legacy location.

    The canonical location is settings.KNOWLEDGE_DIR/google_token.json.
    If a token exists only in an older path, move it there once so OAuth,
    runtime and reads all agree on a single token file.
    """
    if TOKEN_FILE.exists():
        return
    for legacy in _LEGACY_TOKEN_PATHS:
        try:
            if legacy.exists():
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                legacy.replace(TOKEN_FILE)
                return
        except OSError:
            pass


_migrate_legacy_token()


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

    # Ensure the state file exists
    if not OAUTH_STATE_FILE.exists():
        raise ValueError("Google OAuth state file not found")

    # Load stored state and verifier
    try:
        oauth_state = json.loads(OAUTH_STATE_FILE.read_text())
    except json.JSONDecodeError:
        OAUTH_STATE_FILE.unlink(missing_ok=True)
        raise ValueError("Corrupted OAuth state file")

    saved_state = oauth_state.get("state")
    saved_verifier = oauth_state.get("code_verifier")

    # Validate state matches what we expect
    if saved_state != state:
        # Clean up any stale state file to avoid repeated mismatches
        OAUTH_STATE_FILE.unlink(missing_ok=True)
        raise ValueError("State mismatch – possible replay attack or stale session")
    if not saved_verifier:
        OAUTH_STATE_FILE.unlink(missing_ok=True)
        raise ValueError("Missing code verifier in stored state")

    # Build the flow again so we can set the verifier
    flow = _get_flow()
    # Restore the exact PKCE verifier that was generated for this authorization attempt.
    flow.code_verifier = saved_verifier

    # Exchange the authorization code for tokens.
    try:
        flow.fetch_token(
            code=code,
            code_verifier=saved_verifier,
        )
    except Exception as exc:
        # Clean up state file on any failure
        OAUTH_STATE_FILE.unlink(missing_ok=True)
        raise exc

    # Persist the credentials (including refreshed token if applicable).
    creds = flow.credentials
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


def get_upcoming_events(days: int = 14, max_results: int = 20) -> List[dict]:
    """Step 3 — fetch upcoming events from primary calendar."""
    creds = _load_credentials()
    if not creds:
        return []

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


# ----------------------------------------------------------------------
# Write-scope detection
# ----------------------------------------------------------------------
def _token_scopes() -> Optional[List[str]]:
    """Return the scopes stored with the saved token, or None if unavailable."""
    if not TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(TOKEN_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    scopes = data.get("scopes")
    if scopes is None:
        return None
    if isinstance(scopes, str):
        return [scopes]
    if isinstance(scopes, list):
        return [s for s in scopes if isinstance(s, str)]
    return None


def has_write_scope() -> bool:
    """Return True only when the stored token includes a writable Calendar scope.

    A token scoped to calendar.readonly (or a missing/unknown scope) is treated
    as read-only — reads work, writes must be refused.
    """
    scopes = _token_scopes()
    if not scopes:
        return False
    normalized = {s.rstrip("/") for s in scopes}
    return bool(normalized.intersection(WRITE_SCOPES))


def _require_write_access() -> None:
    """Raise PermissionError when calendar writes are not possible.

    Called before any write request so we never call Google with a token that is
    known to be read-only.
    """
    if not is_connected():
        raise PermissionError(
            "Google Calendar isn't connected. Connect it before creating calendar events."
        )
    if not has_write_scope():
        raise PermissionError(WRITE_SCOPE_ERROR_MESSAGE)


# ----------------------------------------------------------------------
# Write operations (create / update / delete)
# ----------------------------------------------------------------------
def _get_service():
    """Return an authenticated Google Calendar service instance."""
    creds = _load_credentials()
    if not creds:
        raise PermissionError("Google Calendar not connected – please re‑authorize.")
    return build("calendar", "v3", credentials=creds)


def create_calendar_event(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new event. Returns the created event representation."""
    _require_write_access()
    service = _get_service()
    try:
        created = service.events().insert(calendarId="primary", body=event_data).execute()
        return {
            "id": created.get("id"),
            "summary": created.get("summary"),
            "start": created.get("start"),
            "end": created.get("end"),
            "status": created.get("status"),
        }
    except Exception as exc:
        # If the error is due to insufficient scope, surface a clear message.
        if "insufficient" in str(exc).lower():
            raise PermissionError(
                "Calendar write access not granted. Please re‑authorize with full Calendar scope."
            ) from exc
        raise exc


def update_calendar_event(event_id: str, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing event. Returns the updated event representation."""
    _require_write_access()
    service = _get_service()
    try:
        updated = service.events().update(
            calendarId="primary", eventId=event_id, body=event_data
        ).execute()
        return {
            "id": updated.get("id"),
            "summary": updated.get("summary"),
            "start": updated.get("start"),
            "end": updated.get("end"),
            "status": updated.get("status"),
        }
    except Exception as exc:
        if "insufficient" in str(exc).lower():
            raise PermissionError(
                "Calendar write access not granted. Please re‑authorize with full Calendar scope."
            ) from exc
        raise exc


def delete_calendar_event(event_id: str) -> Dict[str, str]:
    """Delete an existing event. Returns a confirmation message."""
    _require_write_access()
    service = _get_service()
    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"status": "deleted", "event_id": event_id}
    except Exception as exc:
        if "insufficient" in str(exc).lower():
            raise PermissionError(
                "Calendar write access not granted. Please re‑authorize with full Calendar scope."
            ) from exc
        raise exc
