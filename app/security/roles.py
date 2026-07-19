from collections.abc import Callable

from fastapi import (
    Depends,
    HTTPException,
    status,
)

from app.models.user import (
    VALID_USER_ROLES,
    User,
)
from app.security.deps import get_current_user


def normalize_role(value) -> str:
    raw_value = getattr(
        value,
        "value",
        value,
    )

    return str(
        raw_value or ""
    ).strip().lower()


def require_roles(
    *allowed_roles: str,
) -> Callable:
    normalized_roles = {
        normalize_role(role)
        for role in allowed_roles
    }

    if not normalized_roles:
        raise ValueError(
            "Informe ao menos um papel permitido."
        )

    invalid_roles = (
        normalized_roles
        - VALID_USER_ROLES
    )

    if invalid_roles:
        raise ValueError(
            "Papeis invalidos: "
            + ", ".join(
                sorted(invalid_roles)
            )
        )

    def dependency(
        current_user: User = Depends(
            get_current_user
        ),
    ) -> User:
        current_role = normalize_role(
            current_user.role
        )

        if current_role not in normalized_roles:
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "Usuario sem permissao "
                    "para esta operacao."
                ),
            )

        return current_user

    return dependency


require_admin = require_roles(
    "admin"
)

require_reviewer = require_roles(
    "admin",
    "reviewer",
)

require_creator = require_roles(
    "admin",
    "creator",
)

require_content_reader = require_roles(
    "admin",
    "reviewer",
    "creator",
)
