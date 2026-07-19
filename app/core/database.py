# ============================================================
# ATLAS OS - database.py
# Conexão com o PostgreSQL via SQLAlchemy
# ============================================================

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Motor de conexão com o banco (usa a URL do config)
_db_url = settings.database_url
_engine_kwargs = {"pool_pre_ping": True, "echo": False}
if _db_url.startswith("sqlite"):
    # SQLite precisa liberar o uso da conexão entre threads do FastAPI.
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_db_url, **_engine_kwargs)

# Fábrica de sessões: cada requisição usa uma sessão
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Classe base para todos os modelos (tabelas)
Base = declarative_base()


# Dependência do FastAPI: fornece uma sessão e garante o fechamento
def get_db():
    """Abre uma sessão, entrega para a rota e fecha ao final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
