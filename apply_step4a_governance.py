from datetime import datetime
from pathlib import Path
import shutil


ROOT = Path("/atlas")

MODEL_PATH = ROOT / "app/models/affiliate.py"
MAIN_PATH = ROOT / "app/main.py"
VIDEO_PATH = ROOT / "app/routers/affiliate_video.py"

ROUTER_PATH = (
    ROOT
    / "app/routers"
    / "affiliate_content_review.py"
)

MIGRATION_PATH = (
    ROOT
    / "alembic/versions"
    / "f4c2a1d9e7b0_affiliate_content_governance.py"
)


required_files = [
    MODEL_PATH,
    MAIN_PATH,
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
        + f".before_step4a_{timestamp}.bak"
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

backup(ROUTER_PATH)
backup(MIGRATION_PATH)


# ============================================================
# 1. MODELO AFFILIATE CONTENT
# ============================================================

model_text = read(MODEL_PATH)

if "content_fingerprint = Column(" not in model_text:
    model_anchor = '''    seo_tags = Column(
        String,
        nullable=True,
    )

    status = Column(
'''

    model_replacement = '''    seo_tags = Column(
        String,
        nullable=True,
    )

    language = Column(
        String(10),
        nullable=True,
    )

    disclosure = Column(
        Text,
        nullable=True,
    )

    content_fingerprint = Column(
        String(64),
        nullable=True,
        index=True,
    )

    generation_type = Column(
        String(30),
        nullable=True,
    )

    review_notes = Column(
        Text,
        nullable=True,
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    status = Column(
'''

    model_text = replace_once(
        model_text,
        model_anchor,
        model_replacement,
        "Campos de governanca no modelo",
    )

    write(
        MODEL_PATH,
        model_text,
    )

    print(
        "[OK] Modelo AffiliateContent atualizado."
    )
else:
    print(
        "[OK] Modelo ja possui campos de governanca."
    )


# ============================================================
# 2. ROUTER DE REVISAO E APROVACAO
# ============================================================

router_code = '''from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.core.database import get_db
from app.models.affiliate import (
    AffiliateContent,
    ContentStatusEnum,
)


router = APIRouter(
    prefix="/affiliate/content",
    tags=["Affiliate Content Review"],
)


class ContentReviewRequest(BaseModel):
    notes: Optional[str] = Field(
        default=None,
        max_length=4000,
    )


def _status_value(
    content: AffiliateContent,
) -> str:
    status = content.status

    return (
        status.value
        if hasattr(status, "value")
        else str(status or "")
    )


def _serialize(
    content: AffiliateContent,
) -> dict:
    return {
        "id": content.id,
        "product_id": content.product_id,
        "platform": content.platform,
        "hook_1": content.hook_1,
        "hook_2": content.hook_2,
        "script": content.script,
        "caption": content.caption,
        "trigger_keyword": (
            content.trigger_keyword
        ),
        "seo_tags": content.seo_tags,
        "language": content.language,
        "disclosure": content.disclosure,
        "content_fingerprint": (
            content.content_fingerprint
        ),
        "generation_type": (
            content.generation_type
        ),
        "status": _status_value(content),
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
        "created_at": (
            content.created_at.isoformat()
            if content.created_at
            else None
        ),
        "updated_at": (
            content.updated_at.isoformat()
            if content.updated_at
            else None
        ),
    }


def _get_content(
    db: Session,
    content_id: int,
) -> AffiliateContent:
    content = (
        db.query(AffiliateContent)
        .filter(
            AffiliateContent.id == content_id
        )
        .first()
    )

    if not content:
        raise HTTPException(
            status_code=404,
            detail="Conteudo nao encontrado.",
        )

    return content


def _clean_notes(
    payload: ContentReviewRequest,
) -> Optional[str]:
    notes = str(
        payload.notes or ""
    ).strip()

    return notes or None


@router.get("/{content_id}")
def get_content_for_review(
    content_id: int,
    db: Session = Depends(get_db),
):
    content = _get_content(
        db,
        content_id,
    )

    return {
        "ok": True,
        "content": _serialize(content),
    }


@router.post(
    "/{content_id}/submit-review"
)
def submit_content_for_review(
    content_id: int,
    payload: ContentReviewRequest,
    db: Session = Depends(get_db),
):
    content = _get_content(
        db,
        content_id,
    )

    current_status = _status_value(content)

    allowed_statuses = {
        ContentStatusEnum.DRAFT.value,
        ContentStatusEnum.REJECTED.value,
    }

    if current_status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente conteudo draft ou rejected "
                "pode ser enviado para revisao."
            ),
        )

    if not str(
        content.language or ""
    ).strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "O conteudo nao possui idioma "
                "definido."
            ),
        )

    if not str(
        content.disclosure or ""
    ).strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "O conteudo nao possui disclosure "
                "definido."
            ),
        )

    content.status = (
        ContentStatusEnum.PENDING_REVIEW
    )

    content.review_notes = _clean_notes(
        payload
    )

    content.reviewed_at = None
    content.approved_at = None

    try:
        db.commit()
        db.refresh(content)
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "action": "submitted_for_review",
        "content": _serialize(content),
    }


@router.post("/{content_id}/approve")
def approve_content(
    content_id: int,
    payload: ContentReviewRequest,
    db: Session = Depends(get_db),
):
    content = _get_content(
        db,
        content_id,
    )

    if (
        _status_value(content)
        != ContentStatusEnum.PENDING_REVIEW.value
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente conteudo pending_review "
                "pode ser aprovado."
            ),
        )

    if not str(
        content.disclosure or ""
    ).strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "Disclosure obrigatorio ausente."
            ),
        )

    content.status = ContentStatusEnum.APPROVED

    content.review_notes = _clean_notes(
        payload
    )

    content.reviewed_at = func.now()
    content.approved_at = func.now()

    try:
        db.commit()
        db.refresh(content)
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "action": "approved",
        "content": _serialize(content),
    }


@router.post("/{content_id}/reject")
def reject_content(
    content_id: int,
    payload: ContentReviewRequest,
    db: Session = Depends(get_db),
):
    content = _get_content(
        db,
        content_id,
    )

    if (
        _status_value(content)
        != ContentStatusEnum.PENDING_REVIEW.value
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente conteudo pending_review "
                "pode ser rejeitado."
            ),
        )

    notes = _clean_notes(payload)

    if not notes:
        raise HTTPException(
            status_code=422,
            detail=(
                "Informe o motivo da rejeicao "
                "no campo notes."
            ),
        )

    content.status = ContentStatusEnum.REJECTED
    content.review_notes = notes
    content.reviewed_at = func.now()
    content.approved_at = None

    try:
        db.commit()
        db.refresh(content)
    except Exception:
        db.rollback()
        raise

    return {
        "ok": True,
        "action": "rejected",
        "content": _serialize(content),
    }
'''

write(
    ROUTER_PATH,
    router_code,
)

print(
    "[OK] Router de revisao gravado."
)


# ============================================================
# 3. REGISTRO DO ROUTER NO FASTAPI
# ============================================================

main_text = read(MAIN_PATH)

if "affiliate_content_review," not in main_text:
    import_anchor = '''    affiliate,
    affiliate_manual,
'''

    import_replacement = '''    affiliate,
    affiliate_content_review,
    affiliate_manual,
'''

    main_text = replace_once(
        main_text,
        import_anchor,
        import_replacement,
        "Importacao do router de revisao",
    )


registration_line = (
    "app.include_router("
    "affiliate_content_review.router"
    ")"
)

if registration_line not in main_text:
    registration_anchor = '''app.include_router(affiliate.router)
app.include_router(affiliate_manual.router)
'''

    registration_replacement = '''app.include_router(affiliate.router)
app.include_router(affiliate_content_review.router)
app.include_router(affiliate_manual.router)
'''

    main_text = replace_once(
        main_text,
        registration_anchor,
        registration_replacement,
        "Registro do router de revisao",
    )


write(
    MAIN_PATH,
    main_text,
)

print(
    "[OK] Router registrado no FastAPI."
)


# ============================================================
# 4. BLOQUEIO DO VIDEO ENGINE
# ============================================================

video_text = read(VIDEO_PATH)

old_video_import = (
    "from app.models.affiliate import "
    "AffiliateContent, AffiliateProduct, "
    "MarketplaceEnum"
)

new_video_import = '''from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    ContentStatusEnum,
    MarketplaceEnum,
)'''


if "ContentStatusEnum," not in video_text:
    video_text = replace_once(
        video_text,
        old_video_import,
        new_video_import,
        "Importacao do status no Video Engine",
    )


video_guard_message = (
    "Somente conteudo aprovado pode gerar video."
)

if video_guard_message not in video_text:
    product_anchor = '''    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    theme = _marketplace_theme(product)
'''

    product_replacement = '''    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado.")

    current_status = (
        content.status.value
        if hasattr(content.status, "value")
        else str(content.status or "")
    )

    if current_status != ContentStatusEnum.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail=(
                "Somente conteudo aprovado pode gerar video."
            ),
        )

    theme = _marketplace_theme(product)
'''

    video_text = replace_once(
        video_text,
        product_anchor,
        product_replacement,
        "Bloqueio de video sem aprovacao",
    )


write(
    VIDEO_PATH,
    video_text,
)

print(
    "[OK] Video Engine protegido."
)


# ============================================================
# 5. MIGRACAO ALEMBIC
# ============================================================

migration_code = '''"""affiliate content governance

Revision ID: f4c2a1d9e7b0
Revises: e4b82d7c91aa
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2a1d9e7b0"
down_revision: Union[str, None] = "e4b82d7c91aa"

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
    op.add_column(
        "affiliate_contents",
        sa.Column(
            "language",
            sa.String(length=10),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "disclosure",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "content_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "generation_type",
            sa.String(length=30),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "review_notes",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE affiliate_contents AS content
        SET
            language = CASE
                WHEN product.marketplace::text
                    IN ('AMAZON_US', 'amazon_us')
                    THEN 'en-US'
                ELSE 'pt-BR'
            END,
            disclosure = CASE
                WHEN product.marketplace::text
                    IN ('AMAZON_US', 'amazon_us')
                    THEN
                        'Ad. As an Amazon Associate I earn '
                        'from qualifying purchases.'
                ELSE
                    'Publicidade. Como Associado da Amazon, '
                    'recebo por compras qualificadas.'
            END,
            generation_type = 'legacy'
        FROM affiliate_products AS product
        WHERE product.id = content.product_id
        """
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_product_platform_status",
        "affiliate_contents",
        [
            "product_id",
            "platform",
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_contents_product_platform_status",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.drop_column(
        "affiliate_contents",
        "approved_at",
    )

    op.drop_column(
        "affiliate_contents",
        "reviewed_at",
    )

    op.drop_column(
        "affiliate_contents",
        "review_notes",
    )

    op.drop_column(
        "affiliate_contents",
        "generation_type",
    )

    op.drop_column(
        "affiliate_contents",
        "content_fingerprint",
    )

    op.drop_column(
        "affiliate_contents",
        "disclosure",
    )

    op.drop_column(
        "affiliate_contents",
        "language",
    )
'''

write(
    MIGRATION_PATH,
    migration_code,
)

print(
    "[OK] Migracao de governanca gravada."
)

print(
    "[OK] Preparacao do Passo 4A concluida."
)