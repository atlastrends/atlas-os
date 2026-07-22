# ============================================================
# ATLAS OS - services/live_catalog_service.py
#
# Fonte de PRODUTOS da live, por PLATAFORMA. Hoje a Amazon esta pronta
# (le os produtos reais da bio). TikTok e Mercado Livre ja tem o "encaixe"
# pronto (basta implementar a busca quando o usuario tiver as contas).
#
# Todo produto e' normalizado para o mesmo formato:
#   {id, title, url, image, price, platform, market}
#
# Assim o roteirista e o montador de video funcionam igual para qualquer
# plataforma - so muda de onde os produtos vem.
# ============================================================

from __future__ import annotations

import html
import json
import re
from pathlib import Path

_ATLAS_ROOT = Path(__file__).resolve().parents[2]
_DOCS_DIR = _ATLAS_ROOT / "docs"
_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})", re.IGNORECASE)

# Plataformas conhecidas. "ready" = ja da' para puxar produtos hoje.
_PLATFORMS = [
    {"id": "amazon", "name": "Amazon", "ready": True},
    {"id": "tiktok", "name": "TikTok Shop", "ready": False},
    {"id": "mercadolivre", "name": "Mercado Livre", "ready": False},
]


def list_platforms() -> list[dict]:
    """Lista as plataformas e se ja estao prontas para gerar live."""
    return [dict(p) for p in _PLATFORMS]


def is_ready(platform: str) -> bool:
    pid = (platform or "").strip().lower()
    for p in _PLATFORMS:
        if p["id"] == pid:
            return bool(p["ready"])
    return False


def get_products(platform: str, market: str = "", *, limit: int = 0) -> list[dict]:
    """Devolve os produtos normalizados de uma plataforma.

    platform: "amazon" | "tiktok" | "mercadolivre".
    market:   opcional ("BR"/"US") - usado hoje pela Amazon.
    limit:    0 = todos; N = no maximo N produtos.
    """
    pid = (platform or "amazon").strip().lower()
    if pid == "amazon":
        items = _amazon_products(market)
    elif pid == "tiktok":
        items = _tiktok_products(market)
    elif pid == "mercadolivre":
        items = _mercadolivre_products(market)
    else:
        items = []

    if limit and limit > 0:
        items = items[:limit]
    return items


# ------------------------------------------------------------
# AMAZON (pronta) - produtos reais da bio
# ------------------------------------------------------------
def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _amazon_products(market: str = "") -> list[dict]:
    """Produtos reais da bio (docs/produtos.json) + imagem real (docs/_img_cache.json)."""
    data = _load_json(_DOCS_DIR / "produtos.json") or {}
    img_cache = _load_json(_DOCS_DIR / "_img_cache.json") or {}
    raw = data.get("products", []) if isinstance(data, dict) else []
    want = (market or "").upper()

    out: list[dict] = []
    seen: set[str] = set()
    for p in raw:
        url = (p.get("url") or "").strip()
        mk = (p.get("market") or "").upper()
        if want and mk != want:
            continue
        match = _ASIN_RE.search(url)
        asin = match.group(1).upper() if match else ""
        key = asin or url
        if not key or key in seen:
            continue
        seen.add(key)
        image = img_cache.get(asin) or img_cache.get(key) or ""
        if not image and asin:
            image = f"https://m.media-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"
        out.append(
            {
                "id": asin or key,
                "title": html.unescape((p.get("title") or "").strip()),
                "url": url,
                "image": image,
                "price": (p.get("price") or "").strip() if isinstance(p, dict) else "",
                "platform": "amazon",
                "market": mk,
            }
        )
    return out


# ------------------------------------------------------------
# TikTok Shop (encaixe pronto - a implementar quando houver conta)
# ------------------------------------------------------------
def _tiktok_products(market: str = "") -> list[dict]:
    """PLACEHOLDER. Quando voce tiver a conta de afiliado do TikTok Shop,
    aqui puxamos os produtos (via API de afiliado do TikTok ou uma lista/CSV
    que voce exportar). O formato de saida deve ser igual ao da Amazon:
    {id, title, url, image, price, platform:"tiktok", market}.
    """
    return []


# ------------------------------------------------------------
# Mercado Livre (encaixe pronto - a implementar quando houver conta)
# ------------------------------------------------------------
def _mercadolivre_products(market: str = "") -> list[dict]:
    """PLACEHOLDER. Com a conta de afiliado do Mercado Livre, puxamos os
    produtos (API do Mercado Livre ou lista/CSV) no mesmo formato normalizado.
    """
    return []
