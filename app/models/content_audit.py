from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.core.database import Base


class ContentAuditLog(Base):
    __tablename__ = (
        "affiliate_content_audit_logs"
    )

    __table_args__ = (
        Index(
            "ix_affiliate_content_audit_content_created",
            "content_id",
            "created_at",
        ),
        Index(
            "ix_affiliate_content_audit_actor_created",
            "actor_user_id",
            "created_at",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    content_id = Column(
        Integer,
        ForeignKey(
            "affiliate_contents.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    actor_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    action = Column(
        String(50),
        nullable=False,
    )

    from_status = Column(
        String(30),
        nullable=True,
    )

    to_status = Column(
        String(30),
        nullable=True,
    )

    notes = Column(
        Text,
        nullable=True,
    )

    details = Column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
