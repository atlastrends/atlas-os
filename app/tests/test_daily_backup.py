import importlib.util
import sqlite3
from pathlib import Path


MODULE_PATH = Path(__file__).parents[2] / "scripts" / "atlas_daily_backup.py"
SPEC = importlib.util.spec_from_file_location("atlas_daily_backup", MODULE_PATH)
backup = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backup)


def test_redact_text_removes_credentials_and_personal_data():
    content = (
        "email=test@example.com phone=+55 43 99999-0000 "
        "access_token=secret-value-with-more-than-sixteen-chars "
        "url=https://example.com/?access_token=private&campaign=safe"
    )

    redacted = backup.redact_text(content)

    assert "test@example.com" not in redacted
    assert "99999-0000" not in redacted
    assert "secret-value" not in redacted
    assert "access_token=private" not in redacted
    assert "campaign=safe" in redacted


def test_sanitized_sqlite_backup_clears_tokens(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with sqlite3.connect(source) as db:
        db.execute(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "access_token TEXT NOT NULL, notes TEXT)"
        )
        db.execute(
            "INSERT INTO accounts VALUES (1, 'Atlas', 'private-token', "
            "'contact test@example.com')"
        )
        db.commit()

    result = backup.sanitized_sqlite_backup(source, destination)

    with sqlite3.connect(destination) as db:
        row = db.execute(
            "SELECT name, access_token, notes FROM accounts"
        ).fetchone()
    assert result["created"] is True
    assert row == ("Atlas", "", "contact [REDACTED_EMAIL]")
