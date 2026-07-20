"""IA que responde duvidas do cliente sobre o produto (usa Groq, gratis).

Regra: responde curto e util SOMENTE sobre o produto. Se a pergunta fugir
disso (status de pedido, reclamacao, parceria, outro assunto), a IA devolve a
marca [EMAIL] e o robo manda o cliente falar por email.
"""
from __future__ import annotations

import logging

import requests

from . import config

log = logging.getLogger("bot.ai")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM = (
    "Voce e um atendente simpatico de uma loja de indicacoes de produtos da "
    "Amazon. Responda de forma CURTA (1 a 3 frases), no MESMO idioma da "
    "pergunta do cliente. Responda apenas duvidas GERAIS sobre o produto "
    "informado (para que serve, caracteristicas comuns, como usar). Voce NAO "
    "tem acesso a pedidos, entregas, estoque ou pagamentos. Se a pergunta for "
    "sobre status de pedido, entrega de uma compra especifica, reclamacao, "
    "parceria/publicidade, ou qualquer assunto que nao seja o produto em si, "
    "responda EXATAMENTE com a palavra: [EMAIL]. Nao invente dados que voce "
    "nao sabe."
)

EMAIL_MARK = "[EMAIL]"


def answer_question(product_title: str, question: str) -> tuple[str, bool]:
    """Retorna (resposta, precisa_email).

    precisa_email=True quando a IA sinalizou [EMAIL] (ou deu erro).
    """
    if not config.GROQ_API_KEY:
        return "", True
    user = (
        f"Produto: {product_title}\n"
        f"Pergunta do cliente: {question}\n"
        "Responda seguindo as regras."
    )
    try:
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            json={
                "model": config.GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
                "max_tokens": 180,
            },
            timeout=20,
        )
        resp.raise_for_status()
        text = (
            resp.json()["choices"][0]["message"]["content"] or ""
        ).strip()
    except Exception as exc:  # pragma: no cover - rede
        log.warning("Groq erro: %s", exc)
        return "", True

    if EMAIL_MARK in text or not text:
        return "", True
    return text, False
