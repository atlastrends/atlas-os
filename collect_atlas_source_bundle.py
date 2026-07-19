from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile


ROOT = Path("/atlas").resolve()

STAGING = (
    ROOT
    / "_atlas_source_review_bundle"
)

OUTPUT_ZIP = (
    ROOT
    / "atlas_source_review_bundle.zip"
)

COLLECTOR_PATH = (
    ROOT
    / "collect_atlas_source_bundle.py"
)


# ============================================================
# CONFIGURACAO
# ============================================================

ALLOWED_SUFFIXES = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".vue",
    ".svelte",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".html",
    ".htm",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".conf",
    ".md",
    ".rst",
    ".sql",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".txt",
    ".properties",
    ".xml",
}

ALLOWED_NAMES_WITHOUT_SUFFIX = {
    "Dockerfile",
    "Makefile",
    "Procfile",
    "Pipfile",
    "LICENSE",
    "README",
}

EXCLUDED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    "media",
    "videos",
    "video",
    "audio",
    "images",
    "uploads",
    "output",
    "outputs",
    "storage",
    "tmp",
    "temp",
    "logs",
    "log",
    "backups",
    "backup",
    "_atlas_source_review_bundle",
}

EXCLUDED_EXACT_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.test",
    ".env.staging",
    "credentials.json",
    "client_secret.json",
    "client_secrets.json",
    "service-account.json",
    "service_account.json",
    "token.json",
    "tokens.json",
    "cookies.json",
    "session.json",
    "id_rsa",
    "id_ed25519",
    "release_readiness.txt",
    "atlas_source_review_bundle.zip",
    "collect_atlas_source_bundle.py",
}

EXCLUDED_NAME_PARTS = {
    ".before_step",
    ".bak",
    ".backup",
    ".sqlite",
    ".sqlite3",
    ".dump",
    ".tar",
    ".zip",
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".keystore",
    "private_key",
    "private-key",
    "client_secret",
    "client-secret",
    "credentials",
    "refresh_token",
    "access_token",
}

SENSITIVE_KEY_PARTS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "client_secret",
    "access_key",
    "refresh_token",
    "cookie",
    "session_key",
    "jwt_secret",
    "jwt_key",
    "signing_key",
    "webhook_secret",
}

SENSITIVE_EXCEPTIONS = {
    "token_type",
    "token_url",
    "tokenurl",
    "max_tokens",
    "sessionmaker",
    "session_factory",
    "password_context",
    "password_hash",
    "hashed_password",
    "verify_password",
    "get_password_hash",
}

RELEVANT_ENV_KEYWORDS = {
    "ATLAS",
    "DATABASE",
    "POSTGRES",
    "REDIS",
    "CELERY",
    "JWT",
    "AUTH",
    "OAUTH",
    "TIKTOK",
    "INSTAGRAM",
    "META",
    "FACEBOOK",
    "YOUTUBE",
    "GOOGLE",
    "VIDEO",
    "FFMPEG",
    "MEDIA",
    "UPLOAD",
    "PUBLISH",
    "AMAZON",
    "AWS",
    "OPENAI",
}

MAX_FILE_BYTES = 2 * 1024 * 1024


copied_files: list[str] = []
excluded_files: list[dict[str, str]] = []
security_findings: list[dict[str, Any]] = []
collection_errors: list[dict[str, str]] = []


# ============================================================
# UTILITARIOS
# ============================================================

def relative_name(path: Path) -> str:
    return str(
        path.relative_to(ROOT)
    ).replace("\\", "/")


def write_text(
    path: Path,
    content: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )


def is_sensitive_key(name: str) -> bool:
    normalized = re.sub(
        r"[^a-z0-9_]",
        "_",
        str(name or "").strip().lower(),
    )

    if normalized in SENSITIVE_EXCEPTIONS:
        return False

    if any(
        exception in normalized
        for exception in SENSITIVE_EXCEPTIONS
    ):
        return False

    return any(
        part in normalized
        for part in SENSITIVE_KEY_PARTS
    )


def record_finding(
    file_name: str,
    line: int | None,
    category: str,
    key: str = "",
) -> None:
    security_findings.append(
        {
            "file": file_name,
            "line": line,
            "category": category,
            "key": key,
            "value_included": False,
        }
    )


def record_exclusion(
    path: Path,
    reason: str,
) -> None:
    try:
        name = relative_name(path)
    except Exception:
        name = path.name

    excluded_files.append(
        {
            "file": name,
            "reason": reason,
        }
    )


