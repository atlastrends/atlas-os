# ============================================================
# ATLAS OS - routers/media.py
# Serve os arquivos de video para o painel, de forma SEGURA:
# somente caminhos dentro das pastas permitidas sao entregues
# (evita path traversal e exposicao de arquivos sensiveis).
#   GET /media/{path}   ->  arquivo de video
# ============================================================

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["Media"])

PROJECT_ROOT = os.path.abspath(os.getenv("ATLAS_ROOT", os.getcwd()))

# Pastas cujos arquivos podem ser servidos publicamente.
ALLOWED_PREFIXES = (
    "output_videos",
    os.path.join("storage", "video_pipeline", "outputs"),
)

ALLOWED_EXTENSIONS = (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".gif")


@router.get("/media/{path:path}")
def serve_media(path: str):
    # Normaliza e resolve o caminho absoluto.
    rel = path.replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(PROJECT_ROOT, rel))

    # Impede path traversal para fora do projeto.
    if not abs_path.startswith(PROJECT_ROOT + os.sep):
        raise HTTPException(status_code=403, detail="Caminho nao permitido.")

    # Precisa estar em uma pasta permitida.
    rel_from_root = os.path.relpath(abs_path, PROJECT_ROOT)
    if not any(
        rel_from_root.replace("\\", "/").startswith(prefix.replace("\\", "/"))
        for prefix in ALLOWED_PREFIXES
    ):
        raise HTTPException(status_code=403, detail="Pasta nao permitida.")

    if os.path.splitext(abs_path)[1].lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Tipo de arquivo nao permitido.")

    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado.")

    return FileResponse(abs_path)
