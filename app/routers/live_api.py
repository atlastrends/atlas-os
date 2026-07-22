# ============================================================
# ATLAS OS - routers/live_api.py
#
# API do "cerebro da live". Por enquanto expoe:
#   POST /api/live/answer       -> comentario -> IA -> (voz)
#   GET  /api/live/audio/{name} -> serve o audio da resposta
#   GET  /api/live/status       -> IA disponivel?
#
# Esta e a fundacao do canal de lives. O avatar e a transmissao
# ao vivo entram em etapas seguintes.
# ============================================================

from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import live_avatar_service as avatar
from app.services import live_brain_service as brain

router = APIRouter(prefix="/api/live", tags=["Live"])

_AUDIO_DIR = brain._AUDIO_DIR
_CLIP_DIR = avatar._CLIP_DIR

# Pasta docs/ onde o build da bio deixa a lista de produtos e o cache de imagens.
_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _bio_products(market: str = "") -> list[dict]:
    """Le os produtos REAIS da bio (docs/produtos.json) com a imagem real da
    Amazon (docs/_img_cache.json). Sao os mesmos produtos que aparecem na bio."""
    data = _load_json(_DOCS_DIR / "produtos.json") or {}
    img_cache = _load_json(_DOCS_DIR / "_img_cache.json") or {}
    raw = data.get("products", []) if isinstance(data, dict) else []
    want = (market or "").upper()
    out: list[dict] = []
    seen: set[str] = set()
    for p in raw:
        url = (p.get("url") or "").strip()
        mk = (p.get("market") or "").upper()
        if want and mk != want:
            continue
        match = _ASIN_RE.search(url)
        asin = match.group(1).upper() if match else ""
        key = asin or url
        if not key or key in seen:
            continue
        seen.add(key)
        image = img_cache.get(asin) or img_cache.get(key) or ""
        if not image and asin:
            image = f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"
        out.append(
            {
                "asin": asin,
                "title": html.unescape((p.get("title") or "").strip()),
                "url": url,
                "market": mk,
                "image": image,
            }
        )
    return out


class AnswerRequest(BaseModel):
    comment: str
    language: str = "pt"
    product_context: str = ""
    persona: str = ""
    with_voice: bool = True
    voice: str = ""
    with_video: bool = False


@router.post("/answer")
def answer(req: AnswerRequest):
    """Recebe um comentario e devolve a resposta (texto + audio opcional)."""
    result = brain.answer_and_speak(
        req.comment,
        language=req.language,
        product_context=req.product_context,
        persona=req.persona,
        voice=req.voice,
        with_voice=req.with_voice,
    )

    audio_rel = result.get("audio_rel", "")
    if audio_rel:
        result["audio_url"] = f"/api/live/audio/{os.path.basename(audio_rel)}"
    else:
        result["audio_url"] = ""

    # Gera o VIDEO do apresentador falando (opcional). Se faltar foto/motor,
    # o proprio servico devolve o motivo e o palco cai na foto estatica.
    result["video_url"] = ""
    if req.with_video and audio_rel:
        abs_audio = Path(_AUDIO_DIR) / os.path.basename(audio_rel)
        clip = avatar.render_clip(abs_audio)
        if clip.get("ok") and clip.get("video_rel"):
            result["video_url"] = f"/api/live/clip/{os.path.basename(clip['video_rel'])}"
            result["video_engine"] = clip.get("engine", "")
            if clip.get("note"):
                result["video_note"] = clip["note"]
        else:
            result["video_note"] = clip.get("reason", "Nao foi possivel gerar o video.")

    return result


@router.get("/audio/{name}")
def audio(name: str):
    """Entrega o arquivo de audio de uma resposta (somente dessa pasta)."""
    safe = os.path.basename(name)
    if not safe.endswith(".mp3"):
        raise HTTPException(status_code=403, detail="Tipo de arquivo nao permitido.")

    abs_path = (Path(_AUDIO_DIR) / safe).resolve()
    root = Path(_AUDIO_DIR).resolve()
    if root not in abs_path.parents:
        raise HTTPException(status_code=403, detail="Caminho nao permitido.")
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail="Audio nao encontrado.")

    return FileResponse(str(abs_path), media_type="audio/mpeg")


@router.get("/clip/{name}")
def clip(name: str):
    """Entrega o video (mp4) do apresentador falando (somente dessa pasta)."""
    safe = os.path.basename(name)
    if not safe.endswith(".mp4"):
        raise HTTPException(status_code=403, detail="Tipo de arquivo nao permitido.")

    abs_path = (Path(_CLIP_DIR) / safe).resolve()
    root = Path(_CLIP_DIR).resolve()
    if root not in abs_path.parents:
        raise HTTPException(status_code=403, detail="Caminho nao permitido.")
    if not abs_path.is_file():
        raise HTTPException(status_code=404, detail="Video nao encontrado.")

    return FileResponse(str(abs_path), media_type="video/mp4")


# Tamanho maximo da foto do apresentador (8 MB).
_MAX_PRESENTER_BYTES = 8 * 1024 * 1024
_ALLOWED_PRESENTER_EXT = {".png", ".jpg", ".jpeg", ".webp"}


@router.post("/presenter")
async def upload_presenter(file: UploadFile = File(...)):
    """Recebe a foto do apresentador (pessoa realista) para o avatar em video."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_PRESENTER_EXT:
        raise HTTPException(
            status_code=400,
            detail="Envie uma imagem .png, .jpg ou .webp.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if len(data) > _MAX_PRESENTER_BYTES:
        raise HTTPException(status_code=413, detail="Imagem muito grande (max 8 MB).")

    try:
        avatar.save_presenter(data, ext)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "has_presenter": True}


@router.get("/presenter")
def get_presenter():
    """Serve a foto do apresentador salva (para o palco exibir)."""
    path = avatar.presenter_path()
    if not path:
        raise HTTPException(status_code=404, detail="Sem foto do apresentador.")
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    if path.suffix.lower() == ".webp":
        media = "image/webp"
    return FileResponse(str(path), media_type=media)


@router.get("/status")
def status():
    """Informa se a IA e a voz estao prontas para a live."""
    gemini_ready = bool(os.getenv("GEMINI_API_KEY"))
    groq_ready = bool(os.getenv("GROQ_API_KEY"))
    return {
        "brain_ready": gemini_ready or groq_ready,
        "gemini_ready": gemini_ready,
        "groq_ready": groq_ready,
        "default_voices": brain.DEFAULT_VOICES,
        "avatar_engine": avatar.engine_name(),
        "has_presenter": avatar.has_presenter(),
    }


@router.get("/products")
def products(market: str = ""):
    """Produtos REAIS da bio (Amazon) para o apresentador mostrar na live.

    market opcional: "BR" ou "US". Sem market, devolve todos.
    """
    items = _bio_products(market)
    return {"ok": True, "count": len(items), "products": items}
