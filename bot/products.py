"""Le a lista de produtos (palavra-gatilho -> link) publicada na bio.

A lista fica num arquivo publico (produtos.json no GitHub Pages), gerado pelo
scripts/build_bio.py. Aqui a gente baixa essa lista de vez em quando (cache)
e procura qual produto combina com o comentario do cliente.
"""
from __future__ import annotations

import re
import time
import unicodedata

import requests

from . import config

_cache: dict = {"at": 0.0, "items": []}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return _strip_accents(str(text or "")).upper()


def load_products(force: bool = False) -> list[dict]:
    """Retorna a lista de produtos, com cache de alguns minutos."""
    now = time.time()
    if not force and _cache["items"] and (now - _cache["at"]) < config.PRODUCTS_TTL_SECONDS:
        return _cache["items"]
    try:
        resp = requests.get(config.PRODUCTS_JSON_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("products", []) if isinstance(data, dict) else []
        _cache["items"] = items
        _cache["at"] = now
    except Exception:
        # Se der erro na rede, mantem o que ja tinha em cache (melhor que nada).
        pass
    return _cache["items"]


def find_by_media(media_id: str) -> dict | None:
    """Acha o produto pelo POST onde o comentario foi feito (mais confiavel)."""
    if not media_id:
        return None
    mid = str(media_id)
    for p in load_products():
        if str(p.get("instagram_media_id") or "") == mid:
            return p
        if str(p.get("facebook_post_id") or "") == mid:
            return p
    return None


def find_by_keyword(comment_text: str) -> dict | None:
    """Acha o produto pela palavra-gatilho que aparece no comentario."""
    text_norm = _norm(comment_text)
    if not text_norm:
        return None
    for p in load_products():
        kw = _norm(p.get("keyword") or "")
        if not kw:
            continue
        # palavra inteira (evita casar pedaco de outra palavra)
        if re.search(rf"\b{re.escape(kw)}\b", text_norm):
            return p
    return None


def match_product(comment_text: str, media_id: str = "") -> dict | None:
    """Regra do robo: so responde se a pessoa usou a palavra-gatilho.

    1) Descobre o produto pela palavra escrita no comentario.
    2) Se nao achar pela palavra mas o post for de um produto conhecido,
       ainda assim NAO responde sozinho (evita spam) -- so responde se a
       pessoa realmente escreveu a palavra.
    """
    return find_by_keyword(comment_text)
