from typing import Optional

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
