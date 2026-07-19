from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.repositories.user import user_repository
from app.schemas.user import (
    UserCreate,
    UserResponse,
)
from app.security.deps import get_current_user


router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_first_admin(
    user_in: UserCreate,
    db: Session = Depends(get_db),
):
    """
    Permite criar somente o primeiro usuario.

    A primeira conta recebe obrigatoriamente
    o papel admin. Depois disso, a criacao
    publica fica bloqueada.
    """
    try:
        db.execute(
            text(
                "LOCK TABLE users "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )

        user_count = user_repository.count(db)

        if user_count != 0:
            db.rollback()

            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "Bootstrap encerrado. "
                    "A criacao publica de usuarios "
                    "esta bloqueada."
                ),
            )

        existing = user_repository.get_by_email(
            db,
            email=user_in.email,
        )

        if existing:
            db.rollback()

            raise HTTPException(
                status_code=400,
                detail="E-mail ja cadastrado.",
            )

        return user_repository.create(
            db,
            user_in=user_in,
            role="admin",
        )

    except HTTPException:
        raise

    except Exception:
        db.rollback()
        raise


@router.get(
    "/",
    response_model=list[UserResponse],
)
def read_users(
    skip: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=200,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):
    return user_repository.get_all(
        db,
        skip=skip,
        limit=limit,
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
)
def read_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):
    user = user_repository.get(
        db,
        user_id,
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Usuario nao encontrado.",
        )

    return user
