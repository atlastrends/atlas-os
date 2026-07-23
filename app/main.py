import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Carrega as variaveis do .env para o ambiente, para que os publicadores
# (YouTube/TikTok/Instagram/Facebook) e os coletores de metricas encontrem as
# credenciais via os.getenv. Alem do .env do projeto, tambem carrega um .env
# COMPARTILHADO (ex.: %OneDrive%\ATLAS-OS-SECRETS\.env) quando existir, para
# funcionar em varias maquinas sem copiar segredos e sem coloca-los no Git.
from app.core.env_loader import load_env

load_env()

from app.routers import (
    affiliate,
    affiliate_content_review,
    affiliate_manual,
    affiliate_video,
    amazon_catalog,
    amazon_sales,
    auth,
    dashboard_api,
    live_api,
    media,
    shortlink,
    users,
)


_engine_thread = None
_atlas_engine = None


def _env_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    return raw_value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "sim",
    }


def is_atlas_engine_enabled() -> bool:
    return _env_bool(
        name="ATLAS_ENGINE_ENABLED",
        default=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _atlas_engine
    global _engine_thread

    print("[ATLAS OS] API iniciando...")

    # Garante que as tabelas do painel existam (idempotente).
    try:
        from app.core.database import Base, engine
        from app.models import dashboard as dashboard_models
        from app.models.amazon_sales import AmazonSale
        from app.models.content import Content

        # Cria apenas as tabelas do painel. Isso evita depender de recursos
        # especificos do Postgres usados por outros modelos (ex.: BTRIM em
        # CHECK constraints), permitindo tambem testar com SQLite localmente.
        dashboard_tables = [
            dashboard_models.VideoAsset.__table__,
            dashboard_models.Publication.__table__,
            dashboard_models.VideoMetric.__table__,
            dashboard_models.PlatformStat.__table__,
            dashboard_models.ShortLink.__table__,
            dashboard_models.LinkClick.__table__,
            dashboard_models.AdCampaign.__table__,
            dashboard_models.AnsweredComment.__table__,
            # Tabela usada pelo motor de reels (loop_worker) para salvar o
            # roteiro gerado antes de renderizar o video.
            Content.__table__,
            # Tabela das vendas de afiliado da Amazon (pagina "Vendas Amazon").
            AmazonSale.__table__,
        ]
        Base.metadata.create_all(bind=engine, tables=dashboard_tables)
        print("[ATLAS OS] Tabelas do painel verificadas/criadas.")
    except Exception as exc:  # noqa: BLE001
        print(f"[ATLAS OS] Aviso ao criar tabelas do painel: {exc}")

    if is_atlas_engine_enabled():
        from app.workers.loop_worker import Engine

        if _atlas_engine is None:
            _atlas_engine = Engine()

        if (
            _engine_thread is None
            or not _engine_thread.is_alive()
        ):
            _engine_thread = threading.Thread(
                target=_atlas_engine.start,
                daemon=True,
                name="atlas-engine-thread",
            )

            _engine_thread.start()

            print(
                "[ATLAS ENGINE] Motor acionado "
                "via background thread."
            )
        else:
            print(
                "[ATLAS ENGINE] Motor ja estava "
                "em execucao."
            )
    else:
        print(
            "[ATLAS ENGINE] Motor automatico desativado. "
            "Defina ATLAS_ENGINE_ENABLED=true para habilitar."
        )

    # Agendador de tarefas automaticas (coleta de metricas por hora, etc.).
    try:
        from app.services.scheduler_service import start_scheduler

        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        print(f"[ATLAS SCHEDULER] Falha ao iniciar agendador: {exc}")

    yield

    print("[ATLAS OS] API desligando...")

    try:
        from app.services.scheduler_service import shutdown_scheduler

        shutdown_scheduler()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(
    title="ATLAS OS API",
    description="API principal do ecossistema ATLAS OS",
    version="1.1.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(affiliate.router)
app.include_router(affiliate_content_review.router)
app.include_router(affiliate_manual.router)
app.include_router(affiliate_video.router)
app.include_router(amazon_catalog.router)
app.include_router(amazon_sales.router)
app.include_router(dashboard_api.router)
app.include_router(live_api.router)
app.include_router(shortlink.router)
app.include_router(media.router)


@app.get("/api/health", tags=["Health"])
def health_check():
    engine_enabled = is_atlas_engine_enabled()

    return {
        "status": "online",
        "system": "ATLAS OS",
        "message": "ATLAS OS API online.",
        "atlas_engine_enabled": engine_enabled,
        "amazon_catalog_enabled": True,
    }


# ---------------------------------------------------------------------------
# Painel (frontend React compilado). Servido pela propria API para que o
# usuario acesse tudo em http://127.0.0.1:8000 sem rodar o Vite separado.
# ---------------------------------------------------------------------------
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def _serve_spa(full_path: str):
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))