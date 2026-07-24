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

import random
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
# Frases de RECOMECO (anti-loop) = o LOOP INVISIVEL.
# Ditas quando a live volta ao inicio; giram a cada volta para
# nunca parecer repeticao (legenda no reinicio do loop).
# ------------------------------------------------------------
def recap_lines(language: str = "pt") -> list[str]:
    """Frases ditas quando a live volta ao inicio (loop imperceptivel)."""
    if _norm_language(language) == "en":
        return [
            "I see a lot of new people joining us, so let's go back to the "
            "first product and start from the beginning.",
            "If you just joined the live, don't worry. We're going to go "
            "through everything again.",
            "Many new viewers have arrived, so let's start over with the "
            "first featured product.",
            "We'll begin again from the first product so everyone can catch "
            "the full presentation.",
        ]
    return [
        "Enquanto novas pessoas continuam entrando na live, vou voltar ao "
        "primeiro produto para que ninguém perca nenhuma demonstração.",
        "Se você acabou de chegar, fique tranquilo. Vamos começar novamente "
        "desde o primeiro produto.",
        "Muita gente entrou agora, então vou mostrar tudo novamente desde o "
        "começo.",
        "Vou reiniciar nossa apresentação para que todos possam acompanhar "
        "cada detalhe.",
    ]


# ------------------------------------------------------------
# Abertura (cumprimenta quem chegou + apresenta a live)
# ------------------------------------------------------------
def _intro_text(platform_name: str, language: str, product_count: int = 2) -> str:
    if language == "en":
        return (
            "Hey everyone, welcome to the live! If you just arrived, this is "
            "where I show the best deals with the link right in the "
            f"description. Today I hand-picked {product_count} special products "
            "for you - stay with me and I'll walk you through each one in detail!"
        )
    return (
        "Oi gente, sejam muito bem-vindos à nossa live! Pra quem está chegando "
        "agora, é aqui que eu mostro os melhores achados com o link na "
        f"descrição. Hoje eu separei {product_count} produtos especiais pra "
        "você - fica comigo que eu vou mostrar cada um em detalhes!"
    )


# ------------------------------------------------------------
# Transicao suave entre um produto e o proximo (sem corte brusco)
# ------------------------------------------------------------
def _short_title(product: dict, limit: int = 48) -> str:
    title = (product.get("title") or "").strip()
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _transition_prompt(
    current_product: dict, next_product: dict, *, language: str, persona: str, words: int
) -> str:
    cur_title = (current_product.get("title") or "").strip()
    nxt_title = (next_product.get("title") or "").strip()
    persona_line = f"Estilo do apresentador: {persona}" if persona else ""
    if language == "en":
        return (
            "You are hosting a fast-paced live-shopping show (like Shopee/TikTok "
            "Shop hosts). Write ONLY the spoken BRIDGE line (no quotes, no "
            f"emojis, about {words} words) moving from one product straight into "
            "the next, sounding 100% natural and full of energy - never robotic "
            "or like a script being read. Briefly close out the previous product "
            "with genuine enthusiasm, then spark real curiosity about the next "
            "one so people keep watching instead of scrolling away.\n"
            f"Previous product: {cur_title}\nNext product: {nxt_title}\n{persona_line}"
        )
    return (
        "Voce esta apresentando uma live de vendas rapida, como as "
        "apresentadoras da Shopee/TikTok Shop. Escreva APENAS a fala de "
        f"transicao (sem aspas, sem emojis, cerca de {words} palavras) saindo "
        "de um produto direto pro proximo, soando 100% natural e cheia de "
        "energia - nunca robotica ou como um texto sendo lido. Feche o produto "
        "anterior com entusiasmo genuino e desperte curiosidade real pelo "
        "proximo, pra prender quem esta assistindo em vez de deixar rolar o "
        "feed.\n"
        f"Produto anterior: {cur_title}\nProximo produto: {nxt_title}\n{persona_line}"
    )


