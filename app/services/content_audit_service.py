from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.affiliate import AffiliateContent
from app.models.content_audit import ContentAuditLog
from app.models.user import User


def status_value(value) -> Optional[str]:
    if value is None:
        return None

    raw_value = getattr(
        value,
        "value",
        value,
    )

    normalized = str(
        raw_value or ""
    ).strip()

    return normalized or None


def record_content_audit(
    db: Session,
    *,
    action: str,
    actor: Optional[User] = None,
    content: Optional[AffiliateContent] = None,
    from_status=None,
    to_status=None,
    notes: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> ContentAuditLog:
    normalized_action = str(
        action or ""
    ).strip().lower()

    if not normalized_action:
        raise ValueError(
            "A acao de auditoria e obrigatoria."
        )

    log = ContentAuditLog(
        content_id=(
            content.id
            if content is not None
            else None
        ),
        actor_user_id=(
            actor.id
            if actor is not None
            else None
        ),
        action=normalized_action[:50],
        from_status=status_value(
            from_status
        ),
        to_status=status_value(
            to_status
        ),
        notes=(
            str(notes).strip()
            if notes
            else None
        ),
        details=details or {},
    )

    db.add(log)
    db.flush()

    return log
