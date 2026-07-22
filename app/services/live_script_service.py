# ============================================================
# ATLAS OS - services/live_script_service.py
#
# "ROTEIRISTA" da live gravada. Pega os produtos de uma plataforma
# (via live_catalog_service) e escreve o ROTEIRO da live:
#
#   abertura -> [fala de cada produto ~30s] -> encerramento
#   + frases de RECOMECO (para quando o video volta em loop, sem
#     parecer repeticao: "voltamos para quem perdeu..." etc.)
#
# Cada fala e' gerada pela IA (live_brain_service.generate). Se a IA
# falhar, cai numa fala-modelo pronta - o roteiro NUNCA fica vazio.
#
# Saida (build_script): {ok, platform, market, language, blocks[], total_seconds}
#   block = {kind, seconds, text, product?}
#     kind: "intro" | "product" | "outro"
# E as frases de recomeco vem em recap_lines(language) (usadas no loop).
# ============================================================

from __future__ import annotations

import re

from app.services import live_brain_service as brain
from app.services import live_catalog_service as catalog

# Ritmo de fala aproximado (palavras por segundo) para estimar a duracao.
# PT-BR fica confortavel perto de 2.5 palavras/seg.
_WORDS_PER_SEC = {"pt": 2.5, "en": 2.6}

# Limites de seguranca para a duracao por produto.
_MIN_SECONDS = 20
_MAX_SECONDS = 60


def _norm_language(language: str | None) -> str:
    return "en" if (language or "").strip().lower().startswith("en") else "pt"


def _clamp_seconds(seconds: int | float) -> int:
    try:
        value = int(round(float(seconds)))
    except Exception:
        value = 30
    return max(_MIN_SECONDS, min(_MAX_SECONDS, value))


def _target_words(seconds: int, language: str) -> int:
    rate = _WORDS_PER_SEC.get(language, 2.5)
    return max(12, int(seconds * rate))


def estimate_seconds(text: str, language: str = "pt") -> int:
    """Estima em quantos segundos a fala e' dita (para somar a duracao)."""
    words = len(re.findall(r"\S+", text or ""))
    rate = _WORDS_PER_SEC.get(_norm_language(language), 2.5)
    return max(1, int(round(words / rate)))


# ------------------------------------------------------------
# Frases de RECOMECO (anti-loop) - giram a cada volta do video
# ------------------------------------------------------------
def recap_lines(language: str = "pt") -> list[str]:
    """Frases ditas quando a live volta ao inicio (para nao parecer loop)."""
    if _norm_language(language) == "en":
        return [
            "We just went through all today's deals! If you just got here, "
            "let's run them back from the top - you don't want to miss these.",
            "Welcome back to everyone who just joined! Stick around, the best "
            "finds are coming right up again.",
            "Quick recap for whoever missed it: I lined up the best sellers, "
            "come take another look!",
            "For everyone arriving now, we're starting fresh - same great "
            "prices, let's dive back in!",
        ]
    return [
        "Acabamos de passar por todos os achados de hoje! Pra quem chegou "
        "agora, bora repassar do comecinho - tem oferta boa demais aqui.",
        "Boas-vindas a quem acabou de entrar! Fica comigo que os melhores "
        "achados vem de novo agorinha.",
        "Recapitulando pra quem perdeu: separei os campeoes de venda, vem "
        "ver mais uma vez comigo!",
        "Pra galera que ta chegando agora, a gente volta do inicio - mesmos "
        "precos, bora conferir tudo de novo!",
    ]


# ------------------------------------------------------------
# Abertura e encerramento
# ------------------------------------------------------------
def _intro_text(platform_name: str, language: str) -> str:
    if language == "en":
        return (
            f"Hey everyone, welcome to our live deals show! Today I picked the "
            f"best finds from {platform_name} for you. Some links are affiliate "
            f"links. Stick around - let's get shopping!"
        )
    return (
        f"Oi gente, sejam bem-vindos a nossa live de ofertas! Hoje eu separei "
        f"os melhores achados da {platform_name} pra voces. Alguns links sao de "
        f"afiliado. Fica comigo que vem coisa boa - bora as compras!"
    )


def _outro_text(language: str) -> str:
    if language == "en":
        return (
            "That's our lineup for now! The links are in the description. "
            "Stay with me because we're starting again for anyone who just arrived."
        )
    return (
        "Esses foram os achados por enquanto! Os links estao na descricao. "
        "Fica comigo que a gente ja vai comecar de novo pra quem acabou de chegar."
    )


