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

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import live_brain_service as brain

router = APIRouter(prefix="/api/live", tags=["Live"])

_AUDIO_DIR = brain._AUDIO_DIR


class AnswerRequest(BaseModel):
    comment: str
    language: str = "pt"
    product_context: str = ""
    persona: str = ""
    with_voice: bool = True
    voice: str = ""


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
    }
