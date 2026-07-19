from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import (
    VALID_USER_ROLES,
    User,
)
from app.schemas.user import (
    UserCreate,
    UserUpdate,
)
from app.security.password import (
    get_password_hash,
)


class UserRepository:
    @staticmethod
    def get(
        db: Session,
        user_id: int,
    ) -> User | None:
        stmt = select(User).where(
            User.id == user_id
        )

        return (
            db.execute(stmt)
            .scalars()
            .first()
        )

    @staticmethod
    def get_by_email(
        db: Session,
        email: str,
    ) -> User | None:
        normalized_email = str(
            email or ""
        ).strip().lower()

        stmt = select(User).where(
            User.email == normalized_email
        )

        return (
            db.execute(stmt)
            .scalars()
            .first()
        )

    @staticmethod
    def count(
        db: Session,
    ) -> int:
        stmt = select(
            func.count(User.id)
        )

        return int(
            db.execute(stmt).scalar_one()
        )

    @staticmethod
    def get_all(
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        stmt = (
            select(User)
            .order_by(User.id.asc())
            .offset(skip)
            .limit(limit)
        )

        return list(
            db.execute(stmt)
            .scalars()
            .all()
        )

    @staticmethod
    def normalize_role(
        role,
    ) -> str:
        raw_value = getattr(
            role,
            "value",
            role,
        )

        normalized = str(
            raw_value or ""
        ).strip().lower()

        if normalized not in VALID_USER_ROLES:
            raise ValueError(
                "Papel invalido. Use admin, "
                "reviewer ou creator."
            )

        return normalized

    @staticmethod
    def create(
        db: Session,
        user_in: UserCreate,
        role: str = "creator",
    ) -> User:
        normalized_role = (
            UserRepository.normalize_role(role)
        )

        db_user = User(
            email=user_in.email,
            name=user_in.name,
            is_active=user_in.is_active,
            role=normalized_role,
            hashed_password=get_password_hash(
                user_in.password
            ),
        )

        db.add(db_user)

        try:
            db.commit()
            db.refresh(db_user)
            return db_user

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def update(
        db: Session,
        db_user: User,
        user_in: UserUpdate,
    ) -> User:
        update_data = user_in.model_dump(
            exclude_unset=True
        )

        if "role" in update_data:
            update_data["role"] = (
                UserRepository.normalize_role(
                    update_data["role"]
                )
            )

        for field, value in update_data.items():
            setattr(
                db_user,
                field,
                value,
            )

        try:
            db.commit()
            db.refresh(db_user)
            return db_user

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def delete(
        db: Session,
        db_user: User,
    ) -> User:
        db.delete(db_user)

        try:
            db.commit()
            return db_user

        except Exception:
            db.rollback()
            raise


user_repository = UserRepository()