def _transition_text(
    current_product: dict,
    next_product: dict,
    language: str,
    *,
    persona: str = "",
    use_ai: bool = True,
) -> str:
    """Fala de transicao pro proximo produto (IA -> templates prontos)."""
    if use_ai:
        words = _target_words(9, language)
        prompt = _transition_prompt(
            current_product, next_product, language=language, persona=persona, words=words
        )
        result = brain.generate(prompt)
        text = (result.get("text") or "").strip() if result else ""
        text = text.strip().strip('"').strip("'").strip()
        if text:
            return text

    title = _short_title(next_product)
    if language == "en":
        options = [
            f"Loved that one! Now let me show you the next pick: {title}.",
            f"Great, let's keep going! Up next in our selection: {title}.",
            f"And if you liked that, wait for this next one: {title}.",
        ]
    else:
        options = [
            f"Amei esse! Agora deixa eu te mostrar o próximo achado: {title}.",
            f"Boa, vamos seguir! O próximo da seleção é esse aqui: {title}.",
            f"E se você gostou desse, espera só ver o próximo: {title}.",
        ]
    return random.choice(options)


# ------------------------------------------------------------
# Pergunta simulada do publico + resposta da apresentadora (1 fala)
# ------------------------------------------------------------
def _qa_questions(language: str) -> list[str]:
    if language == "en":
        return [
            "is this good quality?",
            "is it really worth it?",
            "do you ship everywhere?",
            "does it come with a warranty?",
            "is this price a discount?",
        ]
    return [
        "esse produto é de boa qualidade?",
        "vale a pena mesmo?",
        "entrega pra todo o Brasil?",
        "tem garantia?",
        "esse preço já está com desconto?",
    ]


def _fallback_qa_answer(product: dict, language: str) -> str:
    price = (product.get("price") or "").strip()
    if language == "en":
        price_part = f" And at {price}, it's a steal." if price else ""
        return (
            "great question! The quality is excellent, it comes with a warranty "
            f"and the link is right there in the description.{price_part} Go "
            "grab yours!"
        )
    price_part = f" E por {price}, tá valendo muito." if price else ""
    return (
        "ótima pergunta! A qualidade é excelente, tem garantia e o link tá aí "
        f"na descrição pra você comprar com segurança.{price_part} Corre pegar "
        "o seu!"
    )


def _qa_prompt(product: dict, question: str, *, language: str, words: int) -> str:
    title = (product.get("title") or "").strip()
    price = (product.get("price") or "").strip()
    price_line = f"Preco: {price}" if price else "Preco: (nao informado)"
    if language == "en":
        return (
            "You are a charismatic, persuasive live-shopping host (think "
            "Shopee/TikTok Shop hosts), but always HONEST - never invent a "
            "number, warranty or discount that wasn't given to you. A viewer "
            f'just asked: "{question}". Write ONLY the spoken ANSWER (no '
            f"quotes, no emojis, no markdown, about {words} words), in a "
            "natural, conversational tone with contractions, like you're "
            "really talking, not reading a script. Answer the question "
            "directly first, then reinforce the biggest practical BENEFIT for "
            "the viewer's daily life, and close with a clear, low-friction call "
            "to tap the link in the description right now.\n"
            f"Product: {title}\n{price_line}"
        )
    return (
        "Voce e uma apresentadora carismatica e persuasiva de live de vendas "
        "(no estilo das apresentadoras da Shopee/TikTok Shop), mas SEMPRE "
        "HONESTA - nunca inventa numero, garantia ou desconto que nao foi "
        f'informado. Um espectador acabou de perguntar: "{question}". Escreva '
        f"APENAS a RESPOSTA falada (sem aspas, sem emojis, sem markdown, cerca "
        f"de {words} palavras), em tom natural e conversacional, com "
        "contracoes, como se estivesse falando de verdade, nao lendo um "
        "roteiro. Responda a pergunta diretamente primeiro, depois reforce o "
        "MAIOR beneficio pratico pro dia a dia de quem assiste, e termine com "
        "um pedido claro e sem friccao pra tocar no link da descricao agora.\n"
        f"Produto: {title}\n{price_line}"
    )


def build_qa_line(
    product: dict,
    *,
    language: str = "pt",
    persona: str = "",
    use_ai: bool = True,
) -> str:
    """Pergunta simulada do publico + resposta da apresentadora (uma fala so)."""
    language = _norm_language(language)
    question = random.choice(_qa_questions(language))

    answer = ""
    if use_ai:
        result = brain.generate(_qa_prompt(product, question, language=language, words=28))
        answer = (result.get("text") or "").strip().strip('"').strip("'").strip() if result else ""
    if not answer:
        answer = _fallback_qa_answer(product, language)

    if language == "en":
        return f"Someone in the chat asked: {question} {answer}"
    return f"Alguém aqui no chat perguntou: {question} {answer}"


