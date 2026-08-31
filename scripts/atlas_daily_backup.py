from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SENSITIVE_COLUMN = re.compile(
    r"(token|secret|password|credential|api.?key|private.?key|card|phone|email|address)",
    re.IGNORECASE,
)
TOKEN_PATTERNS = (
    re.compile(r"\b(?:sk|gh[pousr])[-_][A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\brft\.[A-Za-z0-9_!.-]{16,}\b"),
    re.compile(r"\bEA[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-=]{16,}\b", re.IGNORECASE),
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?9?\d{4}[\s.-]?\d{4}(?!\d)")
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]?){13,19}(?!\d)")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![?&])\b(password|secret|(?:access|refresh)[_-]?token|token|api[_-]?key|"
    r"client[_-]?secret|private[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;\"']+|[\"'][^\"']*[\"'])"
)
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "code",
    "password",
    "api_key",
    "key",
}
ARTIFACT_DIRS = (
    "storage",
    "output_videos",
    "output_metadata",
    "stories",
    "ebooks",
    "app/assets",
)


def run(command: list[str], cwd: Path, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def redact_urls(text: str) -> str:
    url_pattern = re.compile(r"https?://[^\s<>\"']+")

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing = ""
        while raw and raw[-1] in ".,);]":
            trailing = raw[-1] + trailing
            raw = raw[:-1]
        try:
            parts = urlsplit(raw)
            query = [
                (key, "[REDACTED]" if key.lower() in SENSITIVE_QUERY_KEYS else value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
            ]
            return urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
            ) + trailing
        except ValueError:
            return "[REDACTED_URL]" + trailing

    return url_pattern.sub(replace, text)


def redact_text(value: str) -> str:
    text = str(value)
    text = redact_urls(text)
    text = SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    for pattern in TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED_TOKEN]", text)
    text = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
    text = PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    text = CARD_PATTERN.sub("[REDACTED_CARD]", text)
    username = re.escape(os.environ.get("USERNAME", ""))
    if username:
        text = re.sub(
            rf"(?i)C:\\Users\\{username}",
            "%USERPROFILE%",
            text,
        )
    return text


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def newest_session_log() -> Path | None:
    home = Path(os.environ.get("XDG_STATE_HOME") or Path.home())
    candidates = list((home / ".copilot" / "session-state").glob("*/events.jsonl"))
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def archive_session(log_path: Path | None, destination: Path, date_key: str) -> dict:
    prompt_path = destination / "prompts.sanitized.jsonl"
    assistant_path = destination / "assistant.sanitized.jsonl"
    prompt_count = 0
    assistant_count = 0
    if log_path is None or not log_path.is_file():
        prompt_path.write_text("", encoding="utf-8")
        assistant_path.write_text("", encoding="utf-8")
        return {"source": None, "prompts": 0, "assistant_messages": 0}

    with (
        log_path.open("r", encoding="utf-8", errors="replace") as source,
        prompt_path.open("w", encoding="utf-8") as prompts,
        assistant_path.open("w", encoding="utf-8") as assistants,
    ):
        for line in source:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = event.get("timestamp")
            if timestamp:
                try:
                    local_date = datetime.fromisoformat(
                        timestamp.replace("Z", "+00:00")
                    ).astimezone().date().isoformat()
                    if local_date != date_key:
                        continue
                except ValueError:
                    continue
            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "user.message":
                content = redact_text(data.get("content") or "")
                prompts.write(
                    json.dumps(
                        {"timestamp": timestamp, "role": "user", "content": content},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                prompt_count += 1
            elif event_type == "assistant.message" and not data.get("parentToolCallId"):
                content = redact_text(data.get("content") or "")
                assistants.write(
                    json.dumps(
                        {"timestamp": timestamp, "role": "assistant", "content": content},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                assistant_count += 1
    return {
        "source": str(log_path),
        "prompts": prompt_count,
        "assistant_messages": assistant_count,
    }


def sanitized_sqlite_backup(source: Path, destination: Path) -> dict:
    if not source.is_file():
        return {"created": False, "reason": "database not found"}
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    scrubbed_columns: list[str] = []
    with sqlite3.connect(destination) as db:
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
            for _, column, column_type, not_null, *_ in columns:
                if SENSITIVE_COLUMN.search(column):
                    replacement = "" if not_null else None
                    db.execute(
                        f'UPDATE "{table}" SET "{column}" = ?',
                        (replacement,),
                    )
                    scrubbed_columns.append(f"{table}.{column}")
                    continue
                if "CHAR" not in column_type.upper() and "TEXT" not in column_type.upper():
                    continue
                rows = db.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
                ).fetchall()
                for rowid, current in rows:
                    redacted = redact_text(current)
                    if redacted != current:
                        db.execute(
                            f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?',
                            (redacted, rowid),
                        )
        db.commit()
    return {"created": True, "scrubbed_columns": scrubbed_columns}


def artifact_manifest(repo: Path) -> list[dict]:
    records: list[dict] = []
    for relative in ARTIFACT_DIRS:
        root = repo / relative
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            records.append(
                {
                    "path": path.relative_to(repo).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    return records


def env_key_manifest(repo: Path) -> list[dict]:
    env_path = repo / ".env"
    if not env_path.is_file():
        return []
    keys: list[dict] = []
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        keys.append({"key": key.strip(), "configured": bool(value.strip())})
    return keys


def create_backup(args: argparse.Namespace) -> Path:
    repo = Path(args.repo_root).resolve()
    date_key = args.date or datetime.now().astimezone().date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_key):
        raise ValueError("Backup date must use YYYY-MM-DD")
    run_key = datetime.now().astimezone().strftime("%H%M%S")
    destination = (
        Path(args.private_root).resolve()
        / date_key[:4]
        / date_key
        / run_key
    )
    (destination / "git").mkdir(parents=True)
    (destination / "session").mkdir()
    (destination / "db").mkdir()
    (destination / "runtime").mkdir()

    head = run(["git", "rev-parse", "HEAD"], repo)
    branch = run(["git", "branch", "--show-current"], repo)
    status = run(["git", "status", "--porcelain=v1"], repo, check=False)
    (destination / "git" / "status.txt").write_text(status + "\n", encoding="utf-8")
    run(
        ["git", "bundle", "create", str(destination / "git" / "repo.bundle"), "--all"],
        repo,
    )

    session_log = Path(args.session_log).resolve() if args.session_log else newest_session_log()
    session = archive_session(session_log, destination / "session", date_key)
    db_result = sanitized_sqlite_backup(
        repo / "atlas_local.db",
        destination / "db" / "atlas_local.sanitized.db",
    )

    artifacts = artifact_manifest(repo)
    (destination / "runtime" / "artifact-manifest.json").write_text(
        json.dumps(artifacts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (destination / "runtime" / "env-keys.json").write_text(
        json.dumps(env_key_manifest(repo), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    def version(command: list[str]) -> str:
        try:
            return run(command, repo, check=False)
        except OSError:
            return "not installed"

    versions = {
        "python": sys.version,
        "git": version(["git", "--version"]),
        "node": version(["node", "--version"]),
        "npm": version(["npm", "--version"]),
    }
    (destination / "runtime" / "versions.json").write_text(
        json.dumps(versions, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "format": 1,
        "created_at": datetime.now().astimezone().isoformat(),
        "date": date_key,
        "repo": str(repo),
        "branch": branch,
        "head": head,
        "working_tree_clean": not bool(status),
        "session": session,
        "database": db_result,
        "artifact_files": len(artifacts),
        "artifact_bytes": sum(record["size"] for record in artifacts),
        "credentials_included": False,
        "restore_requires_platform_reauthorization": True,
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    checksum_lines = []
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            checksum_lines.append(f"{sha256(path)}  {path.relative_to(destination).as_posix()}")
    (destination / "SHA256SUMS.txt").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="utf-8",
    )

    if args.mirror_root:
        mirror = (
            Path(args.mirror_root).resolve()
            / date_key[:4]
            / date_key
            / run_key
        )
        mirror.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(destination, mirror)
    print(destination)
    return destination


def verify_backup(args: argparse.Namespace) -> None:
    root = Path(args.manifest).resolve().parent
    checksum_path = root / "SHA256SUMS.txt"
    failures = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            failures.append(relative)
    if failures:
        raise RuntimeError(f"Backup verification failed: {failures}")
    print(f"Backup verified: {root}")


def parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    command = argparse.ArgumentParser(description="Create and verify Atlas daily backups")
    subparsers = command.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--repo-root", default=str(root))
    create.add_argument("--private-root", default=str(root / "backups" / "daily"))
    create.add_argument("--mirror-root", default=os.getenv("ATLAS_BACKUP_MIRROR", ""))
    create.add_argument("--session-log")
    create.add_argument("--date")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    return command


def main() -> None:
    args = parser().parse_args()
    if args.command == "create":
        create_backup(args)
    else:
        verify_backup(args)


if __name__ == "__main__":
    main()
