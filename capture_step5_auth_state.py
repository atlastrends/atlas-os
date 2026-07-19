from pathlib import Path
import json
import re
import urllib.request

from sqlalchemy import inspect, text

from app.core.database import engine


ROOT = Path("/atlas")

FILES = [
    "app/main.py",
    "app/core/database.py",
    "app/core/security.py",
    "app/models/user.py",
    "app/models/__init__.py",
    "app/schemas/user.py",
    "app/schemas/auth.py",
    "app/routers/auth.py",
    "app/routers/users.py",
    "app/routers/affiliate_content_review.py",
    "app/models/affiliate.py",
]

SENSITIVE_WORDS = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "client_secret",
)

ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<prefix>\s*[^#\n=]{1,120}"
    r"(?:password|secret|token|api_key|"
    r"private_key|client_secret)"
    r"[^=\n]*=\s*)"
    r"(?P<value>.+)$",
    flags=re.IGNORECASE,
)


def redact_line(line: str) -> str:
    stripped = line.strip()

    if (
        not stripped
        or stripped.startswith("#")
        or stripped.startswith("def ")
        or stripped.startswith("class ")
    ):
        return line

    match = ASSIGNMENT_PATTERN.match(
        line.rstrip("\r\n")
    )

    if not match:
        return line

    prefix = match.group("prefix")
    newline = (
        "\n"
        if line.endswith(("\n", "\r"))
        else ""
    )

    return (
        prefix
        + '"[REDACTED]"'
        + newline
    )


def read_file(relative_path: str) -> str:
    path = ROOT / relative_path

    if not path.is_file():
        return "[ARQUIVO NAO ENCONTRADO]\n"

    content = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    return "".join(
        redact_line(line)
        for line in content.splitlines(
            keepends=True
        )
    )


def print_section(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def get_openapi() -> dict:
    with urllib.request.urlopen(
        "http://localhost:8000/openapi.json",
        timeout=15,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


print("=" * 72)
print("ATLAS OS - PRE-VALIDACAO DO PASSO 5")
print("=" * 72)
print("Worker autorizado: False")
print("Alteracao executada: False")
print("Usuario criado: False")
print("Conteudo gerado: False")
print("Video gerado: False")
print("Publicacao executada: False")


for relative_path in FILES:
    print_section(
        f"ARQUIVO: {relative_path}"
    )

    print(
        read_file(relative_path)
    )


print_section("ARQUIVOS RELACIONADOS A AUTH E USER")

candidate_directories = [
    ROOT / "app",
    ROOT / "alembic/versions",
]

keywords = (
    "auth",
    "user",
    "security",
    "permission",
    "role",
    "audit",
)

for directory in candidate_directories:
    if not directory.is_dir():
        continue

    for path in sorted(
        directory.rglob("*.py")
    ):
        relative_name = str(
            path.relative_to(ROOT)
        ).replace("\\", "/")

        if any(
            keyword in relative_name.lower()
            for keyword in keywords
        ):
            print(relative_name)


print_section("MIGRACOES ALEMBIC")

versions_directory = (
    ROOT / "alembic/versions"
)

if versions_directory.is_dir():
    for path in sorted(
        versions_directory.glob("*.py")
    ):
        text_content = path.read_text(
            encoding="utf-8-sig",
            errors="replace",
        )

        revision_match = re.search(
            r'^\s*revision(?:\s*:\s*[^=]+)?'
            r'\s*=\s*["\']([^"\']+)["\']',
            text_content,
            flags=re.MULTILINE,
        )

        down_match = re.search(
            r'^\s*down_revision'
            r'(?:\s*:\s*[^=]+)?'
            r'\s*=\s*["\']([^"\']+)["\']',
            text_content,
            flags=re.MULTILINE,
        )

        revision = (
            revision_match.group(1)
            if revision_match
            else "desconhecida"
        )

        down_revision = (
            down_match.group(1)
            if down_match
            else "None/complexa"
        )

        print(
            f"{path.name} | "
            f"revision={revision} | "
            f"down_revision={down_revision}"
        )


print_section("ESTRUTURA DO BANCO - USERS")

inspector = inspect(engine)

table_names = set(
    inspector.get_table_names()
)

user_table_candidates = [
    name
    for name in sorted(table_names)
    if (
        "user" in name.lower()
        or "account" in name.lower()
    )
]

if not user_table_candidates:
    print(
        "[NENHUMA TABELA DE USUARIO LOCALIZADA]"
    )

for table_name in user_table_candidates:
    print("")
    print(f"TABELA: {table_name}")

    for column in inspector.get_columns(
        table_name
    ):
        print(
            "COLUNA "
            f"{column['name']} | "
            f"tipo={column['type']} | "
            f"nullable={column['nullable']} | "
            f"default={column.get('default')}"
        )

    for constraint in (
        inspector.get_unique_constraints(
            table_name
        )
    ):
        print(
            "UNIQUE "
            f"{constraint.get('name')} | "
            f"colunas="
            f"{constraint.get('column_names')}"
        )

    for index in inspector.get_indexes(
        table_name
    ):
        print(
            "INDEX "
            f"{index.get('name')} | "
            f"unique={index.get('unique')} | "
            f"colunas={index.get('column_names')}"
        )


print_section("ESTRUTURA DO BANCO - ALEMBIC")

with engine.connect() as connection:
    revisions = connection.execute(
        text(
            "SELECT version_num "
            "FROM alembic_version "
            "ORDER BY version_num"
        )
    ).scalars().all()

for revision in revisions:
    print(f"REVISION_APLICADA={revision}")


print_section("ROTAS E SEGURANCA OPENAPI")

openapi = get_openapi()

selected_prefixes = (
    "/auth",
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

        operation_security = (
            operation.get("security")
        )

        global_security = (
            openapi.get("security")
        )

        effective_security = (
            operation_security
            if operation_security is not None
            else global_security
        )

        print("")
        print(
            f"{method.upper()} {route}"
        )

        print(
            "operationId="
            f"{operation.get('operationId', '')}"
        )

        print(
            "security="
            + json.dumps(
                effective_security,
                ensure_ascii=False,
            )
        )


print_section("SECURITY SCHEMES OPENAPI")

security_schemes = (
    openapi
    .get("components", {})
    .get("securitySchemes", {})
)

print(
    json.dumps(
        security_schemes,
        ensure_ascii=False,
        indent=2,
    )
)


print_section("RESUMO DA CAPTURA")

print("Worker autorizado: False")
print("Alteracao executada: False")
print("Usuario criado: False")
print("Conteudo gerado: False")
print("Video gerado: False")
print("Publicacao executada: False")
print("PRE-VALIDACAO DO PASSO 5 CONCLUIDA")