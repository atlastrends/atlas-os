from datetime import datetime
from pathlib import Path
import re
import shutil


ROOT = Path("/atlas")

SERVICE_PATH = (
    ROOT
    / "app/services"
    / "affiliate_service.py"
)

MANUAL_PATH = (
    ROOT
    / "app/routers"
    / "affiliate_manual.py"
)

VIDEO_PATH = (
    ROOT
    / "app/routers"
    / "affiliate_video.py"
)

GOVERNANCE_PATH = (
    ROOT
    / "app/services"
    / "affiliate_content_governance.py"
)

MODEL_PATH = ROOT / "app/models/affiliate.py"
SCHEMA_PATH = ROOT / "app/schemas/affiliate.py"

REPOSITORY_PATH = (
    ROOT
    / "app/repositories"
    / "affiliate.py"
)

MIGRATION_PATH = (
    ROOT
    / "alembic/versions"
    / "a7d19c4e2f60_affiliate_content_deduplication.py"
)


required_files = [
    SERVICE_PATH,
    MANUAL_PATH,
    VIDEO_PATH,
    GOVERNANCE_PATH,
    MODEL_PATH,
    SCHEMA_PATH,
    REPOSITORY_PATH,
]

for path in required_files:
    if not path.is_file():
        raise RuntimeError(
            f"Arquivo obrigatorio ausente: {path.name}"
        )


timestamp = datetime.utcnow().strftime(
    "%Y%m%d_%H%M%S"
)


def read(path: Path) -> str:
    return path.read_text(
        encoding="utf-8-sig",
        errors="strict",
    )


