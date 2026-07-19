from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import urllib.request

from sqlalchemy import inspect, text

from app.core.database import engine


ROOT = Path("/atlas")

DIRECT_FILES = [
    "app/main.py",
    "app/routers/auth.py",
    "app/routers/users.py",
    "app/routers/affiliate.py",
    "app/routers/affiliate_content_review.py",
    "app/routers/affiliate_video.py",
    "app/services/video_engine.py",
    "app/services/content_audit_service.py",
    "app/security/deps.py",
    "app/security/roles.py",
    "app/security/jwt.py",
    "app/models/affiliate.py",
    "app/models/content_audit.py",
    "app/schemas/token.py",
    "docker-compose.yml",
    "compose.yml",
    "compose.yaml",
    "requirements.txt",
    "pyproject.toml",
]

SEARCH_DIRECTORIES = [
    ROOT / "app",
    ROOT / "scripts",
]

NAME_KEYWORDS = (
    "video",
    "publish",
    "publisher",
    "upload",
    "tiktok",
    "instagram",
    "youtube",
    "ffmpeg",
    "media",
    "render",
    "oauth",
)

SENSITIVE_NAME_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "access_key",
    "refresh_token",
    "cookie",
    "session",
)

SENSITIVE_VALUE_PATTERN = re.compile(
    r"""
    ^
    (?P<prefix>
        \s*
        [A-Za-z_][A-Za-z0-9_]*
        (?:\s*:\s*[^=]+)?
        \s*=\s*
    )
    (?P<value>.+?)
    (?P<newline>\r?\n)?
    $
    """,
    flags=re.VERBOSE,
)


