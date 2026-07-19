from pathlib import Path
import ast
import re

from sqlalchemy import inspect, text

from app.core.database import engine


ROOT = Path("/atlas")

FILES = [
    "app/security/deps.py",
    "app/security/jwt.py",
    "app/security/password.py",
    "app/repositories/user.py",
    "app/schemas/token.py",
    "app/models/event_log.py",
    "app/core/config.py",
    "alembic/versions/338520c92b44_initial_schema.py",
    "alembic/versions/496aa6fa4b37_add_updated_at_to_users.py",
    "alembic/versions/a88355ba762e_add_hashed_password.py",
    "alembic/versions/6a7025e418a9_cria_tabelas_da_fabrica_de_canais.py",
]

SENSITIVE_IDENTIFIERS = {
    "secret",
    "secret_key",
    "jwt_secret",
    "jwt_secret_key",
    "access_token_secret",
    "refresh_token_secret",
    "private_key",
    "api_key",
    "database_url",
    "db_url",
    "password",
}

ASSIGNMENT_PATTERN = re.compile(
    r"^(?P<indent>\s*)"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<annotation>\s*:\s*[^=]+)?"
    r"(?P<equals>\s*=\s*)"
    r"(?P<value>.+?)"
    r"(?P<newline>\r?\n)?$"
)


def redact_sensitive_assignments(
    source: str,
) -> str:
    output = []

    for line in source.splitlines(
        keepends=True
    ):
        match = ASSIGNMENT_PATTERN.match(line)

        if not match:
            output.append(line)
            continue

        name = match.group("name").lower()

        if name not in SENSITIVE_IDENTIFIERS:
            output.append(line)
            continue

        newline = match.group("newline") or ""

        output.append(
            match.group("indent")
            + match.group("name")
            + (match.group("annotation") or "")
            + match.group("equals")
            + '"[REDACTED]"'
            + newline
        )

    return "".join(output)


def read_source(
    relative_path: str,
) -> str:
    path = ROOT / relative_path

    if not path.is_file():
        return "[ARQUIVO NAO ENCONTRADO]\n"

    source = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    return redact_sensitive_assignments(
        source
    )


def print_section(title: str) -> None:
    print("")
    print("=" * 72)
    print(title)
    print("=" * 72)


def print_python_structure(
    relative_path: str,
) -> None:
    path = ROOT / relative_path

    if not path.is_file():
        print("[ARQUIVO NAO ENCONTRADO]")
        return

    source = path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        print(
            "AST_ERRO="
            f"{error.__class__.__name__}: "
            f"{error}"
        )
        return

    for node in tree.body:
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            arguments = []

            for argument in node.args.args:
                arguments.append(
                    argument.arg
                )

            print(
                "FUNCAO "
                f"{node.name}"
                f"({', '.join(arguments)})"
            )

        elif isinstance(node, ast.ClassDef):
            print(f"CLASSE {node.name}")

            for class_node in node.body:
                if isinstance(
                    class_node,
                    (
                        ast.FunctionDef,
                        ast.AsyncFunctionDef,
                    ),
                ):
                    arguments = [
                        argument.arg
                        for argument
                        in class_node.args.args
                    ]

                    print(
                        "  METODO "
                        f"{class_node.name}"
                        f"({', '.join(arguments)})"
                    )


print("=" * 72)
print("ATLAS OS - COMPLEMENTO DE AUTH DO PASSO 5")
print("=" * 72)
print("Somente leitura: True")
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
        read_source(relative_path)
    )

    if relative_path.endswith(".py"):
        print("")
        print("ESTRUTURA AST:")

        print_python_structure(
            relative_path
        )


print_section("ESTRUTURA DAS TABELAS DE AUDITORIA")

inspector = inspect(engine)

table_names = set(
    inspector.get_table_names()
)

audit_candidates = [
    table_name
    for table_name in sorted(table_names)
    if any(
        keyword in table_name.lower()
        for keyword in (
            "event",
            "audit",
            "log",
            "history",
        )
    )
]

if not audit_candidates:
    print(
        "[NENHUMA TABELA DE AUDITORIA LOCALIZADA]"
    )

for table_name in audit_candidates:
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

    for foreign_key in (
        inspector.get_foreign_keys(
            table_name
        )
    ):
        print(
            "FOREIGN_KEY "
            f"{foreign_key.get('name')} | "
            f"colunas="
            f"{foreign_key.get('constrained_columns')} | "
            f"destino="
            f"{foreign_key.get('referred_table')}."
            f"{foreign_key.get('referred_columns')}"
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


print_section("RESUMO NAO IDENTIFICAVEL DE USUARIOS")

with engine.connect() as connection:
    user_summary = connection.execute(
        text(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE is_active = true
                ) AS active,
                COUNT(*) FILTER (
                    WHERE is_active = false
                ) AS inactive,
                COUNT(*) FILTER (
                    WHERE hashed_password IS NULL
                ) AS without_password
            FROM users
            """
        )
    ).mappings().one()

print(
    "TOTAL_USERS="
    f"{user_summary['total']}"
)

print(
    "ACTIVE_USERS="
    f"{user_summary['active']}"
)

print(
    "INACTIVE_USERS="
    f"{user_summary['inactive']}"
)

print(
    "USERS_WITHOUT_PASSWORD="
    f"{user_summary['without_password']}"
)


print_section("FOREIGN KEYS PARA USERS")

for table_name in sorted(table_names):
    for foreign_key in (
        inspector.get_foreign_keys(
            table_name
        )
    ):
        if (
            foreign_key.get("referred_table")
            != "users"
        ):
            continue

        print(
            f"TABELA={table_name} | "
            f"COLUNAS="
            f"{foreign_key.get('constrained_columns')} | "
            f"DESTINO="
            f"{foreign_key.get('referred_columns')} | "
            f"NOME={foreign_key.get('name')}"
        )


print_section("CONFIGURACAO JWT SEM SEGREDOS")

jwt_path = ROOT / "app/security/jwt.py"

if jwt_path.is_file():
    jwt_source = jwt_path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )

    patterns = {
        "algorithm": (
            r"(?:ALGORITHM|algorithm)"
            r"\s*=\s*[\"']([^\"']+)[\"']"
        ),
        "expire_minutes": (
            r"(?:ACCESS_TOKEN_EXPIRE_MINUTES|"
            r"access_token_expire_minutes)"
            r"\s*=\s*(\d+)"
        ),
        "token_url": (
            r"tokenUrl\s*=\s*[\"']([^\"']+)[\"']"
        ),
    }

    for key, pattern in patterns.items():
        match = re.search(
            pattern,
            jwt_source,
        )

        print(
            f"{key.upper()}="
            + (
                match.group(1)
                if match
                else "[NAO IDENTIFICADO]"
            )
        )
else:
    print(
        "[ARQUIVO JWT NAO ENCONTRADO]"
    )


print_section("REVISAO ATUAL")

with engine.connect() as connection:
    revision = connection.execute(
        text(
            "SELECT version_num "
            "FROM alembic_version"
        )
    ).scalar_one()

print(f"REVISION_APLICADA={revision}")


print_section("RESUMO DA CAPTURA")

print("Somente leitura: True")
print("Worker autorizado: False")
print("Alteracao executada: False")
print("Usuario criado: False")
print("Conteudo gerado: False")
print("Video gerado: False")
print("Publicacao executada: False")
print("CAPTURA COMPLEMENTAR DO PASSO 5 CONCLUIDA")