def write(
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


def backup(path: Path) -> None:
    if not path.exists():
        return

    destination = Path(
        str(path)
        + f".before_step4b_repair_{timestamp}.bak"
    )

    shutil.copy2(
        path,
        destination,
    )


def replace_once_regex(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    updated, count = re.subn(
        pattern,
        replacement,
        text,
        count=1,
        flags=re.S,
    )

    if count != 1:
        raise RuntimeError(
            f"{label}: esperado 1 bloco, "
            f"encontrado {count}."
        )

    return updated


def scoped_replace(
    text: str,
    start_marker: str,
    end_marker: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    start = text.find(start_marker)

    if start < 0:
        raise RuntimeError(
            f"{label}: inicio da funcao nao localizado."
        )

    if end_marker:
        end = text.find(
            end_marker,
            start + len(start_marker),
        )

        if end < 0:
            raise RuntimeError(
                f"{label}: fim da funcao nao localizado."
            )
    else:
        end = len(text)

    scope = text[start:end]

    updated_scope = replace_once_regex(
        scope,
        pattern,
        replacement,
        label,
    )

    return (
        text[:start]
        + updated_scope
        + text[end:]
    )


for path in [
    SERVICE_PATH,
    MANUAL_PATH,
    VIDEO_PATH,
    MIGRATION_PATH,
]:
    backup(path)


# ============================================================
# 1. GERADOR PRINCIPAL
# ============================================================

service_text = read(SERVICE_PATH)

governance_import = '''from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

if governance_import not in service_text:
    import_anchor = (
        "from app.services.content_service "
        "import ContentService\n"
    )

    if import_anchor not in service_text:
        raise RuntimeError(
            "Importacao de ContentService nao localizada."
        )

    service_text = service_text.replace(
        import_anchor,
        import_anchor + governance_import,
        1,
    )


if 'generation_type="standard"' not in service_text:
    service_text = scoped_replace(
        text=service_text,
        start_marker=(
            "    def generate_sales_content("
        ),
        end_marker=(
            "\n\naffiliate_service ="
        ),
        pattern=(
            r"\n        content = AffiliateContent\("
            r".*?"
            r"\n        return content"
        ),
        replacement='''

        content, duplicate = create_governed_content(
            db=db,
            product=product,
            platform=platform,
            data=final_data,
            generation_type="standard",
        )

        print(
            "[AFFILIATE] Conteudo governado salvo. "
            f"Duplicado: {duplicate}"
        )

        return content''',
        label="Persistencia do gerador principal",
    )


write(
    SERVICE_PATH,
    service_text,
)

print(
    "[OK] Gerador principal integrado."
)


# ============================================================
# 2. GERADORES MANUAIS
# ============================================================

manual_text = read(MANUAL_PATH)

manual_governance_import = '''from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

if manual_governance_import not in manual_text:
    import_anchor = (
        "from app.schemas.affiliate "
        "import ProductCreate\n"
    )

    if import_anchor not in manual_text:
        raise RuntimeError(
            "Importacao de ProductCreate "
            "nao localizada."
        )

    manual_text = manual_text.replace(
        import_anchor,
        import_anchor + manual_governance_import,
        1,
    )


if '"language": content.language' not in manual_text:
    serialization_anchor = '''        "seo_tags": content.seo_tags,
        "status": content.status.value if content.status else None,
'''

    serialization_replacement = '''        "seo_tags": content.seo_tags,
        "language": content.language,
        "disclosure": content.disclosure,
        "content_fingerprint": content.content_fingerprint,
        "generation_type": content.generation_type,
        "review_notes": content.review_notes,
        "reviewed_at": (
            content.reviewed_at.isoformat()
            if content.reviewed_at
            else None
        ),
        "approved_at": (
            content.approved_at.isoformat()
            if content.approved_at
            else None
        ),
        "status": content.status.value if content.status else None,
'''

    if serialization_anchor not in manual_text:
        raise RuntimeError(
            "Serializacao de conteudo "
            "nao localizada."
        )

    manual_text = manual_text.replace(
        serialization_anchor,
        serialization_replacement,
        1,
    )


if 'generation_type="smart"' not in manual_text:
    manual_text = scoped_replace(
        text=manual_text,
        start_marker=(
            "def generate_smart_affiliate_content("
        ),
        end_marker=(
            "\n\nfrom typing import List as PitchList"
        ),
        pattern=(
            r"\n    content = AffiliateContent\("
            r".*?"
            r"\n    return _serialize_content\(content\)"
        ),
        replacement='''

    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data={
            "hook_1": hook_1,
            "hook_2": hook_2,
            "script": script,
            "caption": caption,
            "trigger_keyword": trigger_keyword,
            "seo_tags": seo_tags,
        },
        generation_type="smart",
    )

    return _serialize_content(content)''',
        label="Persistencia do gerador smart",
    )


if 'generation_type="pitch"' not in manual_text:
    manual_text = scoped_replace(
        text=manual_text,
        start_marker=(
            "def generate_pitch_affiliate_content("
        ),
        end_marker=(
            "\n\n\ndef _detect_pitch_profile_v2"
        ),
        pattern=(
            r"\n    content = AffiliateContent\("
            r".*?"
            r"\n    return _serialize_content\(content\)"
        ),
        replacement='''

    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data={
            "hook_1": hook_1,
            "hook_2": hook_2,
            "script": script,
            "caption": caption,
            "trigger_keyword": trigger_keyword,
            "seo_tags": seo_tags,
        },
        generation_type="pitch",
    )

    return _serialize_content(content)''',
        label="Persistencia do gerador pitch",
    )


if 'generation_type="analysis"' not in manual_text:
    manual_text = scoped_replace(
        text=manual_text,
        start_marker=(
            "def generate_content_from_analysis("
        ),
        end_marker="",
        pattern=(
            r"\n    content = AffiliateContent\("
            r".*?"
            r"\n    db\.refresh\(content\)"
        ),
        replacement='''

    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data=generated,
        generation_type="analysis",
    )''',
        label=(
            "Persistencia do gerador "
            "generate-from-analysis"
        ),
    )


write(
    MANUAL_PATH,
    manual_text,
)

print(
    "[OK] Geradores smart, pitch e analysis integrados."
)


# ============================================================
# 3. DISCLOSURE VISUAL
# ============================================================

video_text = read(VIDEO_PATH)

if "content.disclosure or theme" not in video_text:
    video_pattern = (
        r'    disclaimer = _wrap_limited\('
        r'theme\["disclaimer"\], '
        r'chars_per_line=42, max_lines=2\)'
    )

    video_replacement = '''    disclaimer = _wrap_limited(
        content.disclosure or theme["disclaimer"],
        chars_per_line=42,
        max_lines=2,
    )'''

    video_text = replace_once_regex(
        video_text,
        video_pattern,
        video_replacement,
        "Disclosure visual no Video Engine",
    )


if "ContentStatusEnum.APPROVED.value" not in video_text:
    raise RuntimeError(
        "A protecao do Passo 4A nao foi "
        "localizada no Video Engine."
    )


write(
    VIDEO_PATH,
    video_text,
)

print(
    "[OK] Disclosure visual integrado."
)


# ============================================================
# 4. VERIFICACAO DA PARTE JA APLICADA
# ============================================================

model_text = read(MODEL_PATH)

if "content_fingerprint = Column(" not in model_text:
    raise RuntimeError(
        "Campo content_fingerprint ausente no modelo."
    )

if "unique=True" not in model_text:
    raise RuntimeError(
        "Fingerprint ainda nao esta unico no modelo."
    )


schema_text = read(SCHEMA_PATH)

required_schema_fields = [
    "language: Optional[str]",
    "disclosure: Optional[str]",
    "content_fingerprint: Optional[str]",
    "generation_type: Optional[str]",
]

for field in required_schema_fields:
    if field not in schema_text:
        raise RuntimeError(
            f"Campo ausente no schema: {field}"
        )


repository_text = read(REPOSITORY_PATH)

if 'generation_type="repository"' not in repository_text:
    raise RuntimeError(
        "Repository nao esta integrado "
        "ao servico de governanca."
    )


governance_text = read(GOVERNANCE_PATH)

required_governance_markers = [
    "DISCLOSURE_BR",
    "DISCLOSURE_US",
    "def content_fingerprint(",
    "def create_governed_content(",
    "hashlib.sha256",
]

for marker in required_governance_markers:
    if marker not in governance_text:
        raise RuntimeError(
            f"Marcador de governanca ausente: {marker}"
        )


# ============================================================
# 5. MIGRACAO DE DEDUPLICACAO
# ============================================================

migration_code = '''"""affiliate content deduplication

Revision ID: a7d19c4e2f60
Revises: f4c2a1d9e7b0
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a7d19c4e2f60"
down_revision: Union[str, None] = "f4c2a1d9e7b0"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT content_fingerprint
                FROM affiliate_contents
                WHERE content_fingerprint IS NOT NULL
                GROUP BY content_fingerprint
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Existem fingerprints duplicados.';
            END IF;
        END
        $$;
        """
    )

    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=False,
    )
'''

write(
    MIGRATION_PATH,
    migration_code,
)

print(
    "[OK] Migracao a7d19c4e2f60 gravada."
)


# ============================================================
# 6. VERIFICACAO FINAL DOS ARQUIVOS
# ============================================================

service_check = read(SERVICE_PATH)
manual_check = read(MANUAL_PATH)
video_check = read(VIDEO_PATH)

required_integrations = [
    (
        service_check,
        'generation_type="standard"',
        "standard",
    ),
    (
        manual_check,
        'generation_type="smart"',
        "smart",
    ),
    (
        manual_check,
        'generation_type="pitch"',
        "pitch",
    ),
    (
        manual_check,
        'generation_type="analysis"',
        "analysis",
    ),
    (
        video_check,
        "content.disclosure or theme",
        "video disclosure",
    ),
]

for source, marker, label in required_integrations:
    if marker not in source:
        raise RuntimeError(
            f"Integracao ausente: {label}"
        )


print(
    "[OK] Reparacao dos arquivos concluida."
)