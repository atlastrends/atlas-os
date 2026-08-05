"""
app/services/trend_relevance_service.py

Portao de relevancia do B-ROLL dos videos de TENDENCIA (motor automatico).

Pedido do usuario: so criar o video de trend se o material de fundo baixado for
~90% REALMENTE sobre o assunto. O portao analisa PALAVRAS e IMAGENS dentro do
proprio clipe baixado:

  - IMAGENS: extrai alguns frames do clipe e envia para o Gemini (visao).
  - PALAVRAS: o Gemini le qualquer texto visivel nos frames (legendas, nomes,
    marcas, placares) e tambem recebe as palavras de origem da midia (termo de
    busca / titulo do clipe). Com isso decide se o clipe mostra o ASSUNTO
    especifico (a pessoa/jogo/evento/produto nomeado) e nao apenas uma cena
    generica vagamente relacionada.

Se a confianca ficar abaixo do limite (ATLAS_TREND_RELEVANCE_MIN_CONFIDENCE,
padrao 90) OU o veredito for "nao e sobre o assunto", o chamador
(media_service.produce_video) levanta NoFaithfulBackgroundError e o motor PULA
para a proxima trend em alta, em vez de publicar um fundo fora do tema.

Reaproveita o cliente Gemini ja usado no projeto (google-genai, via
authorized_broll_renderer._gemini_client). Nenhuma dependencia nova.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from typing import Any, Optional


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def gate_enabled() -> bool:
    """Portao ligado por padrao. Desligue com ATLAS_TREND_RELEVANCE_ENABLED=false."""
    return _env_bool("ATLAS_TREND_RELEVANCE_ENABLED", True)


def _strict_when_unavailable() -> bool:
    """Quando a IA de visao NAO pode julgar (sem chave/erro/sem frames):
    False (padrao) = deixa passar, para nao travar o motor por indisponibilidade;
    True = descarta o assunto por seguranca."""
    return _env_bool("ATLAS_TREND_RELEVANCE_STRICT", False)


def _min_confidence() -> int:
    try:
        val = int(float(os.getenv("ATLAS_TREND_RELEVANCE_MIN_CONFIDENCE", "90")))
    except (TypeError, ValueError):
        val = 90
    return max(0, min(100, val))


def _frame_count() -> int:
    try:
        val = int(float(os.getenv("ATLAS_TREND_RELEVANCE_FRAMES", "3")))
    except (TypeError, ValueError):
        val = 3
    return max(1, min(6, val))


# Guarda o ultimo erro do juiz de visao para enriquecer o motivo exibido no log.
_LAST_JUDGE_ERROR = ""

# Disjuntor de cota: quando o Gemini responde 429, evitamos martelar a API em
# cada candidato/reel ate este instante (epoch). Volta a tentar depois.
_QUOTA_COOLDOWN_UNTIL = 0.0


def _vision_model_chain() -> list:
    """Modelos de VISAO em ordem de preferencia.

    Prioriza modelos multimodais com COTA GRATUITA ALTA (familia 2.x flash). Os
    modelos 3.x tem free tier de apenas ~20 requisicoes/DIA por modelo e estouram
    rapido (HTTP 429 RESOURCE_EXHAUSTED). Como cada modelo tem cota diaria PROPRIA,
    a lista tambem funciona como fallback: se um estoura, tenta o proximo.

    Configuravel com ATLAS_TREND_RELEVANCE_MODEL (modelo preferido do juiz).
    """
    chain: list = []
    for name in (
        os.getenv("ATLAS_TREND_RELEVANCE_MODEL", "gemini-2.0-flash"),
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        os.getenv("GEMINI_MODEL", ""),
        os.getenv("GEMINI_MODEL_FALLBACK", ""),
    ):
        name = (name or "").strip()
        if name and name not in chain:
            chain.append(name)
    return chain


def _resolve_ffmpeg() -> str:
    """Localiza o ffmpeg (PATH ou o binario empacotado pelo imageio-ffmpeg)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _extract_frames(video_path: str, count: int) -> list:
    """Extrai ate `count` frames JPEG espalhados pelo clipe e retorna os bytes.

    Usa varios -ss espalhados; se o clipe for curto e algum -ss cair depois do
    fim, aquele frame e simplesmente ignorado. Se nada sair, tenta o 1o frame.
    """
    if not video_path or not os.path.isfile(video_path):
        return []

    ffmpeg = _resolve_ffmpeg()

    if count <= 1:
        stamps = [1.0]
    else:
        # 1.0, 3.5, 6.0, 8.5, ... (espalha ao longo do clipe)
        stamps = [round(1.0 + i * 2.5, 2) for i in range(count)]

    frames: list = []
    tmp = tempfile.mkdtemp(prefix="atlas_relevance_")
    try:
        for idx, ss in enumerate(stamps):
            out = os.path.join(tmp, f"frame_{idx}.jpg")
            cmd = [
                ffmpeg, "-y", "-loglevel", "error",
                "-ss", str(ss), "-i", video_path,
                "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "4", out,
            ]
            try:
                r = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except Exception:
                continue
            if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                try:
                    with open(out, "rb") as fh:
                        frames.append(fh.read())
                except Exception:
                    pass

        # Clipe muito curto: tenta ao menos o primeiro frame (sem -ss).
        if not frames:
            out = os.path.join(tmp, "frame_first.jpg")
            cmd = [
                ffmpeg, "-y", "-loglevel", "error", "-i", video_path,
                "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "4", out,
            ]
            try:
                r = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
                if r.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0:
                    with open(out, "rb") as fh:
                        frames.append(fh.read())
            except Exception:
                pass

        return frames
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build_prompt(topic: str, narration: str, media_words: str) -> str:
    words = (media_words or "").strip()
    words_line = f'SEARCH TERM used to find the clip: "{words}"\n' if words else ""

    narr = (narration or "").strip()
    if len(narr) > 1200:
        narr = narr[:1200] + "…"
    narration_block = (
        "NARRATION / AUDIO SCRIPT (what the video actually SAYS out loud):\n"
        f'"""{narr}"""\n\n'
        if narr
        else ""
    )

    return (
        "You are a VERY STRICT judge for a short-video BACKGROUND clip.\n"
        "The clip plays as the background WHILE the narration (audio) is spoken, so "
        "the viewer must SEE on screen what is being SAID. The footage has to VISUALLY "
        "MATCH the narration and the subject — not merely share a vague theme.\n\n"
        f'TRENDING SUBJECT: "{topic}"\n'
        f"{words_line}"
        f"{narration_block}"
        "Look at the attached FRAMES sampled from the clip AND read ANY on-screen TEXT "
        "in them (captions, names, logos, watermarks, scoreboards).\n\n"
        "Decide if the footage VISUALLY SHOWS the specific subject and the concrete "
        "things described in the narration.\n"
        "Answer relevant=false when:\n"
        "- The footage only matches a general theme but does NOT show the concrete "
        "subject/events narrated (example: a generic 'vet holding a dog' while the "
        "audio tells a specific story about an animal hospital -> relevant=false).\n"
        "- It is generic stock footage (random people, city, nature, office, abstract) "
        "picked only for the vibe.\n"
        "- It is a plain color / gradient / unrelated b-roll.\n"
        "- The TRENDING SUBJECT is a specific PERSON (athlete, artist, politician, "
        "celebrity) but the footage does NOT let you CONFIRM that exact person. Only "
        "confirm the identity via an on-screen name/caption naming them, a jersey with "
        "their name/number, or an unmistakable well-known face. A DIFFERENT person, a "
        "look-alike, a fan, or a generic player/person merely wearing related team or "
        "brand clothing (example: a random man wearing a football club shirt while the "
        "audio talks about a specific named player) -> relevant=false.\n"
        "- You cannot verify the identity/subject from what is ACTUALLY visible on "
        "screen. Do NOT assume it is the right person/subject just because the search "
        "term or the narration names them.\n"
        "- You are not sure the footage truly depicts what is being said.\n"
        "Only answer relevant=true with HIGH confidence when the footage genuinely "
        "depicts the specific subject AND what the narration is talking about.\n\n"
        'Reply ONLY with JSON: '
        '{"relevant": true|false, "confidence": 0-100, "reason": "short"}.'
    )


