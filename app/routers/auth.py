# ============================================================
# ATLAS OS - routers/auth.py
# Endpoint para Autenticação e Login (Geração de Token)
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.token import Token
from app.repositories.user import user_repository
from app.security.password import verify_password
from app.security.jwt import create_access_token

router = APIRouter(tags=["Authentication"])

@router.post("/login/access-token", response_model=Token)
def login_access_token(
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    Endpoint para autenticação (Login). 
    Recebe e-mail e senha, e retorna o Token JWT se estiver tudo correto.
    (Nota: O padrão OAuth2 usa o campo 'username', aqui nós enviamos o e-mail nele).
    """
    # 1. Tenta encontrar o usuário usando o e-mail recebido (form_data.username)
    user = user_repository.get_by_email(db, email=form_data.username)
    
    # 2. Verifica se o usuário existe e se a senha "bate" com o hash do banco
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail ou senha incorretos."
        )
    
    # 3. Impede o login de usuários inativados
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este usuário está inativo."
        )
    
    # 4. Gera o token e retorna conforme o nosso Schema
    return {
        "access_token": create_access_token(subject=user.id),
        "token_type": "bearer"
    }

