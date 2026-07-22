# ============================================================
# ATLAS OS - services/live_brain_service.py
#
# "Cerebro da live": recebe um comentario do publico, gera uma
# resposta curta com IA (Gemini primario, Groq reserva) e, se
# pedido, transforma a resposta em VOZ (Edge TTS).
#
# Esta e a base do canal de lives com avatar. Aqui NAO ha avatar
# nem transmissao ainda - so a parte que roda em qualquer maquina
# (sem placa de video): comentario -> IA -> texto -> voz.
# ============================================================

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from pathlib import Path

# Vozes neurais padrao (Edge TTS, gratis). Podem ser trocadas por
# outra voz suportada pelo edge-tts (ex.: pt-BR-AntonioNeural).
DEFAULT_VOICES = {
    "pt": "pt-BR-FranciscaNeural",
    "en": "en-US-AriaNeural",
}

# Onde os audios das respostas sao gravados.
_ATLAS_ROOT = Path(os.getenv("ATLAS_ROOT", os.getcwd()))
_AUDIO_DIR = _ATLAS_ROOT / "storage" / "live" / "answers"


# ----------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------

def _norm_language(language: str | None) -> str:
    value = (language or "").strip().lower()
    if value.startswith("en"):
        return "en"
    return "pt"


def _clean_answer(text: str | None) -> str:
    """Remove marcacao/markdown e deixa a resposta pronta pra fala."""
    if not text:
        return ""
    value = str(text).strip()
    # Remove cercas de codigo e marcadores comuns.
    value = re.sub(r"```[a-zA-Z]*", "", value).replace("```", "")
    value = re.sub(r"[*_`#>]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _build_prompt(
    comment: str,
    *,
    language: str,
    product_context: str,
    persona: str,
) -> str:
    if language == "en":
        persona_line = persona or (
            "You are a friendly, upbeat live shopping host on a livestream."
        )
        product_line = (
            f"Product being shown right now: {product_context}\n"
            if product_context
            else ""
        )
        return (
            f"{persona_line}\n"
            "A viewer just wrote a comment in the live chat. Reply out loud, "
            "the way a host would speak on camera.\n\n"
            "Rules:\n"
            "- Answer ONLY in ENGLISH. Do not use any other language.\n"
            "- Keep it SHORT: 1 to 2 complete spoken sentences, warm and natural.\n"
            "- Speak directly to the viewer. No markdown, no emojis, no lists.\n"
            "- If you don't know a detail, be honest and invite them to keep "
            "watching. Never invent prices or specs.\n"
            "- Stay friendly and encouraging.\n\n"
            f"{product_line}"
            f"Viewer comment: {comment}\n\n"
            "Your complete spoken reply in English:"
        )

    persona_line = persona or (
        "Voce e um apresentador simpatico e animado de uma live de vendas."
    )
    product_line = (
        f"Produto que esta sendo mostrado agora: {product_context}\n"
        if product_context
        else ""
    )
    return (
        f"{persona_line}\n"
        "Um espectador acabou de escrever um comentario no chat da live. "
        "Responda em voz alta, como um apresentador falaria na camera.\n\n"
        "Regras:\n"
        "- Responda SOMENTE em PORTUGUES do Brasil. Nao use nenhum outro idioma.\n"
        "- Seja CURTO: 1 a 2 frases faladas completas, calorosas e naturais.\n"
        "- Fale direto com o espectador. Sem markdown, sem emojis, sem listas.\n"
        "- Se nao souber um detalhe, seja honesto e convide a continuar "
        "assistindo. Nunca invente preco nem especificacoes.\n"
        "- Mantenha um tom amigavel e incentivador.\n\n"
        f"{product_line}"
        f"Comentario do espectador: {comment}\n\n"
        "Sua resposta falada completa em portugues:"
    )


# ----------------------------------------------------------------
# IA: Gemini primario, Groq reserva
# ----------------------------------------------------------------

def _gemini_answer(prompt: str) -> str | None:
    try:
        from app.automation.authorized_broll_renderer import _gemini_client
    except Exception:
        return None

    client = _gemini_client()
    if client is None:
        return None

    models: list[str] = []
    for name in (
        os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        os.getenv("GEMINI_MODEL_FALLBACK", "gemini-flash-latest"),
    ):
        name = (name or "").strip()
        if name and name not in models:
            models.append(name)

    for model in models:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "temperature": 0.7,
                    "max_output_tokens": 512,
                    # Desliga o "pensamento" do modelo para que todos os tokens
                    # de saida virem resposta (evita corte no meio da frase).
                    "thinking_config": {"thinking_budget": 0},
                },
            )
        except Exception:
            continue
        text = getattr(response, "text", None)
        if text and text.strip():
            return text
    return None


