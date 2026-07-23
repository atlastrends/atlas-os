"""Robo de direct do Atlas (Instagram / Facebook).

Fluxo:
  1) Cliente comenta a palavra do produto (ex.: FRITADEIRA).
  2) O Meta avisa este servico (webhook).
  3) O robo manda no direto o link daquele produto.
  4) Se o cliente responder no direct com uma duvida do produto, a IA responde.
     Se for outro assunto, o robo passa o email de contato.

Roda como um servico web leve (FastAPI). Feito para o Render (24h no ar).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import FastAPI, Request, Response

from . import ai, config, meta_api, products

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

app = FastAPI(title="Atlas DM Bot")

# Memoria simples: guarda o ultimo produto que cada cliente pediu, para a IA
# ter contexto quando ele responder no direct. Some quando o servico reinicia
# (tudo bem, e so um "melhor esforco").
_context: dict[str, dict] = {}
_CONTEXT_TTL = 24 * 60 * 60  # 24h


def _remember(user_id: str, product: dict) -> None:
    _context[str(user_id)] = {"product": product, "at": time.time()}


def _recall(user_id: str) -> dict | None:
    item = _context.get(str(user_id))
    if not item:
        return None
    if (time.time() - item["at"]) > _CONTEXT_TTL:
        _context.pop(str(user_id), None)
        return None
    return item["product"]


def _is_en(product: dict | None) -> bool:
    return bool(product) and str(product.get("market") or "").upper() == "US"


def _link_message(product: dict) -> str:
    title = (product.get("title") or "").strip()
    if len(title) > 70:
        title = title[:67] + "..."
    url = product.get("url") or ""
    if _is_en(product):
        return (
            f"Hi! 💛 Here's the link for {title}:\n{url}\n\n"
            "Any question about the product, just message me here 😉"
        )
    return (
        f"Oi! 💛 Aqui está o link do {title}:\n{url}\n\n"
        "Qualquer dúvida sobre o produto é só me chamar por aqui 😉"
    )


def _email_message(en: bool) -> str:
    if en:
        return (
            "For this subject it's better to reach us by email: "
            f"{config.SUPPORT_EMAIL} 📧"
        )
    return (
        "Para esse assunto é melhor falar com a gente por email: "
        f"{config.SUPPORT_EMAIL} 📧"
    )


# --------------------------------------------------------------------------
# Verificacao do webhook (o Meta chama isso 1 vez para confirmar o endereco)
# --------------------------------------------------------------------------
@app.get("/webhooks/meta")
async def verify(request: Request) -> Response:
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    if mode == "subscribe" and token == config.META_VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    return Response(content="forbidden", status_code=403)


@app.api_route("/", methods=["GET", "HEAD"])
async def health() -> dict:
    # O Render (e outros health checks) usam HEAD / para checar se a porta
    # esta aberta. Sem "HEAD" aqui, essa versao do FastAPI/Starlette responde
    # 405 e o deploy e marcado como falho por "porta nao encontrada".
    return {"ok": True, "produtos": len(products.load_products())}


# --------------------------------------------------------------------------
# Recebimento dos eventos (comentarios e mensagens)
# --------------------------------------------------------------------------
def _valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Confere que o aviso veio MESMO do Meta (assinatura X-Hub-Signature-256)."""
    if not app_secret:
        # Sem segredo configurado nao da para validar; recusa por seguranca.
        return False
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    got = header.split("=", 1)[1]
    return hmac.compare_digest(expected, got)


@app.post("/webhooks/meta")
async def receive(request: Request) -> Response:
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    if not _valid_signature(config.META_APP_SECRET, raw, sig):
        return Response(content="bad signature", status_code=403)

    try:
        data = await request.json()
    except Exception:
        return Response(content="bad json", status_code=400)

    for entry in data.get("entry", []) or []:
        account_id = str(entry.get("id") or "")
        # 1) Comentarios
        for change in entry.get("changes", []) or []:
            _handle_comment(change)
        # 2) Mensagens no direct
        for msg in entry.get("messaging", []) or []:
            _handle_message(account_id, msg)

    # Responde rapido: o Meta so quer um 200.
    return Response(content="ok", media_type="text/plain")


def _handle_comment(change: dict) -> None:
    field = change.get("field")
    if field not in ("feed", "comments"):
        return
    value = change.get("value", {}) or {}
    # Facebook usa "message"; Instagram usa "text".
    text = value.get("message") or value.get("text") or ""
    # So responde a comentarios NOVOS (nao a edicoes/remocoes).
    if value.get("verb") and value.get("verb") != "add":
        return
    # Ignora comentarios que a propria conta fez.
    from_id = str((value.get("from") or {}).get("id") or "")
    comment_id = value.get("comment_id") or value.get("id") or ""
    media_id = value.get("post_id") or (value.get("media") or {}).get("id") or ""

    product = products.match_product(text, str(media_id))
    if not product:
        return  # ninguem escreveu a palavra-gatilho -> nao faz nada
    ok = meta_api.send_private_reply(str(comment_id), _link_message(product))
    if ok and from_id:
        _remember(from_id, product)
    log.info("Comentario '%s' -> produto %s (enviado=%s)", text[:30], product.get("keyword"), ok)


def _handle_message(account_id: str, msg: dict) -> None:
    message = msg.get("message") or {}
    # Ignora "echo" (mensagens que a propria conta mandou).
    if message.get("is_echo"):
        return
    text = (message.get("text") or "").strip()
    sender_id = str((msg.get("sender") or {}).get("id") or "")
    if not text or not sender_id:
        return

    product = _recall(sender_id)
    en = _is_en(product)
    if product:
        reply, needs_email = ai.answer_question(product.get("title") or "", text)
        if needs_email or not reply:
            reply = _email_message(en)
    else:
        # Nao sabemos de qual produto ele fala -> manda para o email.
        reply = _email_message(en)

    ok = meta_api.send_message(account_id, sender_id, reply)
    log.info("Direct de %s -> resposta enviada=%s", sender_id, ok)
