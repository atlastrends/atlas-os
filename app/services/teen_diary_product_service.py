"""Seleção conservadora de produtos afiliados para o Diário da Bela."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "docs" / "produtos.json"

# Apenas famílias que podem virar props 3D fiéis e adequados ao contexto.
FAMILIES = {
    "stationery": re.compile(
        r"\b(caneta|canetinha|marcador|marca texto|hidrogr[aá]fica|"
        r"l[aá]pis|caderno|notebook|highlighter|journal|story tablet)\b",
        re.I,
    ),
    "backpack": re.compile(r"\b(mochila|backpack|bookbag|lancheira|lunch box)\b", re.I),
    "headphones": re.compile(r"\b(fone|headphone|headphones|earpods)\b", re.I),
    "book": re.compile(r"\b(livro|box cl[aá]ssicos|book|novel)\b", re.I),
    "toy": re.compile(
        r"\b(lego|brinquedo|boneca|massa de modelar|jogo de cartas|"
        r"puzzle|toy|doll|modeling clay)\b",
        re.I,
    ),
    "water_bottle": re.compile(
        r"\b(garrafa|squeeze|water bottle|tumbler|funtainer)\b",
        re.I,
    ),
}

BLOCKED = re.compile(
    r"\b(arma|faca|knife|gun|beer|wine|cerveja|vinho|tabaco|vape|"
    r"suplemento|supplement|rem[eé]dio|medicine|adult|sexual|"
    r"emagre|weight loss|maquiagem|makeup|cosm[eé]tico|energy drink|"
    r"cafe[ií]na|caffeine)\b",
    re.I,
)

TOPIC_PREFERENCES = {
    "escola": ("stationery", "backpack", "headphones", "book", "water_bottle"),
    "casa": ("stationery", "book", "toy", "headphones", "water_bottle"),
    "amizades": ("stationery", "backpack", "headphones", "water_bottle"),
    "paixao": ("stationery", "book", "headphones", "backpack"),
    "aventura": ("backpack", "water_bottle", "headphones", "book"),
    "irma": ("toy", "stationery", "book", "water_bottle"),
    "familia": ("book", "toy", "stationery", "water_bottle"),
    "emocional": ("book", "stationery", "headphones", "water_bottle"),
}

PROP_ACTIONS = {
    "stationery": ("draw", "write_notes", "show_product"),
    "backpack": ("pack_backpack", "wear_backpack", "show_product"),
    "headphones": ("put_on_headphones", "listen_music", "show_product"),
    "book": ("read_book", "hold_book", "show_product"),
    "toy": ("play_with_toy", "hold_toy", "show_product"),
    "water_bottle": ("drink_water", "hold_bottle", "show_product"),
}


@dataclass(frozen=True)
class DiaryAffiliateProduct:
    market: str
    title: str
    url: str
    keyword: str
    prop_type: str

    def as_dict(self) -> dict:
        return asdict(self)


class TeenDiaryProductService:
    def __init__(self, catalog_path: Optional[str] = None):
        self.catalog_path = Path(catalog_path or DEFAULT_CATALOG)

    @staticmethod
    def _valid_url(url: str, market: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        expected = "amazon.com.br" if market == "BR" else "amazon.com"
        return (
            parsed.scheme == "https"
            and host in (expected, f"www.{expected}")
            and "/dp/" in parsed.path
            and "tag=" in parsed.query
        )

    def _load(self) -> list[DiaryAffiliateProduct]:
        if not self.catalog_path.is_file():
            return []
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        products: list[DiaryAffiliateProduct] = []
        for item in raw.get("products", []):
            market = str(item.get("market", "")).upper()
            title = html.unescape(str(item.get("title", ""))).strip()
            url = str(item.get("url", "")).strip()
            if market not in ("BR", "US") or not title or BLOCKED.search(title):
                continue
            if not self._valid_url(url, market):
                continue
            family = next(
                (name for name, pattern in FAMILIES.items() if pattern.search(title)),
                None,
            )
            if family:
                products.append(
                    DiaryAffiliateProduct(
                        market=market,
                        title=title,
                        url=url,
                        keyword=str(item.get("keyword", "")).strip(),
                        prop_type=family,
                    )
                )
        return products

    def select_pair(self, topic: str, seed: str) -> Optional[dict]:
        """Seleciona BR/US da mesma família visual quando possível."""
        products = self._load()
        preferences = TOPIC_PREFERENCES.get(topic, TOPIC_PREFERENCES["casa"])
        digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
        for family in preferences:
            per_market = {
                market: sorted(
                    (
                        product
                        for product in products
                        if product.market == market and product.prop_type == family
                    ),
                    key=lambda product: (product.title.lower(), product.url),
                )
                for market in ("BR", "US")
            }
            if all(per_market.values()):
                return {
                    market.lower(): candidates[digest % len(candidates)].as_dict()
                    for market, candidates in per_market.items()
                }
        return None

    @staticmethod
    def prompt_block(pair: Optional[dict]) -> str:
        if not pair:
            return (
                "AFFILIATE PRODUCT: none available. Do not invent a product, "
                "brand, price or shopping link."
            )
        br = pair["br"]
        us = pair["us"]
        actions = ", ".join(PROP_ACTIONS[br["prop_type"]])
        return (
            "AFFILIATE PRODUCT INTEGRATION (mandatory and transparent):\n"
            f"- Shared 3D prop type: {br['prop_type']}.\n"
            f"- PT product title: {br['title']}.\n"
            f"- EN product title: {us['title']}.\n"
            f"- Allowed product actions: {actions}.\n"
            "- Integrate the prop naturally in one useful story beat; the physical "
            "action must make sense and must not contradict the narration.\n"
            "- The LAST scene must be Isabela showing the product naturally and "
            "must set product_placement=true.\n"
            "- Final PT narration must transparently say this is an affiliate "
            "recommendation and: 'Se parecer útil para você, peça a um adulto "
            "responsável para conferir o link na legenda.'\n"
            "- Final EN narration must transparently say this is an affiliate "
            "recommendation and: 'If it seems useful to you, ask a parent or "
            "guardian to check the link in the caption.'\n"
            "- Never tell a child to buy, never use urgency, scarcity, peer pressure, "
            "fear, shame, or unsupported claims. Never mention a price."
        )

    @staticmethod
    def localized_caption(pair: Optional[dict], lang: str) -> str:
        if not pair:
            return ""
        product = pair["br" if lang == "pt" else "us"]
        disclosure = (
            "Publicidade/Link de afiliado. Se parecer útil, peça a um adulto "
            "responsável para conferir:"
            if lang == "pt"
            else
            "Ad/Affiliate link. If it seems useful, ask a parent or guardian "
            "to check it:"
        )
        return f"{disclosure}\n{product['title']}\n{product['url']}"