# ------------------------------------------------------------
# Fala de UM produto (IA com fallback)
# ------------------------------------------------------------
def _fallback_product_text(product: dict, language: str) -> str:
    title = (product.get("title") or "").strip()
    price = (product.get("price") or "").strip()
    if language == "en":
        price_part = f" Only {price}." if price else ""
        return (
            f"Check out this one: {title}.{price_part} It's a great pick and "
            f"super popular right now. The link is in the description - go grab it!"
        )
    price_part = f" Sai por {price}." if price else ""
    return (
        f"Olha so esse achado: {title}.{price_part} E uma otima escolha e ta "
        f"bombando agora. O link ta na descricao - corre pegar o seu!"
    )


def _product_prompt(product: dict, *, language: str, persona: str, words: int) -> str:
    title = (product.get("title") or "").strip()
    price = (product.get("price") or "").strip()
    price_line = f"Preco: {price}" if price else "Preco: (nao informado)"
    persona_line = f"Estilo do apresentador: {persona}" if persona else ""

    if language == "en":
        return (
            "You are a friendly live-shopping host. Write ONLY the spoken line "
            f"(no quotes, no emojis, about {words} words) presenting this product "
            "on a live sales show. Be warm, mention one benefit and a call to "
            "action to tap the link in the description.\n"
            f"Product: {title}\n{price_line}\n{persona_line}"
        )
    return (
        "Voce e um apresentador simpatico de live de vendas. Escreva APENAS a "
        f"fala (sem aspas, sem emojis, com cerca de {words} palavras) "
        "apresentando este produto numa live. Seja caloroso, cite um beneficio "
        "e finalize chamando para tocar no link da descricao.\n"
        f"Produto: {title}\n{price_line}\n{persona_line}"
    )


def build_product_line(
    product: dict,
    *,
    language: str = "pt",
    persona: str = "",
    seconds: int = 30,
    use_ai: bool = True,
) -> str:
    """Escreve a fala de um produto (IA -> fallback pronto)."""
    language = _norm_language(language)
    seconds = _clamp_seconds(seconds)
    words = _target_words(seconds, language)

    if use_ai:
        prompt = _product_prompt(product, language=language, persona=persona, words=words)
        result = brain.generate(prompt)
        text = (result.get("text") or "").strip() if result else ""
        # Remove aspas que a IA as vezes coloca em volta da fala.
        text = text.strip().strip('"').strip("'").strip()
        if text:
            return text
    return _fallback_product_text(product, language)


# ------------------------------------------------------------
# Roteiro completo
# ------------------------------------------------------------
def build_script(
    platform: str,
    *,
    market: str = "",
    language: str = "pt",
    persona: str = "",
    seconds_per_product: int = 30,
    max_products: int = 0,
    use_ai: bool = True,
) -> dict:
    """Monta o roteiro da live gravada de uma plataforma.

    Retorna {ok, platform, market, language, product_count, total_seconds,
             blocks:[{kind, seconds, text, product?}], recap_lines:[...]}.
    """
    platform = (platform or "amazon").strip().lower()
    language = _norm_language(language)
    seconds_per_product = _clamp_seconds(seconds_per_product)

    products = catalog.get_products(platform, market, limit=max_products)
    platform_name = next(
        (p["name"] for p in catalog.list_platforms() if p["id"] == platform),
        platform.title(),
    )

    if not products:
        return {
            "ok": False,
            "reason": (
                f"Nenhum produto encontrado para '{platform_name}'. "
                "Verifique a plataforma/mercado ou cadastre os produtos."
            ),
            "platform": platform,
            "market": (market or "").upper(),
        }

    blocks: list[dict] = []

    intro = _intro_text(platform_name, language)
    blocks.append({"kind": "intro", "seconds": estimate_seconds(intro, language), "text": intro})

    for product in products:
        text = build_product_line(
            product,
            language=language,
            persona=persona,
            seconds=seconds_per_product,
            use_ai=use_ai,
        )
        blocks.append(
            {
                "kind": "product",
                "seconds": estimate_seconds(text, language),
                "text": text,
                "product": product,
            }
        )

    outro = _outro_text(language)
    blocks.append({"kind": "outro", "seconds": estimate_seconds(outro, language), "text": outro})

    total_seconds = sum(int(b.get("seconds", 0)) for b in blocks)

    return {
        "ok": True,
        "platform": platform,
        "platform_name": platform_name,
        "market": (market or "").upper(),
        "language": language,
        "persona": persona,
        "product_count": len(products),
        "total_seconds": total_seconds,
        "blocks": blocks,
        "recap_lines": recap_lines(language),
    }
