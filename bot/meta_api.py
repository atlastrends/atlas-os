"""Chamadas para a API do Meta (Instagram/Facebook).

Duas coisas:
  - responder no privado a um comentario (private reply) -> abre o direct;
  - mandar mensagem no direct (conversa) -> usado quando a IA responde duvida.
"""
from __future__ import annotations

import logging

import requests

from . import config

log = logging.getLogger("bot.meta")


def send_private_reply(comment_id: str, message: str) -> bool:
    """Responde no PRIVADO a um comentario (funciona p/ Instagram e Facebook).

    Isso manda a mensagem no direct da pessoa que comentou. Precisa da permissao
    de mensagens no app do Meta.
    """
    if not comment_id or not message:
        return False
    url = f"{config.GRAPH_BASE}/{comment_id}/private_replies"
    try:
        resp = requests.post(
            url,
            data={"message": message, "access_token": config.META_ACCESS_TOKEN},
            timeout=15,
        )
        if resp.status_code >= 400:
            log.warning("private_reply falhou (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:  # pragma: no cover - rede
        log.warning("private_reply erro: %s", exc)
        return False


def send_message(account_id: str, recipient_id: str, message: str) -> bool:
    """Manda mensagem no direct (conversa em andamento).

    account_id = id da conta que recebeu (a Pagina/IG que aparece em entry.id
    do webhook). recipient_id = id de quem vai receber (o cliente).
    """
    if not recipient_id or not message:
        return False
    url = f"{config.GRAPH_BASE}/{account_id}/messages"
    try:
        resp = requests.post(
            url,
            json={
                "recipient": {"id": recipient_id},
                "message": {"text": message},
                "messaging_type": "RESPONSE",
            },
            params={"access_token": config.META_ACCESS_TOKEN},
            timeout=15,
        )
        if resp.status_code >= 400:
            log.warning("send_message falhou (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:  # pragma: no cover - rede
        log.warning("send_message erro: %s", exc)
        return False