def _groq_answer(prompt: str) -> str | None:
    try:
        from app.automation.authorized_broll_renderer import _content_service
    except Exception:
        return None

    service = _content_service()
    if service is None or getattr(service, "client", None) is None:
        return None

    # Usa um modelo SEM raciocinio (nao-"reasoning"). Modelos gpt-oss gastam
    # os tokens "pensando" e cortam a resposta no meio. llama-3.3 responde
    # direto, ideal para uma fala curta de live.
    model = os.getenv("ATLAS_LIVE_GROQ_MODEL", "llama-3.3-70b-versatile")

    try:
        response = service.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly live shopping host. You reply with a "
                        "single short spoken answer, no markdown, no emojis."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=256,
        )
    except Exception:
        return None

    try:
        return response.choices[0].message.content
    except Exception:
        return None


def answer_comment(
    comment: str,
    *,
    language: str = "pt",
    product_context: str = "",
    persona: str = "",
) -> dict:
    """Gera uma resposta curta para um comentario da live.

    Retorna {ok, answer, engine, language}.
    """
    comment = (comment or "").strip()
    language = _norm_language(language)

    if not comment:
        return {
            "ok": False,
            "answer": "",
            "engine": "none",
            "language": language,
            "reason": "comentario vazio",
        }

    prompt = _build_prompt(
        comment,
        language=language,
        product_context=(product_context or "").strip(),
        persona=(persona or "").strip(),
    )

    raw = _gemini_answer(prompt)
    engine = "gemini"
    if not raw:
        raw = _groq_answer(prompt)
        engine = "groq"

    answer = _clean_answer(raw)
    if not answer:
        return {
            "ok": False,
            "answer": "",
            "engine": "none",
            "language": language,
            "reason": "IA indisponivel (sem GEMINI/GROQ ou cota esgotada)",
        }

    return {
        "ok": True,
        "answer": answer,
        "engine": engine,
        "language": language,
    }


def generate(prompt: str) -> dict:
    """Gera um texto livre a partir de um prompt (Gemini primario, Groq reserva).

    Usado pelo "roteirista" da live gravada para escrever a fala de cada
    produto. Retorna {ok, text, engine}. Nunca lanca excecao.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "text": "", "engine": "none"}

    raw = _gemini_answer(prompt)
    engine = "gemini"
    if not raw:
        raw = _groq_answer(prompt)
        engine = "groq"

    text = _clean_answer(raw)
    if not text:
        return {"ok": False, "text": "", "engine": "none"}
    return {"ok": True, "text": text, "engine": engine}


# ----------------------------------------------------------------
# VOZ: texto -> audio (Edge TTS, gratis, sem GPU)
# ----------------------------------------------------------------

async def _tts_async(text: str, voice: str, output_path: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def speak(
    text: str,
    *,
    language: str = "pt",
    voice: str = "",
) -> dict:
    """Transforma o texto da resposta em um arquivo de audio .mp3.

    Retorna {ok, audio_path, audio_rel, voice}. audio_rel e o caminho
    relativo a raiz do projeto (para montar a URL do painel).
    """
    text = (text or "").strip()
    language = _norm_language(language)
    voice = (voice or "").strip() or DEFAULT_VOICES.get(language, DEFAULT_VOICES["pt"])

    if not text:
        return {"ok": False, "audio_path": "", "audio_rel": "", "voice": voice,
                "reason": "texto vazio"}

    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"live_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp3"
    output_path = _AUDIO_DIR / filename

    try:
        asyncio.run(_tts_async(text, voice, str(output_path)))
    except RuntimeError:
        # Ja existe um event loop rodando neste thread: usa um proprio.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_tts_async(text, voice, str(output_path)))
        finally:
            loop.close()
    except Exception as exc:
        return {"ok": False, "audio_path": "", "audio_rel": "", "voice": voice,
                "reason": f"falha na voz: {exc}"}

    if not output_path.is_file() or output_path.stat().st_size < 512:
        return {"ok": False, "audio_path": "", "audio_rel": "", "voice": voice,
                "reason": "arquivo de audio nao gerado"}

    audio_rel = os.path.relpath(output_path, _ATLAS_ROOT).replace("\\", "/")
    return {
        "ok": True,
        "audio_path": str(output_path),
        "audio_rel": audio_rel,
        "voice": voice,
    }


def answer_and_speak(
    comment: str,
    *,
    language: str = "pt",
    product_context: str = "",
    persona: str = "",
    voice: str = "",
    with_voice: bool = True,
) -> dict:
    """Fluxo completo: comentario -> IA -> (opcional) voz."""
    result = answer_comment(
        comment,
        language=language,
        product_context=product_context,
        persona=persona,
    )
    if not result.get("ok"):
        return result

    if with_voice:
        audio = speak(result["answer"], language=result["language"], voice=voice)
        result["voice_ok"] = audio.get("ok", False)
        result["audio_rel"] = audio.get("audio_rel", "")
        result["voice"] = audio.get("voice", "")
        if not audio.get("ok"):
            result["voice_reason"] = audio.get("reason", "")

    return result