def _gemini_vision_judge(prompt: str, frames: list) -> Optional[str]:
    """Envia o prompt + frames (imagens) ao Gemini e devolve o texto (JSON) cru."""
    try:
        from app.automation.authorized_broll_renderer import _gemini_client
    except Exception:
        return None

    client = _gemini_client()
    if client is None:
        return None

    try:
        from google.genai import types
    except Exception:
        return None

    contents: list = [prompt]
    for fb in frames:
        try:
            contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))
        except Exception:
            pass

    # Sem nenhuma imagem anexada nao ha analise visual -> nao julga.
    if len(contents) <= 1:
        return None

    global _LAST_JUDGE_ERROR, _QUOTA_COOLDOWN_UNTIL

    # Disjuntor: se acabamos de tomar 429 (cota), nao insiste em cada candidato
    # (evita dezenas de chamadas que vao falhar). Volta a tentar apos o cooldown.
    if time.time() < _QUOTA_COOLDOWN_UNTIL:
        _LAST_JUDGE_ERROR = "cota do Gemini em cooldown (429 recente)"
        return None

    models = _vision_model_chain()
    _LAST_JUDGE_ERROR = ""
    quota_hit = False
    for model in models:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config={
                    "temperature": 0.0,
                    "max_output_tokens": 300,
                    "response_mime_type": "application/json",
                },
            )
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
                short = "cota do Gemini esgotada (429)"
                quota_hit = True
            elif "404" in msg or "NOT_FOUND" in msg or "not available" in msg.lower():
                short = f"modelo indisponivel (404): {model}"
            else:
                short = msg.strip().splitlines()[0][:160] if msg.strip() else "erro desconhecido"
            _LAST_JUDGE_ERROR = short
            print(f"⚠️ [TREND RELEVANCE] Modelo de visão '{model}' falhou: {short}. Tentando próximo…")
            continue
        text = getattr(response, "text", None)
        if text:
            return text
        _LAST_JUDGE_ERROR = "resposta vazia do modelo"

    # Todos falharam. Se foi por cota, entra em cooldown para nao repetir a
    # saraivada de 429 nos proximos candidatos/reels.
    if quota_hit:
        try:
            cooldown = int(float(os.getenv("ATLAS_TREND_RELEVANCE_COOLDOWN", "120")))
        except (TypeError, ValueError):
            cooldown = 120
        _QUOTA_COOLDOWN_UNTIL = time.time() + max(15, cooldown)
    return None


