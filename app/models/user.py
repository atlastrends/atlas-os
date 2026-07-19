from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    String,
    func,
)

from app.core.database import Base


VALID_USER_ROLES = {
    "admin",
    "reviewer",
    "creator",
}


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'reviewer', 'creator')",
            name="ck_users_role",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    email = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    name = Column(
        String,
        nullable=False,
    )

    hashed_password = Column(
        String(255),
        nullable=False,
    )

    is_active = Column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    role = Column(
        String(20),
        default="creator",
        server_default="creator",
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
