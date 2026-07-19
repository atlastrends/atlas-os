from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
)


class UserRole(str, Enum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    CREATOR = "creator"


class UserBase(BaseModel):
    email: str
    name: str
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = str(
            value or ""
        ).strip().lower()

        if not normalized or "@" not in normalized:
            raise ValueError(
                "Informe um e-mail valido."
            )

        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = str(
            value or ""
        ).strip()

        if not normalized:
            raise ValueError(
                "O nome nao pode ser vazio."
            )

        return normalized


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        password = str(value or "")

        if len(password) < 12:
            raise ValueError(
                "A senha deve possuir pelo menos "
                "12 caracteres."
            )

        return password


class UserUpdate(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None

    @field_validator("email")
    @classmethod
    def normalize_optional_email(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None

        normalized = str(
            value
        ).strip().lower()

        if not normalized or "@" not in normalized:
            raise ValueError(
                "Informe um e-mail valido."
            )

        return normalized

    @field_validator("name")
    @classmethod
    def normalize_optional_name(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None

        normalized = str(
            value
        ).strip()

        if not normalized:
            raise ValueError(
                "O nome nao pode ser vazio."
            )

        return normalized


class UserResponse(UserBase):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: int
    role: UserRole
    created_at: datetime
    updated_at: datetime
