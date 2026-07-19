# ============================================================
# ATLAS OS - security/password.py
# Utilitários para hash e verificação de senhas (Bcrypt)
# ============================================================

from passlib.context import CryptContext

# Configuração do contexto de criptografia usando bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """
    Recebe uma senha em texto plano e retorna o hash seguro.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica se uma senha em texto plano corresponde ao hash salvo no banco.
    """
    return pwd_context.verify(plain_password, hashed_password)

