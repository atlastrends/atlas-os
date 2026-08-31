from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urlparse
import argparse
import asyncio
import csv
import hashlib
import importlib
import inspect
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid

import requests
from sqlalchemy.exc import SQLAlchemyError

# Importações do novo motor de vídeo autorizado
from app.automation.authorized_broll_renderer import (
    BrollError,
    duration as audio_duration,
    make_story,
    narration_from_story,
    render_authorized_video,
    render_listing_video,
    render_live_variant,
)
from app.automation.spoken_units import expand_spoken_units

WIDTH = 1080
HEIGHT = 1920
FPS = 30

_DEFAULT_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.getenv("ATLAS_ROOT") or _DEFAULT_ROOT).resolve()

if not (ROOT / "app").exists():
    ROOT = _DEFAULT_ROOT

STORAGE = ROOT / "storage"
AMAZON_STORAGE = STORAGE / "amazon"
IMPORT_DIRECTORY = AMAZON_STORAGE / "imports"
SHOPEE_IMPORT_DIRECTORY = STORAGE / "shopee" / "imports"
SEED_PATH = AMAZON_STORAGE / "seed_terms.json"

VIDEO_STORAGE = STORAGE / "video_pipeline"
OUTPUT_DIRECTORY = VIDEO_STORAGE / "outputs"
WORK_DIRECTORY = VIDEO_STORAGE / "work"
RESERVATION_DIRECTORY = VIDEO_STORAGE / "reservations"

APPROVAL_DIRECTORY = STORAGE / "approval"
PENDING_DIRECTORY = APPROVAL_DIRECTORY / "pending"
PROCESSED_DIRECTORY = APPROVAL_DIRECTORY / "processed"
FAILED_DIRECTORY = APPROVAL_DIRECTORY / "failed"

STATE_PATH = VIDEO_STORAGE / "pipeline_state.json"
LOG_PATH = VIDEO_STORAGE / "pipeline.jsonl"
BIO_HISTORY_PATH = ROOT / "docs" / "_bio_historico.json"

MARKETS = {
    "BR": {
        "marketplace": "www.amazon.com.br",
        "domain": "amazon.com.br",
        "partner_tag": "achadosatlasb-20",
        "language": "pt-BR",
        "voice": "pt-BR-FranciscaNeural",
        "currency": "BRL",
        "search_index": "All",
    },
    "US": {
        "marketplace": "www.amazon.com",
        "domain": "amazon.com",
        "partner_tag": "atlasfindsus-20",
        "language": "en-US",
        "voice": "en-US-JennyNeural",
        "currency": "USD",
        "search_index": "All",
    },
}

# --- Fish Audio TTS (voz natural, multilingue) --------------------------------
# Provider primario opcional. Com FISH_API_KEY definido, a narracao usa o Fish
# (modelo gratuito "s2.1-pro-free"), que pronuncia palavras em ingles dentro do
# texto em portugues corretamente. Qualquer falha cai automaticamente no Edge.
FISH_API_BASE = os.getenv("FISH_API_BASE", "https://api.fish.audio").rstrip("/")
FISH_MODEL = os.getenv("FISH_MODEL", "s2.1-pro-free")
FISH_STATE_PATH = STORAGE / "fish_voice_state.json"

FISH_LANGUAGE_BY_MARKET: dict[str, tuple[str, ...]] = {
    "BR": ("pt-BR", "pt", "portuguese"),
    "US": ("en-US", "en", "english"),
}

# reference_ids fixos por mercado (opcional). Vazio = descoberta automatica.
FISH_VOICE_OVERRIDES: dict[str, dict[str, str]] = {
    "BR": {
        "female": os.getenv("FISH_VOICE_BR_FEMALE", "").strip(),
        "male": os.getenv("FISH_VOICE_BR_MALE", "").strip(),
    },
    "US": {
        "female": os.getenv("FISH_VOICE_US_FEMALE", "").strip(),
        "male": os.getenv("FISH_VOICE_US_MALE", "").strip(),
    },
}

# alternate (padrao) | random | female | male
FISH_VOICE_MODE = os.getenv("AFFILIATE_TTS_VOICE_MODE", "alternate").strip().lower()
GENERATE_LIVE_VARIANTS = os.getenv(
    "ATLAS_GENERATE_LIVE_VARIANTS", "false"
).strip().lower() in {"1", "true", "yes", "on"}

_FISH_VOICE_CACHE: dict[str, dict[str, str]] = {}

SERVICE_MODULES = (
    "app.services.amazon_catalog",
    "app.services.amazon_catalog_service",
    "app.services.amazon_service",
    "app.integrations.amazon",
)

class PipelineError(RuntimeError):
    pass


@dataclass
class Product:
    marketplace_code: str
    asin: str
    title: str
    price_display: str
    image_url: str
    detail_url: str
    source: str
    score: float = 0.0
    brand: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    rating: float | None = None
    review_count: int | None = None
    discount_percent: int | None = None
    currency: str = ""
    category: str = ""
    category_label: str = ""
    platform: str = "amazon"
    language: str = ""
    listing_video_url: str = ""
    listing_image_urls: list[str] = field(default_factory=list)
    media_rights_confirmed: bool = False
    commission_rate: float = 0.0
    commission_amount: float = 0.0
    sold_count: int = 0
    official_page_urls: list[str] = field(default_factory=list)


# Nomes amigaveis das categorias (slug -> rotulo exibido no painel).
CATEGORY_LABELS: dict[str, str] = {
    "electronics": "Eletronicos",
    "kitchen": "Cozinha",
    "home": "Casa",
    "beauty": "Beleza",
    "toys": "Brinquedos",
    "videogames": "Games",
    "sports": "Esportes",
    "pet-supplies": "Pet",
    "hpc": "Saude",
    "office-products": "Escritorio",
    "automotive": "Automotivo",
    "fashion": "Moda",
    "books": "Livros",
    "grocery": "Mercado",
    "musical-instruments": "Instrumentos Musicais",
    "appliances": "Eletrodomesticos",
}


def _load_dynamic_category_labels() -> None:
    """Carrega rotulos de categorias descobertas dinamicamente pelo scraper
    (storage/amazon/imports/category_labels.json) e MESCLA no mapa fixo, sem
    sobrescrever os rotulos curados. Assim, quando a Amazon traz uma categoria
    NOVA, ela ja aparece no painel/bio com um nome, sem precisar editar codigo."""
    try:
        path = ROOT / "storage" / "amazon" / "imports" / "category_labels.json"
        if not path.is_file():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        for slug, label in (data or {}).items():
            slug = str(slug or "").strip().lower()
            label = str(label or "").strip()
            if slug and label and slug not in CATEGORY_LABELS:
                CATEGORY_LABELS[slug] = label
    except Exception:  # noqa: BLE001
        pass


_load_dynamic_category_labels()


def _category_of(item: dict[str, Any]) -> tuple[str, str]:
    """Descobre (slug, rotulo) da categoria de um produto importado."""
    slug = str(item.get("category") or "").strip().lower()

    if not slug:
        # Compatibilidade: extrai de source tipo "movers_electronics".
        source = str(item.get("source") or "")
        if "_" in source:
            slug = source.split("_", 1)[1].strip().lower()

    if not slug:
        slug = "outros"

    label = (
        str(item.get("category_label") or "").strip()
        or CATEGORY_LABELS.get(slug, slug.replace("-", " ").title())
    )
    return slug, label


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    temp.replace(path)


def log_event(event_type: str, **kwargs: Any) -> None:
    record = {
        "timestamp": utc_now(),
        "event": event_type,
        **kwargs,
    }

    line = json.dumps(record, ensure_ascii=False, default=str)
    
    with LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(line + "\n")

    print(line, flush=True)


