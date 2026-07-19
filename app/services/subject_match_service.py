# ============================================================
# ATLAS OS - subject_match_service.py
# Confere se o ASSUNTO do video (a narracao/roteiro) corresponde EXATAMENTE
# ao produto que ele deveria divulgar.
#
# Uso: decidir se um video de afiliado pode ser PUBLICADO AUTOMATICAMENTE
# (quando ha CERTEZA ALTA de que fala do produto certo) ou se deve ir para
# APROVACAO MANUAL (qualquer duvida).
#
# Regra de ouro: NA DUVIDA, NAO publica. Se a IA nao estiver disponivel ou
# a narracao nao existir, retorna "nao confiante" -> aprovacao manual.
#
# Controle por variaveis de ambiente:
#   ATLAS_SUBJECT_MATCH_ENABLED         (default: true)
#   ATLAS_SUBJECT_MATCH_MIN_CONFIDENCE  (default: 85)  -> 0 a 100
# ============================================================

from __future__ import annotations

import json
import os
import re
from typing import Any


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "sim"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


def gate_enabled() -> bool:
    return _env_bool("ATLAS_SUBJECT_MATCH_ENABLED", True)


def _min_confidence() -> int:
    value = _env_int("ATLAS_SUBJECT_MATCH_MIN_CONFIDENCE", 85)
    return max(0, min(value, 100))


def _text(value: Any) -> str:
    return str(value or "").strip()


# ----------------------------------------------------------------
# EXTRACAO DOS CAMPOS (titulo, categoria, narracao) DO VIDEO
# ----------------------------------------------------------------

def _narration_from_payload(payload: dict) -> str:
    """Pega a narracao. Se nao houver texto pronto, tenta montar a partir do
    roteiro (lista de cenas)."""
    narration = _text(payload.get("narration"))
    if narration:
        return narration

    script = payload.get("script")
    if isinstance(script, list):
        parts: list[str] = []
        for scene in script:
            if isinstance(scene, dict):
                parts.append(
                    _text(
                        scene.get("narration")
                        or scene.get("text")
                        or scene.get("line")
                    )
                )
            elif isinstance(scene, str):
                parts.append(_text(scene))
        return " ".join(p for p in parts if p).strip()

    return ""


def extract_fields(asset: Any) -> dict[str, str]:
    payload = getattr(asset, "payload", None) or {}
    product = payload.get("product") or {}

    title = (
        _text(getattr(asset, "title", ""))
        or _text(payload.get("title"))
        or _text(product.get("title"))
    )
    category = (
        _text(payload.get("category_label"))
        or _text(product.get("category_label"))
        or _text(payload.get("category"))
        or _text(product.get("category"))
    )
    narration = _narration_from_payload(payload)

    return {"title": title, "category": category, "narration": narration}


# ----------------------------------------------------------------
# JUIZ POR IA (Gemini primario, Groq reserva)
# ----------------------------------------------------------------

def _build_prompt(title: str, category: str, narration: str) -> str:
    return (
        "You are a STRICT quality reviewer for short affiliate videos.\n"
        "A video was generated to promote ONE specific product. Decide if the "
        "NARRATION clearly and specifically talks about the SAME product below.\n\n"
        "Answer ONLY with valid JSON, no markdown:\n"
        '{"match": true or false, "confidence": 0-100, "reason": "short sentence"}\n\n'
        "Rules:\n"
        "- match=true ONLY if the narration is clearly about this exact product "
        "(same kind of item, consistent with the title). The narration may be in "
        "Portuguese or English.\n"
        "- If the narration is generic, talks about a DIFFERENT product, is broken/"
        "empty, or you are not sure, set match=false.\n"
        "- confidence = how sure you are of your verdict (0-100).\n\n"
        f"PRODUCT TITLE: {title}\n"
        f"CATEGORY: {category}\n"
        f"NARRATION: {narration}\n"
    )


def _gemini_judge(prompt: str) -> str | None:
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
                    "temperature": 0.0,
                    "max_output_tokens": 300,
                    "response_mime_type": "application/json",
                },
            )
        except Exception:
            continue
        text = getattr(response, "text", None)
        if text:
            return text
    return None


def _groq_judge(prompt: str) -> str | None:
    try:
        from app.automation.authorized_broll_renderer import _content_service
    except Exception:
        return None

    service = _content_service()
    if service is None or getattr(service, "client", None) is None:
        return None

    try:
        model = service._get_best_model()
    except Exception:
        model = "llama-3.3-70b-versatile"

    try:
        response = service.client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict QA reviewer. You output ONLY valid "
                        "JSON, no markdown, no comments."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
    except Exception:
        return None

    try:
        return response.choices[0].message.content
    except Exception:
        return None


def _parse_judge(raw: str | None) -> tuple[bool, int, str] | None:
    if not raw:
        return None
    text = raw.strip()
    # Remove cercas de codigo, se a IA devolver com ```json ... ```
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except Exception:
        # Ultima tentativa: acha o primeiro objeto JSON no meio do texto.
        found = re.search(r"\{.*\}", text, re.DOTALL)
        if not found:
            return None
        try:
            data = json.loads(found.group(0))
        except Exception:
            return None

    if not isinstance(data, dict):
        return None

    match = bool(data.get("match"))
    try:
        confidence = int(float(data.get("confidence") or 0))
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(confidence, 100))
    reason = _text(data.get("reason")) or "sem detalhe da IA"
    return match, confidence, reason


def _ai_verdict(title: str, category: str, narration: str) -> tuple[bool, int, str] | None:
    prompt = _build_prompt(title, category, narration)
    for judge in (_gemini_judge, _groq_judge):
        parsed = _parse_judge(judge(prompt))
        if parsed is not None:
            return parsed
    return None


# ----------------------------------------------------------------
# API PUBLICA
# ----------------------------------------------------------------

def verify_subject_match(asset: Any) -> tuple[bool, int, str]:
    """Retorna (confiante, confianca 0-100, motivo).

    `confiante` so e True quando ha CERTEZA ALTA de que o assunto do video
    corresponde ao produto. Em qualquer duvida (IA indisponivel, narracao
    ausente, mismatch), retorna False -> o video vai para aprovacao manual.
    """
    fields = extract_fields(asset)
    title = fields["title"]
    narration = fields["narration"]

    if not title:
        return False, 0, "sem titulo do produto para conferir o assunto"
    if not narration or len(narration) < 60:
        return False, 0, "sem narracao suficiente para conferir o assunto"

    verdict = _ai_verdict(title, fields["category"], narration)
    if verdict is None:
        return (
            False,
            0,
            "IA indisponivel para conferir o assunto; enviado para aprovacao manual",
        )

    match, confidence, reason = verdict
    confident = bool(match) and confidence >= _min_confidence()
    if confident:
        return True, confidence, f"assunto confere ({confidence}%): {reason}"
    return False, confidence, f"assunto incerto ({confidence}%): {reason}"