def _parse_judge(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    return data


def evaluate_background(
    video_path: str, topic: str, narration: str = "", media_words: str = ""
) -> dict:
    """Julga se o clipe de fundo BATE com a narracao e o assunto.

    Retorna dict: {evaluated, relevant, confidence, reason}.
      - evaluated=False => nao foi possivel julgar (IA/frames indisponiveis).
    """
    result = {"evaluated": False, "relevant": False, "confidence": 0, "reason": ""}
    topic = (topic or "").strip()
    if not topic:
        result["reason"] = "sem assunto"
        return result

    frames = _extract_frames(video_path, _frame_count())
    if not frames:
        result["reason"] = "sem frames"
        return result

    raw = _gemini_vision_judge(_build_prompt(topic, narration, media_words), frames)
    if not raw:
        err = (_LAST_JUDGE_ERROR or "").strip()
        result["reason"] = (
            f"juiz de visao indisponivel: {err}" if err else "juiz de visao indisponivel"
        )
        return result

    data = _parse_judge(raw)
    if not data:
        result["reason"] = "resposta invalida do juiz"
        return result

    try:
        confidence = int(float(data.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = 0

    result.update({
        "evaluated": True,
        "relevant": bool(data.get("relevant")),
        "confidence": max(0, min(100, confidence)),
        "reason": str(data.get("reason", "") or "")[:300],
    })
    return result


def passes_gate(
    video_path: str, topic: str, narration: str = "", media_words: str = ""
) -> tuple:
    """Aplica o portao completo. Retorna (aprovado: bool, detalhe: dict).

      - Portao desligado -> aprovado=True.
      - Avaliou e passou (relevant e confidence >= limite) -> True.
      - Avaliou e reprovou -> False.
      - Nao conseguiu avaliar -> depende de ATLAS_TREND_RELEVANCE_STRICT.
    """
    threshold = _min_confidence()
    detail: dict[str, Any] = {
        "evaluated": False,
        "relevant": False,
        "confidence": 0,
        "reason": "",
        "threshold": threshold,
    }

    if not gate_enabled():
        detail["reason"] = "gate desligado"
        return True, detail

    ev = evaluate_background(video_path, topic, narration, media_words)
    detail.update(ev)

    if not ev.get("evaluated"):
        # IA/frames indisponiveis: nao trava o motor por padrao.
        return (not _strict_when_unavailable()), detail

    approved = bool(ev.get("relevant")) and int(ev.get("confidence", 0)) >= threshold
    return approved, detail
