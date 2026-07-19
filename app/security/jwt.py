# ============================================================
# ATLAS OS - security/jwt.py
# Funções para criação e validação de Tokens JWT
# ============================================================

from datetime import datetime, timedelta, timezone
import jwt

# Chave secreta temporária (depois moveremos para o .env)
SECRET_KEY = "atlas_super_secret_key_change_me_in_production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # Token dura 7 dias

def create_access_token(subject: str | int) -> str:
    """
    Cria um Token JWT para um determinado ID de usuário.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject)}
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

