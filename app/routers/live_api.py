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
import threading
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import live_avatar_service as avatar
from app.services import live_brain_service as brain
from app.services import live_catalog_service as catalog
from app.services import live_video_service as video

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
        "presenter_is_default": avatar.using_default_presenter(),
    }


@router.get("/products")
def products(market: str = ""):
    """Produtos REAIS da bio (Amazon) para o apresentador mostrar na live.

    market opcional: "BR" ou "US". Sem market, devolve todos.
    """
    items = _bio_products(market)
    return {"ok": True, "count": len(items), "products": items}


# ============================================================
# LIVE GRAVADA (video pronto que roda como se fosse ao vivo)
# ============================================================

@router.get("/platforms")
def platforms():
    """Lista as plataformas de venda (Amazon pronta; outras 'em breve')."""
    return {"ok": True, "platforms": catalog.list_platforms()}


@router.get("/catalog")
def catalog_products(platform: str = "amazon", market: str = "", limit: int = 0):
    """Produtos de UMA plataforma, ja normalizados para a live."""
    if not catalog.is_ready(platform):
        return {"ok": False, "reason": "Plataforma ainda nao disponivel.", "products": []}
    items = catalog.get_products(platform, market, limit=limit)
    return {"ok": True, "count": len(items), "products": items}


# ---- Montagem em segundo plano (pode demorar minutos) --------------------
_build_lock = threading.Lock()
_build_state: dict = {
    "running": False,
    "done": 0,
    "total": 0,
    "label": "",
    "ok": None,
    "video": "",
    "video_url": "",
    "reason": "",
    "platform": "",
    "started": 0.0,
    "finished": 0.0,
}


def _run_build(params: dict) -> None:
    def progress(done: int, total: int, label: str) -> None:
        _build_state["done"] = done
        _build_state["total"] = total
        _build_state["label"] = label

    try:
        res = video.build_live(progress=progress, **params)
        _build_state["ok"] = bool(res.get("ok"))
        if res.get("ok"):
            _build_state["video"] = res.get("video", "")
            _build_state["video_url"] = f"/api/live/recorded/{res.get('video', '')}"
            _build_state["total_seconds"] = res.get("total_seconds", 0)
        else:
            _build_state["reason"] = res.get("reason", "Falha ao montar o video.")
    except Exception as exc:  # nunca deixa o thread morrer sem status
        _build_state["ok"] = False
        _build_state["reason"] = f"Erro inesperado: {exc}"
    finally:
        _build_state["running"] = False
        _build_state["finished"] = time.time()


class BuildRequest(BaseModel):
    platform: str = "amazon"
    market: str = ""
    language: str = "pt"
    persona: str = ""
    seconds_per_product: int = 30
    max_products: int = 0
    use_ai: bool = True


@router.post("/build")
def build(req: BuildRequest):
    """Comeca a montar o video da live gravada (roda em segundo plano)."""
    if not catalog.is_ready(req.platform):
        raise HTTPException(status_code=400, detail="Plataforma ainda nao disponivel.")
    with _build_lock:
        if _build_state["running"]:
            raise HTTPException(status_code=409, detail="Ja existe uma montagem em andamento.")
        _build_state.update(
            running=True, done=0, total=0, label="iniciando", ok=None,
            video="", video_url="", reason="", platform=req.platform,
            started=time.time(), finished=0.0,
        )
    params = dict(
        platform=req.platform,
        market=req.market,
        language=req.language,
        persona=req.persona,
        seconds_per_product=max(20, min(60, req.seconds_per_product)),
        max_products=max(0, req.max_products),
        use_ai=req.use_ai,
    )
    threading.Thread(target=_run_build, args=(params,), daemon=True).start()
    return {"ok": True, "started": True}


@router.get("/build/status")
def build_status():
    """Progresso da montagem (para a barra de progresso na tela)."""
    return dict(_build_state)


@router.get("/recorded")
def recorded():
    """Lista os videos de live ja montados (prontos para transmitir)."""
    return {"ok": True, "videos": video.list_recorded()}


@router.get("/recorded/{name}/manifest")
def recorded_manifest(name: str):
    """Manifesto do video (legendas, produtos e frases de recomeco por bloco)."""
    path = video.recorded_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    manifest = path.with_suffix(".json")
    data = _load_json(manifest)
    if data is None:
        raise HTTPException(status_code=404, detail="Manifesto nao encontrado.")
    return data


@router.get("/recorded/{name}")
def recorded_file(name: str):
    """Entrega o mp4 da live montada (o palco toca como se fosse ao vivo)."""
    path = video.recorded_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="Video nao encontrado.")
    return FileResponse(str(path), media_type="video/mp4")
