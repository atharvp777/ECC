from app.services import google_calendar


def test_legacy_token_is_migrated_to_canonical_location(tmp_path, monkeypatch):
    canonical = tmp_path / "knowledge" / "google_token.json"
    legacy = tmp_path / "legacy" / "google_token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"token": "abc"}')

    monkeypatch.setattr(google_calendar, "TOKEN_FILE", canonical)
    monkeypatch.setattr(google_calendar, "_LEGACY_TOKEN_PATHS", [legacy])

    google_calendar._migrate_legacy_token()

    assert canonical.exists()
    assert canonical.read_text() == '{"token": "abc"}'
    assert not legacy.exists()


def test_no_migration_when_canonical_token_already_exists(tmp_path, monkeypatch):
    canonical = tmp_path / "knowledge" / "google_token.json"
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"token": "canonical"}')
    legacy = tmp_path / "legacy" / "google_token.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"token": "legacy"}')

    monkeypatch.setattr(google_calendar, "TOKEN_FILE", canonical)
    monkeypatch.setattr(google_calendar, "_LEGACY_TOKEN_PATHS", [legacy])

    google_calendar._migrate_legacy_token()

    assert canonical.read_text() == '{"token": "canonical"}'
    assert legacy.exists()