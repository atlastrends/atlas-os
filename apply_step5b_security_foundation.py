from datetime import datetime
from pathlib import Path
import shutil


ROOT = Path("/atlas")

USER_MODEL_PATH = ROOT / "app/models/user.py"
AFFILIATE_MODEL_PATH = ROOT / "app/models/affiliate.py"
MODELS_INIT_PATH = ROOT / "app/models/__init__.py"

USER_SCHEMA_PATH = ROOT / "app/schemas/user.py"
USER_REPOSITORY_PATH = ROOT / "app/repositories/user.py"
USERS_ROUTER_PATH = ROOT / "app/routers/users.py"
SECURITY_DEPS_PATH = ROOT / "app/security/deps.py"

ROLES_PATH = ROOT / "app/security/roles.py"
AUDIT_MODEL_PATH = ROOT / "app/models/content_audit.py"

AUDIT_SERVICE_PATH = (
    ROOT
    / "app/services"
    / "content_audit_service.py"
)

MIGRATION_PATH = (
    ROOT
    / "alembic/versions"
    / "b91f3d7a5c20_security_foundation.py"
)


required_files = [
    USER_MODEL_PATH,
    AFFILIATE_MODEL_PATH,
    MODELS_INIT_PATH,
    USER_SCHEMA_PATH,
    USER_REPOSITORY_PATH,
    USERS_ROUTER_PATH,
    SECURITY_DEPS_PATH,
]

for path in required_files:
    if not path.is_file():
        raise RuntimeError(
            "Arquivo obrigatorio nao encontrado: "
            f"{path.name}"
        )