# ------------------------------------------------------------
# Encerramento que CONECTA de volta ao inicio (loop invisivel)
# ------------------------------------------------------------
def _outro_text(language: str) -> str:
    if language == "en":
        return (
            "And those were today's two picks! Since new people keep coming in, "
            "I'll head right back to the first product so nobody misses a thing. "
            "Stay with me!"
        )
    return (
        "E esses foram os dois achados de hoje! Como muita gente continua "
        "chegando, eu já vou voltar lá pro primeiro produto pra ninguém perder "
        "nada. Cola comigo!"
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
            "You are a charismatic, highly persuasive live-shopping host (think "
            "Shopee/TikTok Shop top hosts) - but always HONEST, never inventing "
            "a spec, discount or guarantee that wasn't given to you. Write ONLY "
            f"the spoken line (no quotes, no emojis, no markdown, about {words} "
            "words) presenting this product, sounding 100% natural and "
            "conversational (contractions, real speech rhythm), never like a "
            "script being read.\n"
            "Follow this structure:\n"
            "1) Hook - grab attention in the first sentence (a quick question, "
            "a \"check this out\" moment, or a relatable pain point).\n"
            "2) Benefit - highlight the ONE biggest practical benefit for the "
            "viewer's daily life, not just a spec.\n"
            "3) Desire - make the viewer genuinely want it now (honest urgency "
            "or social proof, never a fake/invented claim).\n"
            "4) CTA - end with ONE clear, low-friction call to tap the link in "
            "the description.\n"
            f"Product: {title}\n{price_line}\n{persona_line}"
        )
    return (
        "Voce e um apresentador carismatico e muito persuasivo de live de "
        "vendas (no estilo dos melhores apresentadores da Shopee/TikTok Shop) "
        "- mas SEMPRE HONESTO, nunca inventando especificacao, desconto ou "
        "garantia que nao foi informada. Escreva APENAS a fala (sem aspas, sem "
        f"emojis, sem markdown, com cerca de {words} palavras) apresentando "
        "este produto, soando 100% natural e conversacional (com contracoes, "
        "ritmo de fala de verdade), nunca como um texto sendo lido.\n"
        "Siga esta estrutura:\n"
        "1) Gancho - prenda a atencao na primeira frase (uma pergunta rapida, "
        "um \"olha so isso\" ou uma dor comum de quem assiste).\n"
        "2) Beneficio - destaque O MAIOR beneficio pratico pro dia a dia de "
        "quem assiste, nao so a especificacao tecnica.\n"
        "3) Desejo - faca a pessoa querer o produto AGORA (urgencia ou prova "
        "social honesta, nunca uma alegacao inventada).\n"
        "4) CTA - termine com UM pedido de acao claro e sem friccao pra tocar "
        "no link da descricao.\n"
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

    intro = _intro_text(platform_name, language, len(products))
    blocks.append({"kind": "intro", "seconds": estimate_seconds(intro, language), "text": intro})

    last = len(products) - 1
    for idx, product in enumerate(products):
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

        # Pergunta simulada do publico + resposta (mantem o produto na tela).
        qa = build_qa_line(product, language=language, persona=persona, use_ai=use_ai)
        blocks.append(
            {"kind": "qa", "seconds": estimate_seconds(qa, language), "text": qa, "product": product}
        )

        # Transicao suave ja mostrando o PROXIMO produto (sem corte brusco).
        if idx < last:
            nxt = products[idx + 1]
            trans = _transition_text(product, nxt, language, persona=persona, use_ai=use_ai)
            blocks.append(
                {
                    "kind": "transition",
                    "seconds": estimate_seconds(trans, language),
                    "text": trans,
                    "product": nxt,
                }
            )

    # Encerramento ja mostrando o PRIMEIRO produto -> conecta ao loop.
    outro = _outro_text(language)
    blocks.append(
        {
            "kind": "outro",
            "seconds": estimate_seconds(outro, language),
            "text": outro,
            "product": products[0] if products else None,
        }
    )

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
