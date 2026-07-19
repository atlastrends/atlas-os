from fastapi import (
    Depends,
    HTTPException,
    status,
)
from fastapi.security import OAuth2PasswordBearer
import jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.repositories.user import user_repository
from app.schemas.token import TokenPayload
from app.security.jwt import (
    ALGORITHM,
    SECRET_KEY,
)


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="login/access-token"
)


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalido ou expirado.",
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )

        token_data = TokenPayload(**payload)

        if token_data.sub is None:
            raise credentials_error

        user_id = int(token_data.sub)

    except (
        jwt.PyJWTError,
        ValidationError,
        TypeError,
        ValueError,
    ):
        raise credentials_error

    user = user_repository.get(
        db,
        user_id,
    )

    if not user:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo.",
        )

    return user
