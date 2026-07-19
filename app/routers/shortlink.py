# ============================================================
# ATLAS OS - routers/shortlink.py
# Redirecionamento dos links curtos clicaveis de afiliado.
#   GET /go/{code}  ->  302 -> URL de afiliado (rastreando o clique)
# ============================================================

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.shortlink_service import ShortLinkService

router = APIRouter(tags=["Short Links"])


@router.get("/go/{code}")
def go(code: str, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else None
    link = ShortLinkService(db).resolve_and_track(
        code,
        ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        referer=request.headers.get("referer"),
    )

    if not link:
        # Fallback para a home da Amazon caso o code nao exista.
        return RedirectResponse(url="https://www.amazon.com", status_code=302)

    return RedirectResponse(url=link.target_url, status_code=302)