def section(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def is_sensitive_name(name: str) -> bool:
    normalized = str(name or "").lower()

    return any(
        part in normalized
        for part in SENSITIVE_NAME_PARTS
    )


def redact_source(source: str) -> str:
    output = []

    for line in source.splitlines(
        keepends=True
    ):
        match = SENSITIVE_VALUE_PATTERN.match(
            line
        )

        if not match:
            output.append(line)
            continue

        prefix = match.group("prefix")

        variable_match = re.match(
            r"\s*([A-Za-z_][A-Za-z0-9_]*)",
            prefix,
        )

        variable_name = (
            variable_match.group(1)
            if variable_match
            else ""
        )

        if not is_sensitive_name(variable_name):
            output.append(line)
            continue

        output.append(
            prefix
            + '"[REDACTED]"'
            + (match.group("newline") or "")
        )

    return "".join(output)


def print_file(relative_path: str) -> None:
    path = ROOT / relative_path

    section(f"ARQUIVO: {relative_path}")

    if not path.is_file():
        print("[ARQUIVO NAO ENCONTRADO]")
        return

    source = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    print(
        redact_source(source)
    )


def command_version(
    command: list[str],
) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        combined = (
            result.stdout
            or result.stderr
            or ""
        ).strip()

        first_line = (
            combined.splitlines()[0]
            if combined
            else ""
        )

        return (
            first_line
            or f"exit_code={result.returncode}"
        )

    except Exception as error:
        return (
            f"[INDISPONIVEL: "
            f"{error.__class__.__name__}]"
        )


print("=" * 72)
print("ATLAS OS - RELEASE READINESS")
print("=" * 72)
print("Somente leitura: True")
print("Publicacao executada: False")
print("Video gerado: False")
print("Usuario criado: False")
print("Worker autorizado: False")


for relative_path in DIRECT_FILES:
    print_file(relative_path)


section("ARQUIVOS RELACIONADOS A VIDEO E PUBLICACAO")

located_files = set()

for directory in SEARCH_DIRECTORIES:
    if not directory.is_dir():
        continue

    for path in directory.rglob("*.py"):
        relative = str(
            path.relative_to(ROOT)
        ).replace("\\", "/")

        lowered = relative.lower()

        if any(
            keyword in lowered
            for keyword in NAME_KEYWORDS
        ):
            located_files.add(relative)

for relative in sorted(located_files):
    print(relative)


section("VARIAVEIS DE AMBIENTE RELEVANTES")

relevant_env_keywords = (
    "TIKTOK",
    "INSTAGRAM",
    "META",
    "FACEBOOK",
    "YOUTUBE",
    "GOOGLE",
    "OAUTH",
    "VIDEO",
    "FFMPEG",
    "MEDIA",
    "UPLOAD",
    "PUBLISH",
    "JWT",
    "ATLAS_ENGINE",
)

for name in sorted(os.environ):
    upper_name = name.upper()

    if not any(
        keyword in upper_name
        for keyword in relevant_env_keywords
    ):
        continue

    value = os.environ.get(name, "")

    if is_sensitive_name(name):
        rendered_value = (
            "[CONFIGURADA]"
            if value
            else "[VAZIA]"
        )
    else:
        rendered_value = value

    print(
        f"{name}={rendered_value}"
    )


section("FERRAMENTAS DE VIDEO")

print(
    "FFMPEG_PATH="
    f"{shutil.which('ffmpeg') or '[AUSENTE]'}"
)

print(
    "FFPROBE_PATH="
    f"{shutil.which('ffprobe') or '[AUSENTE]'}"
)

print(
    "FFMPEG_VERSION="
    + command_version(
        ["ffmpeg", "-version"]
    )
)

print(
    "FFPROBE_VERSION="
    + command_version(
        ["ffprobe", "-version"]
    )
)


section("DIRETORIOS DE MIDIA")

media_candidates = [
    ROOT / "media",
    ROOT / "videos",
    ROOT / "output",
    ROOT / "outputs",
    ROOT / "storage",
    ROOT / "assets",
    ROOT / "static",
    ROOT / "tmp",
]

for path in media_candidates:
    print(
        f"{path.name}: "
        f"exists={path.exists()} "
        f"is_dir={path.is_dir()}"
    )

    if not path.is_dir():
        continue

    file_count = 0
    total_size = 0
    extensions = {}

    for item in path.rglob("*"):
        if not item.is_file():
            continue

        file_count += 1

        try:
            total_size += item.stat().st_size
        except OSError:
            pass

        suffix = (
            item.suffix.lower()
            or "[sem_extensao]"
        )

        extensions[suffix] = (
            extensions.get(suffix, 0) + 1
        )

    print(
        f"  files={file_count}"
    )

    print(
        f"  total_bytes={total_size}"
    )

    print(
        "  extensions="
        + json.dumps(
            extensions,
            ensure_ascii=False,
            sort_keys=True,
        )
    )


section("ESTADO DO BANCO")

database_inspector = inspect(engine)

table_names = set(
    database_inspector.get_table_names()
)

with engine.connect() as connection:
    revision = connection.execute(
        text(
            "SELECT version_num "
            "FROM alembic_version"
        )
    ).scalar_one()

    user_count = connection.execute(
        text(
            "SELECT COUNT(*) FROM users"
        )
    ).scalar_one()

    product_count = connection.execute(
        text(
            "SELECT COUNT(*) "
            "FROM affiliate_products"
        )
    ).scalar_one()

    content_count = connection.execute(
        text(
            "SELECT COUNT(*) "
            "FROM affiliate_contents"
        )
    ).scalar_one()

    status_counts = connection.execute(
        text(
            """
            SELECT
                status::text AS status,
                COUNT(*) AS total
            FROM affiliate_contents
            GROUP BY status::text
            ORDER BY status::text
            """
        )
    ).mappings().all()

    audit_count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM affiliate_content_audit_logs
            """
        )
    ).scalar_one()


print(f"REVISION={revision}")
print(f"USER_COUNT={user_count}")
print(f"PRODUCT_COUNT={product_count}")
print(f"CONTENT_COUNT={content_count}")
print(f"AUDIT_COUNT={audit_count}")

for item in status_counts:
    print(
        "CONTENT_STATUS_"
        f"{item['status']}="
        f"{item['total']}"
    )


section("OPENAPI DE AUTH, CONTEUDO E VIDEO")

with urllib.request.urlopen(
    "http://localhost:8000/openapi.json",
    timeout=20,
) as response:
    openapi = json.loads(
        response.read().decode("utf-8")
    )

selected_prefixes = (
    "/login",
    "/users",
    "/affiliate/content",
    "/affiliate/video",
)

for route, route_data in sorted(
    openapi.get("paths", {}).items()
):
    if not route.startswith(
        selected_prefixes
    ):
        continue

    for method, operation in route_data.items():
        if method.lower() not in {
            "get",
            "post",
            "put",
            "patch",
            "delete",
        }:
            continue

        security = operation.get("security")

        if security is None:
            security = openapi.get("security")

        print("")
        print(f"{method.upper()} {route}")
        print(
            "operationId="
            f"{operation.get('operationId', '')}"
        )
        print(
            "security="
            + json.dumps(
                security,
                ensure_ascii=False,
            )
        )

        request_body = (
            operation
            .get("requestBody", {})
            .get("content", {})
        )

        if request_body:
            print(
                "request_content_types="
                + ",".join(
                    sorted(request_body)
                )
            )


section("RELOGIO DO CONTAINER")

print(
    "SYSTEM_DATE="
    + command_version(
        [
            "date",
            "--iso-8601=seconds",
        ]
    )
)


section("RESUMO")

print("Somente leitura: True")
print("Publicacao executada: False")
print("Video gerado: False")
print("Usuario criado: False")
print("Worker autorizado: False")
print("RELEASE READINESS CONCLUIDO")