def exclusion_reason(
    path: Path,
) -> str | None:
    try:
        relative_parts = path.relative_to(
            ROOT
        ).parts
    except Exception:
        return "arquivo fora da raiz"

    for part in relative_parts[:-1]:
        if part.lower() in EXCLUDED_DIRECTORIES:
            return (
                "diretorio excluido: "
                + part
            )

    file_name = path.name
    lowered = file_name.lower()

    if file_name in EXCLUDED_EXACT_NAMES:
        return "arquivo sensivel ou gerado"

    if lowered.startswith(".env"):
        return "arquivo de ambiente"

    if any(
        part in lowered
        for part in EXCLUDED_NAME_PARTS
    ):
        return (
            "nome sensivel, backup ou binario"
        )

    return None


def is_allowed_file(path: Path) -> bool:
    if path.name in ALLOWED_NAMES_WITHOUT_SUFFIX:
        return True

    return (
        path.suffix.lower()
        in ALLOWED_SUFFIXES
    )


def redact_json(
    value: Any,
    file_name: str,
) -> Any:
    if isinstance(value, dict):
        result = {}

        for key, child in value.items():
            rendered_key = str(key)

            if is_sensitive_key(rendered_key):
                configured = (
                    child is not None
                    and child != ""
                    and child is not False
                )

                if configured:
                    record_finding(
                        file_name,
                        None,
                        "chave JSON sensivel",
                        rendered_key,
                    )

                result[key] = "[REDACTED]"
            else:
                result[key] = redact_json(
                    child,
                    file_name,
                )

        return result

    if isinstance(value, list):
        return [
            redact_json(
                child,
                file_name,
            )
            for child in value
        ]

    return value


