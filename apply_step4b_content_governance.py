from datetime import datetime
from pathlib import Path
import shutil


ROOT = Path("/atlas")

MODEL_PATH = ROOT / "app/models/affiliate.py"
SCHEMA_PATH = ROOT / "app/schemas/affiliate.py"
REPOSITORY_PATH = ROOT / "app/repositories/affiliate.py"

SERVICE_PATH = (
    ROOT
    / "app/services"
    / "affiliate_service.py"
)

GOVERNANCE_PATH = (
    ROOT
    / "app/services"
    / "affiliate_content_governance.py"
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

MIGRATION_PATH = (
    ROOT
    / "alembic/versions"
    / "a7d19c4e2f60_affiliate_content_deduplication.py"
)


required_files = [
    MODEL_PATH,
    SCHEMA_PATH,
    REPOSITORY_PATH,
    SERVICE_PATH,
    MANUAL_PATH,
    VIDEO_PATH,
]

for path in required_files:
    if not path.is_file():
        raise RuntimeError(
            f"Arquivo obrigatorio nao encontrado: {path}"
        )


timestamp = datetime.utcnow().strftime(
    "%Y%m%d_%H%M%S"
)


def backup(path: Path) -> None:
    if not path.exists():
        return

    destination = Path(
        str(path)
        + f".before_step4b_{timestamp}.bak"
    )

    shutil.copy2(
        path,
        destination,
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


def replace_once(
    content: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = content.count(old)

    if count != 1:
        raise RuntimeError(
            f"{label}: esperado 1 bloco, "
            f"encontrado {count}."
        )

    return content.replace(
        old,
        new,
        1,
    )


for path in required_files:
    backup(path)

backup(GOVERNANCE_PATH)
backup(MIGRATION_PATH)


# ============================================================
# 1. SERVICO CENTRAL DE GOVERNANCA
# ============================================================

governance_code = '''import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    ContentStatusEnum,
    MarketplaceEnum,
)


DISCLOSURE_BR = (
    "Publicidade. Como associado da Amazon, "
    "eu ganho com compras qualificadas."
)

DISCLOSURE_US = (
    "Ad. As an Amazon Associate I earn "
    "from qualifying purchases."
)


def normalize_platform(
    value: Optional[str],
) -> str:
    normalized = str(
        value or "tiktok"
    ).strip().lower()

    aliases = {
        "tik": "tiktok",
        "tik tok": "tiktok",
        "tik-tok": "tiktok",
        "tt": "tiktok",
        "insta": "instagram",
        "ig": "instagram",
        "instagram reels": "instagram",
        "reels": "instagram",
        "yt": "youtube",
        "youtube shorts": "youtube",
        "shorts": "youtube",
        "fb": "facebook",
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    allowed = {
        "tiktok",
        "instagram",
        "youtube",
        "facebook",
    }

    if normalized not in allowed:
        raise ValueError(
            "Plataforma invalida. Use tiktok, "
            "instagram, youtube ou facebook."
        )

    return normalized


def marketplace_value(
    product: AffiliateProduct,
) -> str:
    marketplace = product.marketplace

    raw_value = getattr(
        marketplace,
        "value",
        marketplace,
    )

    return str(
        raw_value or ""
    ).strip().lower()


def governance_for_product(
    product: AffiliateProduct,
) -> Tuple[str, str]:
    marketplace = marketplace_value(product)

    if marketplace == MarketplaceEnum.AMAZON_US.value:
        return "en-US", DISCLOSURE_US

    return "pt-BR", DISCLOSURE_BR


def clean_text(
    value: Any,
) -> str:
    return re.sub(
        r"\\s+",
        " ",
        str(value or "").strip(),
    )


def optional_text(
    value: Any,
) -> Optional[str]:
    cleaned = clean_text(value)
    return cleaned or None


def add_disclosure(
    value: Any,
    disclosure: str,
) -> str:
    text = clean_text(value)
    disclosure_clean = clean_text(disclosure)

    if not text:
        return disclosure_clean

    if disclosure_clean.lower() in text.lower():
        return text

    return (
        disclosure_clean
        + "\\n\\n"
        + text
    )


def content_fingerprint(
    product_id: int,
    platform: str,
    data: Dict[str, Any],
) -> str:
    canonical = {
        "product_id": int(product_id),
        "platform": clean_text(platform).lower(),
        "hook_1": clean_text(
            data.get("hook_1")
        ).lower(),
        "hook_2": clean_text(
            data.get("hook_2")
        ).lower(),
        "script": clean_text(
            data.get("script")
        ).lower(),
        "caption": clean_text(
            data.get("caption")
        ).lower(),
        "trigger_keyword": clean_text(
            data.get("trigger_keyword")
        ).upper(),
        "seo_tags": clean_text(
            data.get("seo_tags")
        ).lower(),
        "language": clean_text(
            data.get("language")
        ).lower(),
        "disclosure": clean_text(
            data.get("disclosure")
        ).lower(),
    }

    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def prepare_content_data(
    product: AffiliateProduct,
    platform: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    language, disclosure = governance_for_product(
        product
    )

    normalized_platform = normalize_platform(
        platform
    )

    script = add_disclosure(
        data.get("script"),
        disclosure,
    )

    caption = add_disclosure(
        data.get("caption"),
        disclosure,
    )

    if not clean_text(script):
        raise ValueError(
            "O roteiro nao pode ser vazio."
        )

    prepared = {
        "platform": normalized_platform,
        "hook_1": optional_text(
            data.get("hook_1")
        ),
        "hook_2": optional_text(
            data.get("hook_2")
        ),
        "script": script,
        "caption": caption,
        "trigger_keyword": optional_text(
            data.get("trigger_keyword")
        ),
        "seo_tags": optional_text(
            data.get("seo_tags")
        ),
        "language": language,
        "disclosure": disclosure,
    }

    prepared["content_fingerprint"] = (
        content_fingerprint(
            product_id=product.id,
            platform=normalized_platform,
            data=prepared,
        )
    )

    return prepared


def find_by_fingerprint(
    db: Session,
    fingerprint: str,
) -> Optional[AffiliateContent]:
    return (
        db.query(AffiliateContent)
        .filter(
            AffiliateContent.content_fingerprint
            == fingerprint
        )
        .first()
    )


def create_governed_content(
    db: Session,
    product: AffiliateProduct,
    platform: str,
    data: Dict[str, Any],
    generation_type: str,
) -> Tuple[AffiliateContent, bool]:
    prepared = prepare_content_data(
        product=product,
        platform=platform,
        data=data,
    )

    fingerprint = prepared[
        "content_fingerprint"
    ]

    existing = find_by_fingerprint(
        db=db,
        fingerprint=fingerprint,
    )

    if existing is not None:
        print(
            "[AFFILIATE GOVERNANCE] "
            f"Conteudo duplicado reutilizado: "
            f"{existing.id}",
            flush=True,
        )

        return existing, True

    normalized_generation_type = clean_text(
        generation_type
    )[:30] or "unknown"

    content = AffiliateContent(
        product_id=product.id,
        platform=prepared["platform"],
        hook_1=prepared["hook_1"],
        hook_2=prepared["hook_2"],
        script=prepared["script"],
        caption=prepared["caption"],
        trigger_keyword=(
            prepared["trigger_keyword"]
        ),
        seo_tags=prepared["seo_tags"],
        language=prepared["language"],
        disclosure=prepared["disclosure"],
        content_fingerprint=fingerprint,
        generation_type=(
            normalized_generation_type
        ),
        status=ContentStatusEnum.DRAFT,
    )

    db.add(content)

    try:
        db.commit()
        db.refresh(content)

        print(
            "[AFFILIATE GOVERNANCE] "
            f"Conteudo criado: {content.id}",
            flush=True,
        )

        return content, False

    except IntegrityError:
        db.rollback()

        existing = find_by_fingerprint(
            db=db,
            fingerprint=fingerprint,
        )

        if existing is not None:
            print(
                "[AFFILIATE GOVERNANCE] "
                "Concorrencia de deduplicacao "
                f"resolvida com conteudo {existing.id}.",
                flush=True,
            )

            return existing, True

        raise

    except Exception:
        db.rollback()
        raise
'''

write(
    GOVERNANCE_PATH,
    governance_code,
)

print(
    "[OK] Servico central de governanca gravado."
)


# ============================================================
# 2. MODELO: FINGERPRINT UNICO
# ============================================================

model_text = read(MODEL_PATH)

old_fingerprint_column = '''    content_fingerprint = Column(
        String(64),
        nullable=True,
        index=True,
    )
'''

new_fingerprint_column = '''    content_fingerprint = Column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
'''

if "unique=True,\n        index=True," not in model_text:
    model_text = replace_once(
        model_text,
        old_fingerprint_column,
        new_fingerprint_column,
        "Fingerprint unico no modelo",
    )

write(
    MODEL_PATH,
    model_text,
)

print(
    "[OK] Modelo configurado para fingerprint unico."
)


# ============================================================
# 3. SCHEMA DE RESPOSTA
# ============================================================

schema_text = read(SCHEMA_PATH)

if "content_fingerprint: Optional[str]" not in schema_text:
    schema_anchor = '''    seo_tags: Optional[str] = None
    status: ContentStatusEnum
    created_at: datetime
'''

    schema_replacement = '''    seo_tags: Optional[str] = None
    language: Optional[str] = None
    disclosure: Optional[str] = None
    content_fingerprint: Optional[str] = None
    generation_type: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    status: ContentStatusEnum
    created_at: datetime
    updated_at: Optional[datetime] = None
'''

    schema_text = replace_once(
        schema_text,
        schema_anchor,
        schema_replacement,
        "Campos de governanca no schema",
    )

write(
    SCHEMA_PATH,
    schema_text,
)

print(
    "[OK] Schema ContentResponse atualizado."
)


# ============================================================
# 4. REPOSITORY
# ============================================================

repository_text = read(REPOSITORY_PATH)

repository_import = '''from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

if repository_import not in repository_text:
    import_anchor = '''from app.services.amazon_link_validation import (
    validate_amazon_product_links,
)
'''

    import_replacement = '''from app.services.amazon_link_validation import (
    validate_amazon_product_links,
)
from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

    repository_text = replace_once(
        repository_text,
        import_anchor,
        import_replacement,
        "Importacao da governanca no repository",
    )


old_repository_save = '''        content = AffiliateContent(
            product_id=product_id,
            platform=str(platform or "").strip().lower(),
            hook_1=ai_data.get("hook_1"),
            hook_2=ai_data.get("hook_2"),
            script=ai_data.get("script"),
            caption=ai_data.get("caption"),
            trigger_keyword=ai_data.get("trigger_keyword"),
            seo_tags=ai_data.get("seo_tags"),
            status=ContentStatusEnum.DRAFT,
        )

        db.add(content)

        try:
            db.commit()
            db.refresh(content)
            return content
        except Exception:
            db.rollback()
            raise
'''

new_repository_save = '''        product = self.get_product(
            db=db,
            product_id=product_id,
        )

        if not product:
            raise ValueError(
                f"Produto ID {product_id} nao encontrado."
            )

        content, _ = create_governed_content(
            db=db,
            product=product,
            platform=platform,
            data=ai_data,
            generation_type="repository",
        )

        return content
'''

if old_repository_save in repository_text:
    repository_text = replace_once(
        repository_text,
        old_repository_save,
        new_repository_save,
        "Persistencia governada no repository",
    )
elif (
    'generation_type="repository"' not in
    repository_text
):
    raise RuntimeError(
        "O metodo save_content do repository "
        "nao corresponde ao estado esperado."
    )

write(
    REPOSITORY_PATH,
    repository_text,
)

print(
    "[OK] Repository integrado a governanca."
)


# ============================================================
# 5. GERADOR PRINCIPAL
# ============================================================

service_text = read(SERVICE_PATH)

service_import = '''from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

if service_import not in service_text:
    import_anchor = (
        "from app.services.content_service "
        "import ContentService\n"
    )

    import_replacement = '''from app.services.content_service import ContentService
from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

    service_text = replace_once(
        service_text,
        import_anchor,
        import_replacement,
        "Importacao da governanca no gerador principal",
    )


old_service_save = '''        content = AffiliateContent(
            product_id=product.id,
            platform=platform,
            hook_1=final_data["hook_1"],
            hook_2=final_data["hook_2"],
            script=final_data["script"],
            caption=final_data["caption"],
            trigger_keyword=final_data["trigger_keyword"],
            seo_tags=final_data["seo_tags"],
            status="draft",
        )

        db.add(content)
        db.commit()
        db.refresh(content)

        print("Ô£à [AFFILIATE] Conte├║do gerado e salvo com sucesso.")
        return content
'''

new_service_save = '''        content, duplicate = create_governed_content(
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

        return content
'''

if old_service_save in service_text:
    service_text = replace_once(
        service_text,
        old_service_save,
        new_service_save,
        "Persistencia do gerador principal",
    )
elif (
    'generation_type="standard"' not in
    service_text
):
    raise RuntimeError(
        "O bloco de persistencia do gerador "
        "principal nao foi localizado."
    )

write(
    SERVICE_PATH,
    service_text,
)

print(
    "[OK] Gerador principal integrado."
)


# ============================================================
# 6. GERADORES SMART, PITCH E ANALYSIS
# ============================================================

manual_text = read(MANUAL_PATH)

manual_import = '''from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

if manual_import not in manual_text:
    import_anchor = '''from app.repositories.affiliate import affiliate_repo
from app.schemas.affiliate import ProductCreate
'''

    import_replacement = '''from app.repositories.affiliate import affiliate_repo
from app.schemas.affiliate import ProductCreate
from app.services.affiliate_content_governance import (
    create_governed_content,
)
'''

    manual_text = replace_once(
        manual_text,
        import_anchor,
        import_replacement,
        "Importacao da governanca nos geradores manuais",
    )


if '"language": content.language' not in manual_text:
    serialize_anchor = '''        "seo_tags": content.seo_tags,
        "status": content.status.value if content.status else None,
'''

    serialize_replacement = '''        "seo_tags": content.seo_tags,
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

    manual_text = replace_once(
        manual_text,
        serialize_anchor,
        serialize_replacement,
        "Serializacao dos campos de governanca",
    )


old_smart_save = '''    content = AffiliateContent(
        product_id=product.id,
        platform=platform,
        hook_1=hook_1,
        hook_2=hook_2,
        script=script,
        caption=caption,
        trigger_keyword=trigger_keyword,
        seo_tags=seo_tags,
        status=ContentStatusEnum.DRAFT,
    )

    db.add(content)
    db.commit()
    db.refresh(content)

    return _serialize_content(content)
'''

new_smart_save = '''    content, _ = create_governed_content(
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

    return _serialize_content(content)
'''

if old_smart_save in manual_text:
    manual_text = replace_once(
        manual_text,
        old_smart_save,
        new_smart_save,
        "Persistencia do gerador smart",
    )
elif (
    'generation_type="smart"' not in
    manual_text
):
    raise RuntimeError(
        "O bloco do gerador smart nao foi localizado."
    )


old_pitch_save = '''    content = AffiliateContent(
        product_id=product.id,
        platform=platform,
        hook_1=hook_1,
        hook_2=hook_2,
        script=script,
        caption=caption,
        trigger_keyword=trigger_keyword,
        seo_tags=seo_tags,
        status=ContentStatusEnum.DRAFT,
    )

    db.add(content)
    db.commit()
    db.refresh(content)

    return _serialize_content(content)
'''

new_pitch_save = '''    content, _ = create_governed_content(
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

    return _serialize_content(content)
'''

if old_pitch_save in manual_text:
    manual_text = replace_once(
        manual_text,
        old_pitch_save,
        new_pitch_save,
        "Persistencia do gerador pitch",
    )
elif (
    'generation_type="pitch"' not in
    manual_text
):
    raise RuntimeError(
        "O bloco do gerador pitch nao foi localizado."
    )


old_analysis_save = '''    content = AffiliateContent(
        product_id=product.id,
        platform=platform,
        hook_1=generated["hook_1"],
        hook_2=generated["hook_2"],
        script=generated["script"],
        caption=generated["caption"],
        trigger_keyword=generated["trigger_keyword"],
        seo_tags=generated["seo_tags"],
        status=ContentStatusEnum.DRAFT,
    )

    db.add(content)
    db.commit()
    db.refresh(content)

    return {
'''

new_analysis_save = '''    content, _ = create_governed_content(
        db=db,
        product=product,
        platform=platform,
        data=generated,
        generation_type="analysis",
    )

    return {
'''

if old_analysis_save in manual_text:
    manual_text = replace_once(
        manual_text,
        old_analysis_save,
        new_analysis_save,
        "Persistencia do gerador analysis",
    )
elif (
    'generation_type="analysis"' not in
    manual_text
):
    raise RuntimeError(
        "O bloco do gerador analysis "
        "nao foi localizado."
    )

write(
    MANUAL_PATH,
    manual_text,
)

print(
    "[OK] Geradores smart, pitch e analysis integrados."
)


# ============================================================
# 7. DISCLOSURE VISUAL NO VIDEO
# ============================================================

video_text = read(VIDEO_PATH)

old_video_disclaimer = '''    disclaimer = _wrap_limited(theme["disclaimer"], chars_per_line=42, max_lines=2)
'''

new_video_disclaimer = '''    disclaimer = _wrap_limited(
        content.disclosure or theme["disclaimer"],
        chars_per_line=42,
        max_lines=2,
    )
'''

if old_video_disclaimer in video_text:
    video_text = replace_once(
        video_text,
        old_video_disclaimer,
        new_video_disclaimer,
        "Disclosure visual no video",
    )
elif (
    "content.disclosure or theme" not in
    video_text
):
    raise RuntimeError(
        "O disclaimer do Video Engine "
        "nao foi localizado."
    )

write(
    VIDEO_PATH,
    video_text,
)

print(
    "[OK] Disclosure visual integrado ao video."
)


# ============================================================
# 8. MIGRACAO DE INDICE UNICO
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
    "[OK] Migracao de deduplicacao gravada."
)

print(
    "[OK] Preparacao do Passo 4B concluida."
)