timestamp = datetime.utcnow().strftime(
    "%Y%m%d_%H%M%S"
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


def backup(path: Path) -> None:
    if not path.exists():
        return

    destination = Path(
        str(path)
        + f".before_step5b_{timestamp}.bak"
    )

    shutil.copy2(
        path,
        destination,
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

backup(ROLES_PATH)
backup(AUDIT_MODEL_PATH)
backup(AUDIT_SERVICE_PATH)
backup(MIGRATION_PATH)


# ============================================================
# 1. MODELO DE USUARIO
# ============================================================

user_model_code = '''from sqlalchemy import (
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
'''

write(
    USER_MODEL_PATH,
    user_model_code,
)

print("[OK] Modelo User atualizado com papeis.")


# ============================================================
# 2. SCHEMAS DE USUARIO
# ============================================================

user_schema_code = '''from datetime import datetime
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
'''

write(
    USER_SCHEMA_PATH,
    user_schema_code,
)

print("[OK] Schemas de usuario atualizados.")


# ============================================================
# 3. REPOSITORIO DE USUARIO
# ============================================================

user_repository_code = '''from sqlalchemy import func, select
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
'''

write(
    USER_REPOSITORY_PATH,
    user_repository_code,
)

print("[OK] Repositorio User atualizado.")


# ============================================================
# 4. GET_CURRENT_USER
# ============================================================

security_deps_code = '''from fastapi import (
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
'''

write(
    SECURITY_DEPS_PATH,
    security_deps_code,
)

print("[OK] get_current_user corrigido.")


# ============================================================
# 5. DEPENDENCIAS DE PAPEL
# ============================================================

roles_code = '''from collections.abc import Callable

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
'''

write(
    ROLES_PATH,
    roles_code,
)

print("[OK] Dependencias de papel preparadas.")


# ============================================================
# 6. BOOTSTRAP DO PRIMEIRO ADMIN
# ============================================================

users_router_code = '''from fastapi import (
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
'''

write(
    USERS_ROUTER_PATH,
    users_router_code,
)

print("[OK] Bootstrap do primeiro admin instalado.")


# ============================================================
# 7. CAMPOS DE AUTORIA NO CONTEUDO
# ============================================================

affiliate_model_text = read(
    AFFILIATE_MODEL_PATH
)

if (
    "submitted_by_user_id = Column("
    not in affiliate_model_text
):
    affiliate_anchor = '''    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    status = Column(
'''

    affiliate_replacement = '''    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    reviewed_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    approved_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    status = Column(
'''

    affiliate_model_text = replace_once(
        affiliate_model_text,
        affiliate_anchor,
        affiliate_replacement,
        "Campos de autoria do conteudo",
    )

write(
    AFFILIATE_MODEL_PATH,
    affiliate_model_text,
)

print("[OK] Campos de autoria adicionados ao modelo.")


# ============================================================
# 8. MODELO DE AUDITORIA
# ============================================================

audit_model_code = '''from sqlalchemy import (
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
'''

write(
    AUDIT_MODEL_PATH,
    audit_model_code,
)

print("[OK] Modelo de auditoria criado.")


# ============================================================
# 9. REGISTRO DO MODELO
# ============================================================

models_init_text = read(
    MODELS_INIT_PATH
)

audit_import = (
    "from .content_audit import "
    "ContentAuditLog\n"
)

if audit_import not in models_init_text:
    import_anchor = (
        "from .content import Content\n"
    )

    if import_anchor not in models_init_text:
        raise RuntimeError(
            "Importacao do modelo Content "
            "nao localizada."
        )

    models_init_text = models_init_text.replace(
        import_anchor,
        import_anchor + audit_import,
        1,
    )

if '"ContentAuditLog",' not in models_init_text:
    all_anchor = '''    "Content",
    "ContentStatusEnum",
'''

    all_replacement = '''    "Content",
    "ContentAuditLog",
    "ContentStatusEnum",
'''

    models_init_text = replace_once(
        models_init_text,
        all_anchor,
        all_replacement,
        "Registro de ContentAuditLog",
    )

write(
    MODELS_INIT_PATH,
    models_init_text,
)

print("[OK] Modelo de auditoria registrado.")


# ============================================================
# 10. SERVICO DE AUDITORIA
# ============================================================

audit_service_code = '''from typing import Any, Optional

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
'''

write(
    AUDIT_SERVICE_PATH,
    audit_service_code,
)

print("[OK] Servico de auditoria preparado.")


# ============================================================
# 11. MIGRACAO ALEMBIC
# ============================================================

migration_code = '''"""security foundation

Revision ID: b91f3d7a5c20
Revises: a7d19c4e2f60
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b91f3d7a5c20"
down_revision: Union[str, None] = "a7d19c4e2f60"

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
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="creator",
        ),
    )

    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('admin', 'reviewer', 'creator')",
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "submitted_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "approved_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_affiliate_contents_submitted_by_user",
        "affiliate_contents",
        "users",
        ["submitted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_affiliate_contents_reviewed_by_user",
        "affiliate_contents",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_affiliate_contents_approved_by_user",
        "affiliate_contents",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_affiliate_contents_submitted_by_user_id",
        "affiliate_contents",
        ["submitted_by_user_id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_reviewed_by_user_id",
        "affiliate_contents",
        ["reviewed_by_user_id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_approved_by_user_id",
        "affiliate_contents",
        ["approved_by_user_id"],
        unique=False,
    )

    op.create_table(
        "affiliate_content_audit_logs",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            nullable=False,
            server_default=sa.text(
                "'{}'::jsonb"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["affiliate_contents.id"],
            name=(
                "fk_affiliate_content_audit_content"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=(
                "fk_affiliate_content_audit_actor"
            ),
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_affiliate_content_audit_logs_id",
        "affiliate_content_audit_logs",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_content_audit_content_created",
        "affiliate_content_audit_logs",
        ["content_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_content_audit_actor_created",
        "affiliate_content_audit_logs",
        ["actor_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_content_audit_actor_created",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_index(
        "ix_affiliate_content_audit_content_created",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_index(
        "ix_affiliate_content_audit_logs_id",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_table(
        "affiliate_content_audit_logs"
    )

    op.drop_index(
        "ix_affiliate_contents_approved_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_reviewed_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_submitted_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_constraint(
        "fk_affiliate_contents_approved_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_affiliate_contents_reviewed_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_affiliate_contents_submitted_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_column(
        "affiliate_contents",
        "approved_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "reviewed_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "submitted_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "submitted_at",
    )

    op.drop_constraint(
        "ck_users_role",
        "users",
        type_="check",
    )

    op.drop_column(
        "users",
        "role",
    )
'''

write(
    MIGRATION_PATH,
    migration_code,
)

print("[OK] Migracao de seguranca gravada.")
print("[OK] Preparacao do Passo 5B concluida.")