def ensure_directories() -> None:
    for directory in (
        IMPORT_DIRECTORY,
        OUTPUT_DIRECTORY,
        WORK_DIRECTORY,
        RESERVATION_DIRECTORY,
        PENDING_DIRECTORY,
        PROCESSED_DIRECTORY,
        FAILED_DIRECTORY,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def clean_text(value: Any, maximum: int = 1000) -> str:
    rendered = re.sub(
        r"\s+",
        " ",
        str(value or ""),
    ).strip()

    return rendered[:maximum]


def number(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        return float(value)

    rendered = str(value)
    rendered = rendered.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", rendered)

    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def integer(value: Any, default: int = 0) -> int:
    parsed = number(value)

    if parsed is None:
        return default

    return int(parsed)


def find_database_products() -> list[Product]:
    # Esta instalacao utiliza as importacoes JSON.
    return []

def discover_products() -> list[Product]:
    products: list[Product] = []

    # Importa JSONs (Scrapers / OMNI)
    import_directories = (IMPORT_DIRECTORY, SHOPEE_IMPORT_DIRECTORY)
    for import_directory in import_directories:
        if not import_directory.exists():
            continue
        for path in import_directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for item in data:
                        # Extrai URLs ignorando dicionários complexos se for o caso
                        img_url = item.get("image_url")
                        if isinstance(img_url, dict): img_url = img_url.get("url") or img_url.get("URL") or ""

                        slug, label = _category_of(item)
                        products.append(
                            Product(
                                marketplace_code=item.get("marketplace_code", "BR"),
                                asin=item.get("asin", ""),
                                title=item.get("title", ""),
                                price_display=item.get("price_display", ""),
                                image_url=img_url or "",
                                detail_url=item.get("affiliate_url", ""),
                                source=item.get("source", "import"),
                                category=slug,
                                category_label=label,
                                rating=number(item.get("rating")),
                                review_count=integer(item.get("review_count"), 0)
                                or None,
                                platform=clean_text(
                                    item.get("platform") or "amazon", 30
                                ).lower(),
                                language=clean_text(item.get("language"), 20),
                                listing_video_url=clean_text(
                                    item.get("listing_video_url"), 2000
                                ),
                                listing_image_urls=[
                                    clean_text(url, 2000)
                                    for url in (item.get("listing_image_urls") or [])
                                    if clean_text(url, 2000)
                                ],
                                media_rights_confirmed=bool(
                                    item.get("media_rights_confirmed")
                                ),
                                commission_rate=float(
                                    number(item.get("commission_rate")) or 0.0
                                ),
                                commission_amount=float(
                                    number(item.get("commission_amount")) or 0.0
                                ),
                                sold_count=integer(item.get("sold_count"), 0),
                                official_page_urls=[
                                    clean_text(url, 2000)
                                    for url in (
                                        item.get("official_page_urls") or []
                                    )
                                    if clean_text(url, 2000).startswith(
                                        ("https://", "http://")
                                    )
                                ],
                            )
                        )
            except Exception as e:
                log_event("IMPORT_ERROR", file=path.name, error=str(e))

    # Busca do Banco de Dados
    db_products = find_database_products()
    products.extend(db_products)

    log_event(
        "PRODUCT_DISCOVERY_COMPLETED",
        total_found=len(products)
    )

    return products


_ASIN_URL_PATTERN = re.compile(
    r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)",
    re.IGNORECASE,
)


def _normalize_market(value: Any, url: str = "") -> str:
    market = str(value or "").strip().upper().replace("-", "_")
    if market in {"BR", "AMAZON_BR"}:
        return "BR"
    if market in {"US", "AMAZON_US"}:
        return "US"
    host = urlparse(str(url or "")).netloc.lower()
    if "amazon.com.br" in host:
        return "BR"
    if "amazon.com" in host:
        return "US"
    return ""


def _real_asin_from_url(url: str) -> str:
    match = _ASIN_URL_PATTERN.search(str(url or ""))
    return match.group(1).upper() if match else ""


def _stable_asin(real_asin: str) -> str:
    digest = hashlib.sha1(real_asin.upper().encode("utf-8")).hexdigest().upper()
    return "M" + digest[:9]


def _identity_keys(
    market: Any,
    asin: Any,
    url: str = "",
) -> set[tuple[str, str]]:
    normalized_market = _normalize_market(market, url)
    identifiers = {
        str(asin or "").strip().upper(),
        _real_asin_from_url(url),
    }
    real_asin = _real_asin_from_url(url)
    if not real_asin:
        candidate = str(asin or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{10}", candidate) and not re.fullmatch(r"M[0-9A-F]{9}", candidate):
            real_asin = candidate
    if real_asin:
        identifiers.add(_stable_asin(real_asin))
    return {
        (normalized_market, identifier)
        for identifier in identifiers
        if normalized_market and identifier
    }


def product_identity_keys(product: Product) -> set[tuple[str, str]]:
    return _identity_keys(
        product.marketplace_code,
        product.asin,
        product.detail_url,
    )


def product_was_processed(
    product: Product,
    processed_keys: set[tuple[str, str]],
) -> bool:
    return bool(product_identity_keys(product) & processed_keys)


def pending_product_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()

    # PENDING/PROCESSED = videos aguardando aprovacao ou ja publicados.
    # OUTPUT_DIRECTORY = qualquer video ja gerado em disco (sidecar .json).
    # Assim, se o produto ja virou video, ele nao vira video de novo.
    for directory in (PENDING_DIRECTORY, PROCESSED_DIRECTORY, OUTPUT_DIRECTORY):
        if not directory.exists():
            continue

        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                market = data.get("marketplace_code")
                asin = data.get("asin")
                url = data.get("affiliate_url") or data.get("detail_url") or ""
                keys.update(_identity_keys(market, asin, url))
            except (OSError, json.JSONDecodeError, TypeError) as error:
                log_event("DEDUP_SIDECAR_READ_FAILED", file=str(path), error=str(error))

    if BIO_HISTORY_PATH.is_file():
        try:
            history = json.loads(BIO_HISTORY_PATH.read_text(encoding="utf-8"))
            records = history.values() if isinstance(history, dict) else []
            for record in records:
                if not isinstance(record, dict):
                    continue
                keys.update(
                    _identity_keys(
                        record.get("market"),
                        record.get("asin"),
                        record.get("url") or "",
                    )
                )
        except (OSError, json.JSONDecodeError, TypeError) as error:
            log_event("DEDUP_BIO_HISTORY_READ_FAILED", error=str(error))

    try:
        from app.core.database import SessionLocal
        from app.models.dashboard import ShortLink

        db = SessionLocal()
        try:
            for link in db.query(
                ShortLink.marketplace,
                ShortLink.asin,
                ShortLink.target_url,
            ).all():
                keys.update(
                    _identity_keys(
                        link.marketplace,
                        link.asin,
                        link.target_url or "",
                    )
                )
        finally:
            db.close()
    except (ImportError, OSError, RuntimeError, SQLAlchemyError) as error:
        log_event("DEDUP_DATABASE_READ_FAILED", error=str(error))
        sqlite_path = ROOT / "atlas_local.db"
        if sqlite_path.is_file():
            try:
                with sqlite3.connect(sqlite_path) as connection:
                    rows = connection.execute(
                        "SELECT marketplace, asin, target_url FROM short_links"
                    ).fetchall()
                for market, asin, target_url in rows:
                    keys.update(_identity_keys(market, asin, target_url or ""))
            except (OSError, sqlite3.Error) as sqlite_error:
                log_event(
                    "DEDUP_SQLITE_FALLBACK_FAILED",
                    database=str(sqlite_path),
                    error=str(sqlite_error),
                )

    if RESERVATION_DIRECTORY.is_dir():
        cutoff = datetime.now(timezone.utc).timestamp() - (12 * 60 * 60)
        for path in RESERVATION_DIRECTORY.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                keys.update(
                    _identity_keys(
                        data.get("marketplace_code"),
                        data.get("asin"),
                        data.get("detail_url") or "",
                    )
                )
            except (OSError, json.JSONDecodeError, TypeError) as error:
                log_event("DEDUP_RESERVATION_READ_FAILED", file=str(path), error=str(error))

    return keys


def canonical_product_key(product: Product) -> tuple[str, str]:
    market = _normalize_market(product.marketplace_code, product.detail_url)
    real_asin = _real_asin_from_url(product.detail_url)
    identifier = (
        _stable_asin(real_asin)
        if real_asin
        else str(product.asin or "").strip().upper()
    )
    return market, identifier


def _reservation_path(product: Product) -> Path:
    market, identifier = canonical_product_key(product)
    return RESERVATION_DIRECTORY / f"{market}-{identifier}.json"


def reserve_product(product: Product) -> bool:
    RESERVATION_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = _reservation_path(product)
    payload = json.dumps(
        {
            "marketplace_code": product.marketplace_code,
            "asin": product.asin,
            "detail_url": product.detail_url,
            "reserved_at": utc_now(),
            "pid": os.getpid(),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        )
    except FileExistsError:
        return False
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    return True


def release_product_reservation(product: Product) -> None:
    try:
        _reservation_path(product).unlink(missing_ok=True)
    except OSError as error:
        log_event(
            "PRODUCT_RESERVATION_RELEASE_FAILED",
            market=product.marketplace_code,
            asin=product.asin,
            error=str(error),
        )


def _parse_price(price_display: Any, market: str = "") -> float | None:
    """Extrai o valor numerico de um preco exibido, tratando formatos BR e US.

    Ex.: 'R$ 1.299,90' -> 1299.90 ; '$1,299.99' -> 1299.99 ; 'R$ 49,90' -> 49.90.
    Retorna None quando nao ha numero legivel."""
    if price_display is None:
        return None
    if isinstance(price_display, (int, float)):
        return float(price_display)

    text = str(price_display)
    # Mantem apenas digitos e separadores decimais/milhar.
    cleaned = re.sub(r"[^0-9.,]", "", text)
    if not cleaned:
        return None

    has_dot = "." in cleaned
    has_comma = "," in cleaned
    if has_dot and has_comma:
        # O ULTIMO separador e o decimal; o outro e milhar.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_comma:
        # So virgula: decimal se houver exatamente 1-2 casas no fim (ex.: 49,90).
        if re.search(r",\d{1,2}$", cleaned):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_dot:
        # So ponto: decimal se 1-2 casas no fim; senao e milhar (ex.: 1.299).
        if not re.search(r"\.\d{1,2}$", cleaned):
            cleaned = cleaned.replace(".", "")

    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


# Faixa de preco de COMPRA POR IMPULSO por mercado (converte melhor com
# trafego frio de rede social). Configuravel por .env. Fora da faixa o
# produto perde pontos; muito caro perde bastante.
def _impulse_band(market: str) -> tuple[float, float, float]:
    """Retorna (ideal_min, ideal_max, teto_caro) por mercado."""
    mk = (market or "").strip().upper()
    if mk == "BR":
        lo = float(os.getenv("ATLAS_AFFILIATE_IMPULSE_MIN_BRL", "30"))
        hi = float(os.getenv("ATLAS_AFFILIATE_IMPULSE_MAX_BRL", "150"))
        cap = float(os.getenv("ATLAS_AFFILIATE_EXPENSIVE_BRL", "500"))
    else:
        lo = float(os.getenv("ATLAS_AFFILIATE_IMPULSE_MIN_USD", "12"))
        hi = float(os.getenv("ATLAS_AFFILIATE_IMPULSE_MAX_USD", "45"))
        cap = float(os.getenv("ATLAS_AFFILIATE_EXPENSIVE_USD", "150"))
    return lo, hi, cap


def _price_conversion_bonus(product: Product) -> float:
    """Pontos de conversao baseados no preco: cheio dentro da faixa de impulso,
    caindo fora dela e com penalidade para itens caros (baixa conversao em
    trafego frio). Preco desconhecido = neutro (0)."""
    price = _parse_price(product.price_display, product.marketplace_code)
    if price is None:
        return 0.0
    lo, hi, cap = _impulse_band(product.marketplace_code)
    full = float(os.getenv("ATLAS_AFFILIATE_IMPULSE_BONUS", "8"))

    if lo <= price <= hi:
        return full
    if price < lo:
        # Muito barato: ainda bom, leve reducao proporcional.
        ratio = price / lo if lo > 0 else 1.0
        return round(full * max(0.4, ratio), 2)
    # Acima da faixa ideal: decai ate o teto; acima do teto, penalidade.
    if price <= cap:
        span = max(1.0, cap - hi)
        decay = (price - hi) / span  # 0 -> 1
        return round(full * (1.0 - decay), 2)
    # Item caro: penalidade crescente (converte muito mal por impulso).
    over = (price - cap) / cap
    penalty = float(os.getenv("ATLAS_AFFILIATE_EXPENSIVE_PENALTY", "6"))
    return round(-min(penalty, penalty * min(2.0, over + 0.5)), 2)


def score_product(product: Product) -> None:
    score = 10.0
    if product.review_count:
        score += min(product.review_count / 1000.0, 10.0)
    if product.rating:
        score += (product.rating - 3.5) * 2.0
    if product.discount_percent:
        score += min(product.discount_percent / 5.0, 5.0)
    if product.platform == "shopee":
        score += min(max(product.sold_count, 0) ** 0.5, 50.0)
        score += min(max(product.commission_rate, 0.0) * 0.5, 20.0)
        score += min(max(product.commission_amount, 0.0) * 0.2, 20.0)
    # Fator de CONVERSAO por preco (compra por impulso). Pode ser desligado
    # com ATLAS_AFFILIATE_IMPULSE_MODE=0.
    if os.getenv("ATLAS_AFFILIATE_IMPULSE_MODE", "1").strip().lower() not in ("0", "false", "no", "off"):
        score += _price_conversion_bonus(product)
    product.score = max(0.0, round(score, 1))


def select_products(products: list[Product], maximum: int) -> list[Product]:
    already_processed = pending_product_keys()
    eligible: list[Product] = []
    seen: set[tuple[str, str]] = set()
    for product in products:
        key = canonical_product_key(product)
        if (
            key in seen
            or product_was_processed(product, already_processed)
            or not product.title
            or not product.detail_url
        ):
            continue
        seen.add(key)
        eligible.append(product)

    for p in eligible:
        score_product(p)

    eligible.sort(key=lambda p: p.score, reverse=True)
    return eligible[:maximum]


def available_products(platform: str = "amazon") -> list[dict[str, Any]]:
    """Lista os produtos ainda NAO transformados em video, agrupados por
    mercado + categoria, para o painel montar a selecao.

    As categorias saem na ORDEM DOS MAIS VENDIDOS: quem tem os produtos
    mais fortes na Amazon (melhor pontuacao de vendas + posicao em que a
    Amazon devolveu o produto) aparece primeiro. BR e US sao ordenados
    separadamente."""
    already_processed = pending_product_keys()

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    seen_products: set[tuple[str, str]] = set()

    # A ordem em que a Amazon devolve os produtos ja reflete os mais vendidos
    # (primeiro = mais vendido). Guardamos essa posicao para desempate.
    wanted_platform = (platform or "amazon").strip().lower()
    for position, product in enumerate(discover_products()):
        if product.platform != wanted_platform:
            continue
        if not product.title or not product.detail_url:
            continue
        if product_was_processed(product, already_processed):
            continue
        product_key = canonical_product_key(product)
        if product_key in seen_products:
            continue
        seen_products.add(product_key)

        # Numero de avaliacoes = melhor sinal de "quanto vendeu" (quanto mais
        # gente avaliou, mais vendeu). Estrelas servem de desempate.
        reviews = int(product.review_count or 0)
        rating = float(product.rating or 0.0)

        slug = product.category or "outros"
        label = product.category_label or CATEGORY_LABELS.get(slug, slug)
        key = (product.platform, product.marketplace_code, slug)

        group = groups.get(key)
        if group is None:
            group = {
                "marketplace_code": product.marketplace_code,
                "platform": product.platform,
                "category": slug,
                "category_label": label,
                "count": 0,
                "products": [],
                # Forca de venda da categoria = produto mais vendido dela.
                "best_reviews": 0,
                "best_rating": 0.0,
                "best_position": position,
            }
            groups[key] = group

        group["count"] += 1
        group["best_reviews"] = max(group["best_reviews"], reviews)
        group["best_rating"] = max(group["best_rating"], rating)
        group["best_position"] = min(group["best_position"], position)
        group["products"].append(
            {
                "asin": product.asin,
                "title": product.title,
                "price_display": product.price_display,
                "image_url": product.image_url,
                # A Amazon nao expoe "unidades vendidas por dia/semana" nas
                # paginas publicas de Mais Vendidos. Usamos avaliacoes (review
                # count) e nota como o melhor sinal PUBLICO de popularidade
                # real, mais a posicao (rank) que a propria Amazon atribuiu.
                "reviews": reviews,
                "rating": rating,
                "position": position,
                "platform": product.platform,
                "commission_rate": product.commission_rate,
                "commission_amount": product.commission_amount,
                "sold_count": product.sold_count,
                "ready_for_video": bool(
                    product.media_rights_confirmed
                    and (product.listing_video_url or product.image_url)
                ),
            }
        )

    # Dentro de cada categoria, os mais vendidos (mais avaliacoes) primeiro.
    for group in groups.values():
        group["products"].sort(
            key=lambda p: (-p["reviews"], -p["rating"], p["position"]),
        )
        # Rank exibido no painel (1 = mais vendido da categoria) + rotulos
        # prontos para a UI, ja que review_count "puro" nao diz muito sozinho.
        for idx, item in enumerate(group["products"], start=1):
            item["rank"] = idx

    # Ordena as categorias por mercado e, dentro do mercado, pelos MAIS
    # VENDIDOS: mais avaliacoes primeiro; empate, melhor nota; depois quem a
    # Amazon colocou mais no topo; por ultimo, ordem alfabetica.
    ordered = sorted(
        groups.values(),
        key=lambda g: (
            g["platform"],
            g["marketplace_code"],
            -g["best_reviews"],
            -g["best_rating"],
            g["best_position"],
            g["category_label"],
        ),
    )

    # Remove so os campos internos usados exclusivamente para ordenar as
    # CATEGORIAS (posicao/força agregada). Os campos por PRODUTO (reviews,
    # rating, rank) ficam no retorno: a UI usa isso para mostrar o
    # "indicador de popularidade" de cada produto ao expandir a categoria.
    for group in ordered:
        group.pop("best_reviews", None)
        group.pop("best_rating", None)
        group.pop("best_position", None)
        for item in group["products"]:
            item.pop("position", None)

    return ordered


def _resolve_ffprobe_path() -> str | None:
    """Localiza o ffprobe. Pode nao existir (imageio-ffmpeg nao empacota ffprobe)."""
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        directory = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
        for name in ("ffprobe.exe", "ffprobe"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


def _probe_video_moviepy(path: Path) -> dict[str, Any]:
    """Mede o video usando moviepy quando o ffprobe nao esta disponivel."""
    import moviepy.editor as mp

    clip = mp.VideoFileClip(str(path))
    try:
        width, height = clip.size
        video_duration = float(clip.duration or 0)
        has_audio = clip.audio is not None
    finally:
        clip.close()

    if not width or not height or not has_audio:
        raise PipelineError("O video final nao possui video ou audio.")

    return {
        "width": int(width),
        "height": int(height),
        # O video e sempre criado por nos com libx264 + aac.
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_seconds": video_duration,
        "size_bytes": path.stat().st_size,
    }


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe = _resolve_ffprobe_path()

    if not ffprobe:
        return _probe_video_moviepy(path)

    try:
        result = run_command(
            [
                ffprobe,
                "-v", "error",
                "-show_streams",
                "-show_format",
                "-of", "json",
                str(path),
            ]
        )
    except (FileNotFoundError, OSError):
        return _probe_video_moviepy(path)

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video or not audio:
        raise PipelineError("O video final nao possui video ou audio.")

    return {
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "duration_seconds": float(data.get("format", {}).get("duration", 0)),
        "size_bytes": path.stat().st_size,
    }


def _resolve_edge_tts_command() -> list[str] | None:
    """Localiza o edge-tts de forma robusta.

    1. CLI no PATH (shutil.which).
    2. Executavel ao lado do Python atual (Scripts/edge-tts[.exe]).
    3. Fallback: python -m edge_tts (sempre funciona se o pacote estiver instalado).
    """
    cli = shutil.which("edge-tts")
    if cli:
        return [cli]

    scripts_dir = Path(sys.executable).parent
    for name in ("edge-tts.exe", "edge-tts"):
        candidate = scripts_dir / name
        if candidate.is_file():
            return [str(candidate)]

    try:
        import edge_tts  # noqa: F401
        return [sys.executable, "-m", "edge_tts"]
    except Exception:
        return None


def _fish_enabled() -> bool:
    return bool(os.getenv("FISH_API_KEY", "").strip())


def _fish_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    key = os.getenv("FISH_API_KEY", "").strip()
    headers = {"Authorization": "Bearer " + key}
    if extra:
        headers.update(extra)
    return headers


def _fish_classify_gender(title: str, tags: Iterable[str]) -> str:
    blob = (title or "").lower() + " " + " ".join(
        str(tag).lower() for tag in (tags or [])
    )
    if re.search(
        r"\b(female|woman|women|feminina|feminino|feminine|girl|mulher)\b",
        blob,
    ):
        return "female"
    if re.search(
        r"\b(male|man|men|masculina|masculino|masculine|boy|homem)\b",
        blob,
    ):
        return "male"
    return "unknown"


# Tags de vozes que NAO servem para narracao (personagem/anime/jogo/filme).
_FISH_BAD_STYLE_TAGS = (
    "character-voice", "character", "cartoon", "anime", "gaming", "game",
    "videogame", "video-game", "movie", "film", "celebrity", "meme",
    "robot", "monster",
)

# Estilos de PESSOA NORMAL (conversa do dia a dia) - preferidos.
_FISH_CASUAL_STYLE_TAGS = (
    "conversational", "social-media", "casual", "natural", "friendly",
    "warm", "relaxed", "everyday", "chatty", "vlog", "gentle", "soft",
)

# Estilos de narracao suave (aceitaveis) - 2a opcao.
_FISH_SOFT_STYLE_TAGS = (
    "narration", "podcast", "storytelling", "calm", "sincere", "neutral",
    "audiobook", "educational",
)

# Estilos de LOCUTOR/propaganda que o usuario NAO quer (voz "de comercial").
_FISH_AVOID_STYLE_TAGS = (
    "announcer", "advertisement", "commercial", "cinematic", "authoritative",
    "dramatic", "epic", "trailer", "promo", "sports commentary",
    "sports-commentary", "hype",
)

# Nomes de franquias/personagens conhecidos (defesa extra por nome).
_FISH_BLOCKED_NAME_HINTS = (
    "mortal kombat", "smash bros", "super smash", "goku", "dragon ball",
    "naruto", "one piece", "pokemon", "pok\u00e9mon", "anime", "brainrot",
    "skibidi", "spongebob", "bob esponja", "capitao nascimento",
    "capit\u00e3o nascimento", "tropa de elite",
)


def _fish_style_ok(title: str, tags: Iterable[str]) -> bool:
    """True se a voz NAO parecer personagem/anime/filme/celebridade."""
    tag_blob = " ".join(str(tag).lower() for tag in (tags or []))
    if any(bad in tag_blob for bad in _FISH_BAD_STYLE_TAGS):
        return False
    name = (title or "").lower()
    return not any(hint in name for hint in _FISH_BLOCKED_NAME_HINTS)


def _fish_voice_rank(title: str, tags: Iterable[str]) -> int:
    """Prioridade de estilo (menor = melhor). 99 = personagem (descartar).

    0 = pessoa normal/conversa | 1 = narracao suave | 2 = neutra |
    3 = locutor/propaganda (so em ultimo caso).
    """
    if not _fish_style_ok(title, tags):
        return 99
    blob = " ".join(str(tag).lower() for tag in (tags or []))
    if any(avoid in blob for avoid in _FISH_AVOID_STYLE_TAGS):
        return 3
    if any(style in blob for style in _FISH_CASUAL_STYLE_TAGS):
        return 0
    if any(style in blob for style in _FISH_SOFT_STYLE_TAGS):
        return 1
    return 2


def _fish_discover_market_voices(market_code: str) -> dict[str, str]:
    """Descobre as melhores vozes (feminina/masculina) do Fish para o mercado.

    Ordem: overrides por env -> cache em processo -> API do Fish. Retorna
    {"female": reference_id, "male": reference_id}; ids podem ficar vazios se a
    API nao devolver vozes utilizaveis.
    """
    override = FISH_VOICE_OVERRIDES.get(market_code, {})
    picked = {
        "female": (override.get("female") or "").split(",")[0].strip(),
        "male": (override.get("male") or "").split(",")[0].strip(),
    }
    if picked["female"] and picked["male"]:
        return picked

    if market_code in _FISH_VOICE_CACHE:
        cached = _FISH_VOICE_CACHE[market_code]
        return {
            "female": picked["female"] or cached.get("female", ""),
            "male": picked["male"] or cached.get("male", ""),
        }

    languages = FISH_LANGUAGE_BY_MARKET.get(
        market_code, ("en-US", "en", "english")
    )
    items: list[dict[str, Any]] = []
    for lang in languages:
        try:
            response = requests.get(
                FISH_API_BASE + "/model",
                headers=_fish_headers(),
                params={
                    "language": lang,
                    "sort_by": "score",
                    "page_size": 30,
                },
                timeout=30,
            )
        except Exception:
            continue
        if response.status_code == 401:
            log_event(
                "FISH_AUTH_FAILED",
                market=market_code,
                error="Chave Fish invalida (401).",
            )
            return picked
        if response.status_code != 200:
            continue
        try:
            payload = response.json()
        except Exception:
            continue
        items = payload.get("items") or []
        if items:
            break

    female_id = picked["female"]
    male_id = picked["male"]
    female_rank = 99
    male_rank = 99
    # Escolhe a MELHOR voz por genero: pessoa normal (0) > narracao suave (1) >
    # neutra (2) > locutor/propaganda (3). Personagem/anime/filme fica de fora.
    for entry in items:
        reference = str(entry.get("_id") or "").strip()
        if not reference:
            continue
        title = entry.get("title", "")
        tags = entry.get("tags", [])
        rank = _fish_voice_rank(title, tags)
        if rank >= 99:
            continue
        gender = _fish_classify_gender(title, tags)
        if gender == "female" and not picked["female"] and rank < female_rank:
            female_id, female_rank = reference, rank
        elif gender == "male" and not picked["male"] and rank < male_rank:
            male_id, male_rank = reference, rank

    # Ainda faltou (genero nao identificado): usa as melhores vozes distintas,
    # preferindo as "limpas" (sem personagem/anime/filme).
    if (not female_id or not male_id) and items:
        clean = [
            str(e.get("_id") or "").strip()
            for e in items
            if e.get("_id")
            and _fish_style_ok(e.get("title", ""), e.get("tags", []))
        ]
        pool = clean or [
            str(e.get("_id") or "").strip() for e in items if e.get("_id")
        ]
        pool = [t for t in pool if t]
        if not female_id and pool:
            female_id = pool[0]
        if not male_id:
            male_id = next((t for t in pool if t != female_id), female_id)

    result = {"female": female_id, "male": male_id}
    _FISH_VOICE_CACHE[market_code] = result
    return result


def _fish_bump_counter(key: str = "counter") -> int:
    """Contador PERSISTIDO por CHAVE (ex.: "BR:reel"). Cada fluxo (reel de
    afiliado, live, trend) alterna F/M de forma INDEPENDENTE. Antes era um unico
    contador global: como o afiliado gera 2 vozes por produto (reel+live), a
    paridade do reel nunca trocava e ele saia SEMPRE na mesma voz (feminina)."""
    try:
        data: dict[str, Any] = {}
        if FISH_STATE_PATH.is_file():
            loaded = json.loads(FISH_STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        current = int(data.get(key, 0))
        data[key] = current + 1
        FISH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FISH_STATE_PATH.write_text(json.dumps(data), encoding="utf-8")
        return current
    except Exception:
        return 0


def _fish_next_voice(market_code: str, stream: str = "default") -> tuple[str, str]:
    """Escolhe (reference_id, rotulo) alternando feminino/masculino por video.

    `stream` separa os contadores (ex.: "reel", "live", "trend") para cada fluxo
    alternar por conta propria."""
    voices = _fish_discover_market_voices(market_code)
    female_id = voices.get("female", "")
    male_id = voices.get("male", "")

    if FISH_VOICE_MODE == "female" and female_id:
        return female_id, "fish-feminina"
    if FISH_VOICE_MODE == "male" and male_id:
        return male_id, "fish-masculina"

    available: list[tuple[str, str]] = []
    if female_id:
        available.append((female_id, "fish-feminina"))
    if male_id and male_id != female_id:
        available.append((male_id, "fish-masculina"))
    if not available:
        return "", ""

    if FISH_VOICE_MODE == "random":
        import random
        return random.choice(available)

    index = _fish_bump_counter(f"{market_code}:{stream}")
    return available[index % len(available)]


def _fish_synthesize(
    text: str, reference_id: str, destination: Path
) -> tuple[bool, str]:
    """Gera a narracao via Fish Audio. Retorna (ok, detalhe_do_erro)."""
    body: dict[str, Any] = {
        "text": text,
        "format": "mp3",
        "mp3_bitrate": 128,
        "chunk_length": 300,
        "normalize": True,
        "latency": "normal",
        "prosody": {"speed": 1.0},
    }
    if reference_id:
        body["reference_id"] = reference_id

    try:
        response = requests.post(
            FISH_API_BASE + "/v1/tts",
            headers=_fish_headers({"model": FISH_MODEL}),
            json=body,
            timeout=180,
        )
    except Exception as error:
        return False, "excecao: " + str(error)

    if response.status_code != 200:
        try:
            detail = response.text[-400:]
        except Exception:
            detail = ""
        return False, "http " + str(response.status_code) + " " + detail

    content = response.content or b""
    if len(content) < 1000:
        return False, "audio muito pequeno (" + str(len(content)) + " bytes)"

    destination.unlink(missing_ok=True)
    destination.write_bytes(content)
    return True, ""


def create_voice(
    product: Product,
    text: str,
    destination: Path,
    stream: str = "reel",
) -> bool:
    import html

    edge_tts_command = _resolve_edge_tts_command()

    if not edge_tts_command:
        log_event(
            "VOICE_GENERATION_FAILED",
            asin=product.asin,
            market=product.marketplace_code,
            error="edge-tts nao foi encontrado.",
        )
        return False

    cleaned_text = html.unescape(
        str(text or "")
    )

    cleaned_text = cleaned_text.replace(
        "\\u200b",
        " ",
    )

    cleaned_text = cleaned_text.replace(
        "\u200b",
        " ",
    )

    cleaned_text = re.sub(
        r"<[^>]+>",
        " ",
        cleaned_text,
    )

    cleaned_text = re.sub(
        r"\s+",
        " ",
        cleaned_text,
    ).strip()
    cleaned_text = expand_spoken_units(
        cleaned_text,
        MARKETS[product.marketplace_code]["language"],
    )

    if len(cleaned_text) < 80:
        log_event(
            "VOICE_GENERATION_FAILED",
            asin=product.asin,
            market=product.marketplace_code,
            error="O roteiro ficou curto ou vazio.",
        )
        return False

    text_path = destination.with_suffix(
        ".txt"
    )

    text_path.write_text(
        cleaned_text,
        encoding="utf-8",
    )

    # Provider primario: Fish Audio (voz natural, pronuncia ingles dentro do
    # portugues). Falhou por qualquer motivo -> cai no Edge TTS abaixo.
    if _fish_enabled():
        fish_min_seconds = max(3.0, (len(cleaned_text) / 16.0) * 0.6)
        reference_id, voice_label = _fish_next_voice(product.marketplace_code, stream)
        if reference_id or voice_label:
            fish_ok, fish_detail = _fish_synthesize(
                cleaned_text, reference_id, destination
            )
            if fish_ok:
                try:
                    fish_seconds = float(audio_duration(destination))
                except Exception:
                    fish_seconds = 0.0
                if fish_seconds <= 0.0 or fish_seconds >= fish_min_seconds:
                    log_event(
                        "VOICE_GENERATED",
                        asin=product.asin,
                        market=product.marketplace_code,
                        voice=voice_label,
                        provider="fish",
                        reference_id=reference_id,
                        size_bytes=destination.stat().st_size,
                        audio_seconds=round(fish_seconds, 1),
                    )
                    return True
                log_event(
                    "FISH_AUDIO_TRUNCATED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    audio_seconds=round(fish_seconds, 1),
                    min_seconds=round(fish_min_seconds, 1),
                )
            else:
                log_event(
                    "FISH_GENERATION_FAILED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    error=fish_detail[-800:],
                )

    if product.marketplace_code == "BR":
        voices = [
            MARKETS[
                product.marketplace_code
            ]["voice"],
            "pt-BR-FranciscaNeural",
            "pt-BR-AntonioNeural",
            "pt-BR-ThalitaNeural",
        ]
    else:
        voices = [
            MARKETS[
                product.marketplace_code
            ]["voice"],
            "en-US-JennyNeural",
            "en-US-GuyNeural",
            "en-US-AriaNeural",
        ]

    unique_voices: list[str] = []

    for voice in voices:
        if voice and voice not in unique_voices:
            unique_voices.append(voice)

    errors: list[str] = []

    # edge-tts as vezes retorna sucesso (rc=0) mas com o audio TRUNCADO (so
    # parte da narracao) -> gerava reel curto, sem o pitch final. Exigimos que a
    # duracao do audio seja compativel com o texto; se vier truncado, tentamos
    # de novo e guardamos o maior audio como ultimo recurso.
    expected_seconds = len(cleaned_text) / 16.0  # ~16 caracteres por segundo
    min_seconds = max(3.0, expected_seconds * 0.6)

    best_backup = destination.with_name(destination.stem + ".best.mp3")
    best_seconds = 0.0

    for voice in unique_voices:
        for _attempt in range(2):
            destination.unlink(
                missing_ok=True
            )

            command = [
                *edge_tts_command,
                "--voice",
                voice,
                "--pitch=-2Hz",
                "--file",
                str(text_path),
                "--write-media",
                str(destination),
            ]

            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=240,
                )

            except Exception as error:
                errors.append(
                    voice
                    + ": "
                    + str(error)
                )
                break

            if not (
                completed.returncode == 0
                and destination.is_file()
                and destination.stat().st_size > 1000
            ):
                details = (
                    completed.stderr
                    or completed.stdout
                    or "Sem detalhes."
                )
                errors.append(
                    voice
                    + ": codigo="
                    + str(completed.returncode)
                    + " "
                    + details[-800:]
                )
                break

            try:
                seconds = float(audio_duration(destination))
            except Exception:
                seconds = 0.0

            # Sem medicao (0.0) ou audio completo -> aceita.
            if seconds <= 0.0 or seconds >= min_seconds:
                log_event(
                    "VOICE_GENERATED",
                    asin=product.asin,
                    market=product.marketplace_code,
                    voice=voice,
                    size_bytes=destination.stat().st_size,
                    audio_seconds=round(seconds, 1),
                )
                best_backup.unlink(missing_ok=True)
                return True

            # Audio truncado: guarda o maior ate agora e tenta de novo.
            if seconds > best_seconds:
                best_seconds = seconds
                shutil.copyfile(destination, best_backup)

            errors.append(
                voice
                + ": audio truncado "
                + format(seconds, ".1f")
                + "s (minimo "
                + format(min_seconds, ".1f")
                + "s)"
            )

    # Nenhuma voz entregou a narracao completa: usa o maior audio obtido
    # (melhor um reel um pouco curto do que nenhum), se houver.
    if best_seconds > 0.0 and best_backup.is_file():
        shutil.copyfile(best_backup, destination)
        best_backup.unlink(missing_ok=True)
        log_event(
            "VOICE_GENERATED",
            asin=product.asin,
            market=product.marketplace_code,
            voice="melhor_truncado",
            size_bytes=destination.stat().st_size,
            audio_seconds=round(best_seconds, 1),
        )
        return True

    best_backup.unlink(missing_ok=True)

    log_event(
        "VOICE_GENERATION_FAILED",
        asin=product.asin,
        market=product.marketplace_code,
        error=" | ".join(errors)[-5000:],
    )

    return False

def create_video_for_product(product: Product, report: Any = None) -> dict[str, Any]:
    def _sub(fraction: float, stage: str) -> None:
        # Progresso DENTRO deste video (0..1). O run_pipeline converte para a
        # % global, fazendo a barra andar durante a criacao (nao so no fim).
        if not report:
            return
        try:
            report(fraction, stage)
        except Exception:
            pass

    job_id = str(uuid.uuid4())
    work = WORK_DIRECTORY / job_id
    work.mkdir(parents=True, exist_ok=True)

    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", product.title).strip("-")[:50]
    output_name = (
        f"{product.platform}-{product.marketplace_code.lower()}-"
        f"{product.asin.lower()}-{slug}-{job_id[:8]}"
    )
    
    video_path = OUTPUT_DIRECTORY / (output_name + ".mp4")
    approval_path = PENDING_DIRECTORY / (output_name + ".json")

    try:
        # Usa as funcoes do authorized_broll_renderer
        _sub(0.03, "gerando roteiro")
        story = make_story(product)
        narration = narration_from_story(story, product.marketplace_code)

        _sub(0.12, "gerando narração (voz)")
        audio_path = work / "voice.mp3"
        voice_generated = create_voice(product, narration, audio_path)

        if not voice_generated:
            raise PipelineError("A voz IA nao foi gerada. O video nao sera criado sem narracao.")

        _sub(0.20, "baixando mídia do anúncio (fotos/vídeo)")
        broll_metadata = render_listing_video(
            product=product,
            audio_path=audio_path,
            output_path=video_path,
            work_directory=work,
            report=_sub,
        )

        _sub(0.88, "salvando vídeo")
        probe = probe_video(video_path)

        approval_record = {
            "job_id": job_id,
            "status": "AWAITING_APPROVAL",
            "created_at": utc_now(),
            "publication_executed": False,
            "marketplace_code": product.marketplace_code,
            "marketplace": (
                "shopee.com.br"
                if product.platform == "shopee"
                else MARKETS[product.marketplace_code]["marketplace"]
            ),
            "platform": product.platform,
            "partner_tag": (
                ""
                if product.platform == "shopee"
                else MARKETS[product.marketplace_code]["partner_tag"]
            ),
            "asin": product.asin,
            "title": product.title,
            "affiliate_url": product.detail_url,
            "platform": product.platform,
            "image_url": product.image_url,
            "source": product.source,
            "opportunity_score": product.score,
            "video_path": str(video_path),
            "voice_generated": voice_generated,
            "script": story,
            "narration": narration,
            "broll": broll_metadata.get("broll", {}),
            "probe": probe,
            "product": asdict(product),
        }

        write_json(approval_path, approval_record)
        log_event("VIDEO_AWAITING_APPROVAL", job_id=job_id, asin=product.asin, video=video_path.name)

        # Sidecar ao lado do .mp4 para o painel indexar o video de afiliado
        # e gerar o LINK CLICAVEL (link curto) que vai na legenda/descricao.
        try:
            sidecar_path = video_path.with_suffix(".json")
            write_json(
                sidecar_path,
                {
                    "kind": "affiliate",
                    "asin": product.asin,
                    "title": product.title,
                    "marketplace_code": product.marketplace_code,
                    "affiliate_url": product.detail_url,
                    "platform": product.platform,
                    "image_url": product.image_url,
                    "language": MARKETS[product.marketplace_code]["language"],
                    "job_id": job_id,
                    "created_at": utc_now(),
                    # Guardamos a NARRACAO e a CATEGORIA para que a analise
                    # automatica consiga conferir se o assunto do video bate
                    # com o produto antes de publicar sozinho.
                    "narration": narration,
                    "category": product.category,
                    "category_label": product.category_label,
                    # Marca e caracteristicas do anuncio p/ gerar hashtags
                    # fieis ao produto na hora de publicar.
                    "brand": product.brand,
                    "features": product.features,
                },
            )
        except Exception as sidecar_error:  # noqa: BLE001
            log_event(
                "SIDECAR_WRITE_FAILED",
                job_id=job_id,
                asin=product.asin,
                error=str(sidecar_error),
            )

        # ------------------------------------------------------------------
        # VERSAO DE LIVE (2o video): MESMA filmagem do reels, mas com uma
        # narracao de apresentadora AO VIVO (mais explicativa e apelativa) e
        # a legenda do que esta sendo falado. SEM ganchos de reels e SEM QR.
        # O audio original do reels NAO entra na live -- ele serve so pro reels.
        # Reaproveita o b-roll que o render do reels ja baixou (ainda esta na
        # pasta de trabalho, so limpa no finally). Se falhar, o reels segue ok.
        # ------------------------------------------------------------------
        try:
            broll_path = broll_metadata.get("broll_path")
            if product.platform == "shopee":
                log_event(
                    "LIVE_VARIANT_SKIPPED",
                    job_id=job_id,
                    asin=product.asin,
                    error="Shopee gera somente video de afiliado.",
                )
            elif not GENERATE_LIVE_VARIANTS:
                log_event(
                    "LIVE_VARIANT_SKIPPED",
                    job_id=job_id,
                    asin=product.asin,
                    error="geracao desativada por ATLAS_GENERATE_LIVE_VARIANTS",
                )
            elif broll_path and Path(broll_path).is_file():
                _sub(0.90, "gerando versão live")
                live_story = make_story(product, mode="live")
                live_narration = narration_from_story(
                    live_story,
                    product.marketplace_code,
                )
                live_audio = work / "voice_live.mp3"

                if create_voice(product, live_narration, live_audio, stream="live"):
                    live_video_path = OUTPUT_DIRECTORY / (output_name + ".live.mp4")
                    live_meta = render_live_variant(
                        product=product,
                        broll_path=Path(broll_path),
                        live_audio_path=live_audio,
                        live_narration=live_narration,
                        output_path=live_video_path,
                        work_directory=work,
                    )

                    # Sidecar da live: kind="affiliate_live" para a montagem
                    # preferir ESTE video (com audio de live) no lugar do reels.
                    write_json(
                        live_video_path.with_suffix(".json"),
                        {
                            "kind": "affiliate_live",
                            "asin": product.asin,
                            "title": product.title,
                            "marketplace_code": product.marketplace_code,
                            "affiliate_url": product.detail_url,
                            "language": MARKETS[product.marketplace_code]["language"],
                            "job_id": job_id,
                            "created_at": utc_now(),
                            "narration": live_narration,
                            "category": product.category,
                            "category_label": product.category_label,
                            "brand": product.brand,
                            "features": product.features,
                            "reel_video": video_path.name,
                            "duration_seconds": live_meta.get("duration_seconds"),
                        },
                    )
                    log_event(
                        "LIVE_VARIANT_READY",
                        job_id=job_id,
                        asin=product.asin,
                        video=live_video_path.name,
                    )
                else:
                    log_event(
                        "LIVE_VARIANT_SKIPPED",
                        job_id=job_id,
                        asin=product.asin,
                        error="voz da live nao foi gerada",
                    )
            else:
                log_event(
                    "LIVE_VARIANT_SKIPPED",
                    job_id=job_id,
                    asin=product.asin,
                    error="b-roll do reels indisponivel para reaproveitar",
                )
        except Exception as live_error:  # noqa: BLE001
            log_event(
                "LIVE_VARIANT_FAILED",
                job_id=job_id,
                asin=product.asin,
                error=str(live_error),
            )

        return approval_record

    except Exception as error:
        failure_path = FAILED_DIRECTORY / (output_name + ".json")
        write_json(failure_path, {
            "job_id": job_id,
            "status": "FAILED",
            "error": str(error),
            "product": asdict(product),
        })
        log_event("VIDEO_GENERATION_FAILED", job_id=job_id, asin=product.asin, error=str(error))
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_pipeline(
    maximum_videos: int = 10,
    selection: list[dict[str, Any]] | None = None,
    progress_callback: Any = None,
    on_video_ready: Any = None,
    stop_flag: Any = None,
) -> dict[str, Any]:
    ensure_directories()
    started_at = utc_now()
    target = max(1, maximum_videos)

    def _stop_requested() -> bool:
        # stop_flag e um threading.Event opcional (usado pelo robo automatico
        # de afiliados). So verificamos ENTRE um video e outro - nunca no meio
        # da geracao de um video, para nao corromper um arquivo pela metade.
        try:
            return bool(stop_flag is not None and stop_flag.is_set())
        except Exception:
            return False

    def _report(percent: float, title: str = "", stage: str = "") -> None:
        """Envia a % de progresso para o painel (igual aos reels)."""
        if not progress_callback:
            return
        try:
            safe = int(max(0, min(100, percent)))
            progress_callback(safe, title or "", stage or "")
        except Exception:
            pass

    log_event(
        "PIPELINE_STARTED",
        maximum_videos=target,
        strategy="SEARCH_UNTIL_SUCCESS",
        minimum_duration_seconds=30,
        maximum_duration_seconds=60,
        static_image_fallback=False,
    )

    products = discover_products()

    if not products:
        state = {
            "status": "WAITING_FOR_REAL_PRODUCT_SOURCE",
            "products_found": 0,
            "products_attempted": 0,
            "videos_created": 0,
            "target_videos": target,
        }
        write_json(STATE_PATH, state)
        return state

    already_processed = pending_product_keys()
    unique: dict[tuple[str, str], Product] = {}

    for product in products:
        key = canonical_product_key(product)
        if key not in unique:
            unique[key] = product

    eligible = [
        product
        for product in unique.values()
        if not product_was_processed(product, already_processed)
        and product.title
        and product.detail_url
    ]

    for product in eligible:
        score_product(product)

    priority_terms = (
        "fire tv",
        "echo",
        "alexa",
        "amazon",
        "samsung",
        "galaxy",
        "jbl",
        "logitech",
        "motorola",
        "xiaomi",
        "sony",
        "apple",
        "dell",
        "intelbras",
        "philco",
        "mondial",
        "oster",
    )

    # Ordenacao: por padrao (modo impulso), o SCORE de conversao (que ja
    # inclui o fator de preco) manda, e a marca conhecida vira so desempate.
    # Isso evita empurrar itens caros de marca (que convertem mal em trafego
    # frio) para o topo. Com ATLAS_AFFILIATE_IMPULSE_MODE=0 volta ao antigo
    # (marca conhecida primeiro).
    impulse_mode = os.getenv("ATLAS_AFFILIATE_IMPULSE_MODE", "1").strip().lower() not in ("0", "false", "no", "off")
    if impulse_mode:
        eligible.sort(
            key=lambda product: (
                product.score,
                any(term in product.title.lower() for term in priority_terms),
                product.review_count or 0,
            ),
            reverse=True,
        )
    else:
        eligible.sort(
            key=lambda product: (
                any(
                    term in product.title.lower()
                    for term in priority_terms
                ),
                product.score,
                product.review_count or 0,
            ),
            reverse=True,
        )

    # Se veio uma selecao do painel (categorias + quantidade por categoria),
    # filtra os produtos elegiveis para gerar apenas o que foi escolhido.
    if selection:
        wanted: dict[tuple[str, str, str], int] = {}
        for item in selection:
            try:
                market = str(item.get("marketplace_code") or "").strip().upper()
                category = str(item.get("category") or "").strip().lower()
                platform = str(item.get("platform") or "amazon").strip().lower()
                quantity = int(item.get("quantity") or 0)
            except Exception:
                continue
            if market and category and quantity > 0:
                selection_key = (platform, market, category)
                wanted[selection_key] = wanted.get(selection_key, 0) + quantity

        picked: list[Product] = []
        used: dict[tuple[str, str, str], int] = {}
        for product in eligible:
            key = (
                product.platform,
                product.marketplace_code,
                product.category or "outros",
            )
            cap = wanted.get(key)
            if not cap or used.get(key, 0) >= cap:
                continue
            used[key] = used.get(key, 0) + 1
            picked.append(product)

        eligible = picked
        target = len(eligible)

    completed: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    attempted = 0

    _report(0, "", "Preparando produtos…")

    for product in eligible:
        if len(completed) >= target:
            break

        if _stop_requested():
            # Robo automatico foi desligado enquanto este lote rodava: para
            # AGORA, entre um video e outro (o video atual ja terminou),
            # em vez de seguir gerando o resto do lote sem ninguem saber.
            _report(
                int(len(completed) / max(1, target) * 100),
                "",
                "Robô parado pelo usuário — lote interrompido.",
            )
            log_event(
                "PIPELINE_STOPPED_BY_USER",
                videos_created=len(completed),
                target_videos=target,
            )
            break

        if not reserve_product(product):
            log_event(
                "PRODUCT_SKIPPED_ALREADY_RESERVED",
                market=product.marketplace_code,
                asin=product.asin,
                title=product.title,
            )
            continue

        attempted += 1

        done_before = len(completed)
        _report(
            int(done_before / max(1, target) * 100),
            product.title,
            f"Gerando vídeo {done_before + 1} de {target}",
        )

        def _sub_progress(
            fraction: float,
            stage: str,
            _title: str = product.title,
            _base: int = done_before,
        ) -> None:
            # Converte o progresso DENTRO do video (0..1) em % global, para a
            # barra andar durante a criacao — e nao ficar parada ate o fim.
            frac = max(0.0, min(1.0, float(fraction)))
            overall = (_base + frac) / max(1, target) * 100
            _report(overall, _title, f"Vídeo {_base + 1} de {target}: {stage}")

        try:
            completed.append(
                create_video_for_product(product, report=_sub_progress)
            )
            # Assim que ESTE video fica pronto, avisa quem pediu (o
            # job_service) para JA publicar este video — desde que passe
            # no controle de qualidade. Nao espera o lote inteiro terminar.
            if on_video_ready:
                try:
                    on_video_ready(completed[-1])
                except Exception:
                    pass
        except Exception as error:
            failures.append(
                {
                    "marketplace_code": product.marketplace_code,
                    "asin": product.asin,
                    "title": product.title,
                    "error": str(error),
                }
            )

            log_event(
                "PRODUCT_SKIPPED",
                market=product.marketplace_code,
                asin=product.asin,
                title=product.title,
                reason=str(error),
            )
        finally:
            release_product_reservation(product)

    stopped_early = _stop_requested()
    if not stopped_early:
        _report(100, "", "Vídeos gerados")

    if completed:
        status = "AWAITING_APPROVAL"
    elif eligible:
        status = "FAILED_NO_VALID_AUTHORIZED_BROLL"
    else:
        status = "NO_NEW_PRODUCTS"

    state = {
        "status": status,
        "started_at": started_at,
        "completed_at": utc_now(),
        "products_found": len(products),
        "products_unique": len(unique),
        "products_eligible": len(eligible),
        "products_attempted": attempted,
        "target_videos": target,
        "videos_created": len(completed),
        "failed_attempts": len(failures),
        "failures": failures,
        "publication_executed": False,
        "static_image_fallback": False,
        "stopped_by_user": stopped_early,
        "pending_approval": [
            {
                "marketplace_code": record["marketplace_code"],
                "asin": record["asin"],
                "title": record["title"],
                "video_path": record["video_path"],
                "affiliate_url": record["affiliate_url"],
                "broll": record.get("broll", {}),
            }
            for record in completed
        ],
    }

    write_json(STATE_PATH, state)

    log_event(
        "PIPELINE_COMPLETED",
        status=status,
        products_attempted=attempted,
        target_videos=target,
        videos_created=len(completed),
        failed_attempts=len(failures),
        static_image_fallback=False,
    )

    return state

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-videos", type=int, default=10)
    arguments = parser.parse_args()

    # O Limite não tem mais trava rígida, ele aceita o que você mandar.
    result = run_pipeline(maximum_videos=arguments.max_videos)

    print("=" * 72)
    print("ATLAS AMAZON REAL PRODUCT PIPELINE - OMNI B-ROLL")
    print("=" * 72)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print("FINAL_STATUS=" + result["status"])


if __name__ == "__main__":
    main()