def redact_text(
    source: str,
    file_name: str,
) -> str:
    private_key_pattern = re.compile(
        r"-----BEGIN [^-]*PRIVATE KEY-----"
        r".*?"
        r"-----END [^-]*PRIVATE KEY-----",
        flags=re.DOTALL,
    )

    if private_key_pattern.search(source):
        record_finding(
            file_name,
            None,
            "bloco de chave privada",
        )

        source = private_key_pattern.sub(
            "-----BEGIN PRIVATE KEY-----\n"
            "[REDACTED]\n"
            "-----END PRIVATE KEY-----",
            source,
        )

    assignment_pattern = re.compile(
        r"""
        ^
        (?P<prefix>
            \s*
            (?:export\s+)?
            (?P<key>[A-Za-z_][A-Za-z0-9_]*)
            (?:\s*:\s*[^=]+)?
            \s*=\s*
        )
        (?P<quote>["'])
        (?P<value>.*)
        (?P=quote)
        (?P<tail>\s*(?:[#;].*)?)
        $
        """,
        flags=re.VERBOSE,
    )

    mapping_pattern = re.compile(
        r"""
        ^
        (?P<indent>\s*)
        (?P<keyquote>["']?)
        (?P<key>[A-Za-z_][A-Za-z0-9_.-]*)
        (?P=keyquote)
        \s*:\s*
        (?P<quote>["'])
        (?P<value>.*)
        (?P=quote)
        (?P<tail>\s*,?\s*(?:#.*)?)
        $
        """,
        flags=re.VERBOSE,
    )

    bearer_pattern = re.compile(
        r"(?i)\bBearer\s+"
        r"[A-Za-z0-9._~+/=-]{12,}"
    )

    url_secret_pattern = re.compile(
        r"""
        (?P<prefix>
            [\?&]
            (?P<key>
                access_token|
                refresh_token|
                token|
                api_key|
                apikey|
                client_secret|
                signature
            )
            =
        )
        (?P<value>[^&#\s"']+)
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    output: list[str] = []

    for line_number, original in enumerate(
        source.splitlines(keepends=True),
        start=1,
    ):
        if original.endswith("\r\n"):
            newline = "\r\n"
            line = original[:-2]
        elif original.endswith("\n"):
            newline = "\n"
            line = original[:-1]
        else:
            newline = ""
            line = original

        rendered = line

        assignment = assignment_pattern.match(
            rendered
        )

        if (
            assignment
            and is_sensitive_key(
                assignment.group("key")
            )
        ):
            record_finding(
                file_name,
                line_number,
                "atribuicao literal sensivel",
                assignment.group("key"),
            )

            rendered = (
                assignment.group("prefix")
                + assignment.group("quote")
                + "[REDACTED]"
                + assignment.group("quote")
                + assignment.group("tail")
            )

        else:
            mapping = mapping_pattern.match(
                rendered
            )

            if (
                mapping
                and is_sensitive_key(
                    mapping.group("key")
                )
            ):
                record_finding(
                    file_name,
                    line_number,
                    "mapeamento literal sensivel",
                    mapping.group("key"),
                )

                rendered_key = (
                    mapping.group("keyquote")
                    + mapping.group("key")
                    + mapping.group("keyquote")
                )

                rendered = (
                    mapping.group("indent")
                    + rendered_key
                    + ": "
                    + mapping.group("quote")
                    + "[REDACTED]"
                    + mapping.group("quote")
                    + mapping.group("tail")
                )

        if bearer_pattern.search(rendered):
            record_finding(
                file_name,
                line_number,
                "Bearer token literal",
            )

            rendered = bearer_pattern.sub(
                "Bearer [REDACTED]",
                rendered,
            )

        def replace_url_secret(
            match: re.Match,
        ) -> str:
            record_finding(
                file_name,
                line_number,
                "segredo em URL",
                match.group("key"),
            )

            return (
                match.group("prefix")
                + "[REDACTED]"
            )

        rendered = url_secret_pattern.sub(
            replace_url_secret,
            rendered,
        )

        output.append(
            rendered + newline
        )

    return "".join(output)


def sanitize_file(
    path: Path,
    file_name: str,
) -> str:
    source = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    if path.suffix.lower() == ".json":
        try:
            parsed = json.loads(source)

            sanitized = redact_json(
                parsed,
                file_name,
            )

            return (
                json.dumps(
                    sanitized,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
        except Exception:
            pass

    return redact_text(
        source,
        file_name,
    )


def run_command(
    command: list[str],
    timeout: int = 60,
) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        return {
            "command": command,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    except Exception as error:
        return {
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": (
                f"{error.__class__.__name__}: "
                f"{error}"
            ),
        }


# ============================================================
# PREPARAR AREA TEMPORARIA
# ============================================================

if STAGING.exists():
    shutil.rmtree(STAGING)

STAGING.mkdir(
    parents=True,
    exist_ok=True,
)

if OUTPUT_ZIP.exists():
    OUTPUT_ZIP.unlink()


# ============================================================
# COLETAR CODIGO
# ============================================================

source_root = STAGING / "source"

for path in sorted(ROOT.rglob("*")):
    if not path.is_file():
        continue

    try:
        if path.resolve() == COLLECTOR_PATH.resolve():
            record_exclusion(
                path,
                "script coletor",
            )
            continue
    except Exception:
        pass

    reason = exclusion_reason(path)

    if reason:
        record_exclusion(
            path,
            reason,
        )
        continue

    if not is_allowed_file(path):
        record_exclusion(
            path,
            "extensao nao textual ou nao relevante",
        )
        continue

    try:
        file_size = path.stat().st_size
    except OSError as error:
        collection_errors.append(
            {
                "file": relative_name(path),
                "error": str(error),
            }
        )
        continue

    if file_size > MAX_FILE_BYTES:
        record_exclusion(
            path,
            "arquivo acima do limite de tamanho",
        )
        continue

    file_name = relative_name(path)

    try:
        sanitized_source = sanitize_file(
            path,
            file_name,
        )

        destination = (
            source_root
            / file_name
        )

        write_text(
            destination,
            sanitized_source,
        )

        copied_files.append(file_name)

    except Exception as error:
        collection_errors.append(
            {
                "file": file_name,
                "error": (
                    f"{error.__class__.__name__}: "
                    f"{error}"
                ),
            }
        )


# ============================================================
# ARVORE DO PROJETO
# ============================================================

write_text(
    STAGING / "reports/project_tree.txt",
    "\n".join(
        sorted(copied_files)
    )
    + "\n",
)


# ============================================================
# GIT
# ============================================================

git_report = {
    "head": run_command(
        [
            "git",
            "rev-parse",
            "HEAD",
        ]
    ),
    "branch": run_command(
        [
            "git",
            "branch",
            "--show-current",
        ]
    ),
    "status": run_command(
        [
            "git",
            "status",
            "--short",
        ]
    ),
    "diff_stat": run_command(
        [
            "git",
            "diff",
            "--stat",
        ]
    ),
}

write_text(
    STAGING / "reports/git_state.json",
    json.dumps(
        git_report,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
)


# ============================================================
# AMBIENTE, SEM VALORES
# ============================================================

environment_report = {}

for name in sorted(os.environ):
    upper_name = name.upper()

    if not any(
        keyword in upper_name
        for keyword in RELEVANT_ENV_KEYWORDS
    ):
        continue

    value = os.environ.get(name, "")

    environment_report[name] = {
        "configured": bool(value),
        "length": len(value) if value else 0,
        "value_included": False,
    }

write_text(
    STAGING
    / "reports"
    / "environment_configuration.json",
    json.dumps(
        environment_report,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
)


# ============================================================
# OPENAPI
# ============================================================

try:
    with urllib.request.urlopen(
        "http://localhost:8000/openapi.json",
        timeout=20,
    ) as response:
        openapi = json.loads(
            response.read().decode("utf-8")
        )

    write_text(
        STAGING / "reports/openapi.json",
        json.dumps(
            openapi,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )

except Exception as error:
    collection_errors.append(
        {
            "file": "reports/openapi.json",
            "error": (
                f"{error.__class__.__name__}: "
                f"{error}"
            ),
        }
    )


# ============================================================
# ESQUEMA DO BANCO SEM REGISTROS
# ============================================================

database_report: dict[str, Any] = {
    "revision": None,
    "tables": {},
    "row_counts": {},
    "data_rows_included": False,
}

try:
    from sqlalchemy import inspect, text

    from app.core.database import engine

    inspector = inspect(engine)

    with engine.connect() as connection:
        try:
            database_report["revision"] = (
                connection.execute(
                    text(
                        "SELECT version_num "
                        "FROM alembic_version"
                    )
                ).scalar_one()
            )
        except Exception as error:
            database_report[
                "revision_error"
            ] = str(error)

        table_names = sorted(
            inspector.get_table_names()
        )

        for table_name in table_names:
            table_report: dict[str, Any] = {}

            try:
                table_report["columns"] = [
                    {
                        "name": column.get("name"),
                        "type": str(
                            column.get("type")
                        ),
                        "nullable": column.get(
                            "nullable"
                        ),
                        "default": (
                            str(column.get("default"))
                            if column.get("default")
                            is not None
                            else None
                        ),
                    }
                    for column
                    in inspector.get_columns(
                        table_name
                    )
                ]
            except Exception as error:
                table_report[
                    "columns_error"
                ] = str(error)

            try:
                table_report["primary_key"] = (
                    inspector.get_pk_constraint(
                        table_name
                    )
                )
            except Exception as error:
                table_report[
                    "primary_key_error"
                ] = str(error)

            try:
                table_report["foreign_keys"] = (
                    inspector.get_foreign_keys(
                        table_name
                    )
                )
            except Exception as error:
                table_report[
                    "foreign_keys_error"
                ] = str(error)

            try:
                table_report["indexes"] = (
                    inspector.get_indexes(
                        table_name
                    )
                )
            except Exception as error:
                table_report[
                    "indexes_error"
                ] = str(error)

            try:
                table_report[
                    "unique_constraints"
                ] = (
                    inspector.get_unique_constraints(
                        table_name
                    )
                )
            except Exception as error:
                table_report[
                    "unique_constraints_error"
                ] = str(error)

            try:
                table_report[
                    "check_constraints"
                ] = (
                    inspector.get_check_constraints(
                        table_name
                    )
                )
            except Exception as error:
                table_report[
                    "check_constraints_error"
                ] = str(error)

            database_report["tables"][
                table_name
            ] = table_report

            try:
                quoted_table_name = (
                    '"'
                    + table_name.replace(
                        '"',
                        '""',
                    )
                    + '"'
                )

                row_count = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM "
                        + quoted_table_name
                    )
                ).scalar_one()

                database_report["row_counts"][
                    table_name
                ] = int(row_count)

            except Exception as error:
                database_report["row_counts"][
                    table_name
                ] = {
                    "error": str(error),
                }

    write_text(
        STAGING
        / "reports"
        / "database_schema.json",
        json.dumps(
            database_report,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
    )

except Exception as error:
    collection_errors.append(
        {
            "file": "reports/database_schema.json",
            "error": (
                f"{error.__class__.__name__}: "
                f"{error}"
            ),
        }
    )


# ============================================================
# VERSOES
# ============================================================

runtime_report = {
    "captured_at_utc": (
        datetime.now(timezone.utc).isoformat()
    ),
    "python": sys.version,
    "platform": platform.platform(),
    "pip_freeze": run_command(
        [
            sys.executable,
            "-m",
            "pip",
            "freeze",
        ],
        timeout=120,
    ),
    "ffmpeg": run_command(
        [
            "ffmpeg",
            "-version",
        ]
    ),
    "ffprobe": run_command(
        [
            "ffprobe",
            "-version",
        ]
    ),
    "node": run_command(
        [
            "node",
            "--version",
        ]
    ),
    "npm": run_command(
        [
            "npm",
            "--version",
        ]
    ),
}

write_text(
    STAGING
    / "reports"
    / "runtime_versions.json",
    json.dumps(
        runtime_report,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
)


# ============================================================
# RELATORIOS DA COLETA
# ============================================================

security_report = {
    "values_included": False,
    "finding_count": len(
        security_findings
    ),
    "findings": security_findings,
    "note": (
        "Os valores detectados foram removidos. "
        "Revise os arquivos originais localmente."
    ),
}

write_text(
    STAGING
    / "reports"
    / "security_findings.json",
    json.dumps(
        security_report,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
)

collection_report = {
    "captured_at_utc": (
        datetime.now(timezone.utc).isoformat()
    ),
    "copied_file_count": len(
        copied_files
    ),
    "excluded_file_count": len(
        excluded_files
    ),
    "security_finding_count": len(
        security_findings
    ),
    "error_count": len(
        collection_errors
    ),
    "copied_files": copied_files,
    "excluded_files": excluded_files,
    "errors": collection_errors,
    "database_rows_included": False,
    "environment_values_included": False,
    "media_included": False,
    "credentials_included_intentionally": False,
    "worker_authorized": bool(
        os.getenv(
            "ATLAS_WORKER_RUN_ENABLED"
        )
    ),
    "video_generated": False,
    "publication_executed": False,
}

write_text(
    STAGING
    / "reports"
    / "collection_report.json",
    json.dumps(
        collection_report,
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
)


# ============================================================
# README
# ============================================================

readme = f"""ATLAS OS - PACOTE DE REVISAO

Criado em UTC:
{datetime.now(timezone.utc).isoformat()}

Arquivos copiados:
{len(copied_files)}

Possiveis segredos removidos:
{len(security_findings)}

Erros de coleta:
{len(collection_errors)}

Nao foram incluidos:
- valores de variaveis de ambiente;
- arquivos .env;
- senhas ou tokens;
- cookies ou sessoes;
- chaves privadas;
- registros do banco;
- videos, imagens ou audio;
- node_modules;
- diretorio .git.

Relatorios:
- reports/collection_report.json
- reports/security_findings.json
- reports/database_schema.json
- reports/openapi.json
- reports/project_tree.txt
- reports/git_state.json
- reports/runtime_versions.json
- reports/environment_configuration.json

Database rows included: False
Environment values included: False
Media included: False
Video generated: False
Publication executed: False
Worker authorized: False
"""

write_text(
    STAGING / "README_REVIEW_BUNDLE.txt",
    readme,
)


# ============================================================
# GERAR ZIP
# ============================================================

with zipfile.ZipFile(
    OUTPUT_ZIP,
    mode="w",
    compression=zipfile.ZIP_DEFLATED,
    compresslevel=9,
) as archive:
    for path in sorted(STAGING.rglob("*")):
        if not path.is_file():
            continue

        archive_name = str(
            path.relative_to(STAGING)
        ).replace("\\", "/")

        archive.write(
            path,
            archive_name,
        )


if not OUTPUT_ZIP.is_file():
    raise RuntimeError(
        "O pacote ZIP nao foi criado."
    )

zip_size = OUTPUT_ZIP.stat().st_size

if zip_size <= 0:
    raise RuntimeError(
        "O pacote ZIP foi criado vazio."
    )


print("=" * 72)
print("ATLAS SOURCE REVIEW BUNDLE CONCLUIDO")
print("=" * 72)
print(f"COPIED_FILES={len(copied_files)}")
print(
    f"SECURITY_FINDINGS="
    f"{len(security_findings)}"
)
print(
    f"COLLECTION_ERRORS="
    f"{len(collection_errors)}"
)
print(f"ZIP_NAME={OUTPUT_ZIP.name}")
print(f"ZIP_BYTES={zip_size}")
print("DATABASE_ROWS_INCLUDED=False")
print("ENVIRONMENT_VALUES_INCLUDED=False")
print("MEDIA_INCLUDED=False")
print("VIDEO_GENERATED=False")
print("PUBLICATION_EXECUTED=False")
print("WORKER_AUTHORIZED=False")