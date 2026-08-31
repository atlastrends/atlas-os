from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ATLAS_ROOT = Path(__file__).resolve().parents[2]
SHOPEE_STORAGE = ATLAS_ROOT / "storage" / "shopee"
CATALOG_PATH = SHOPEE_STORAGE / "catalog.json"
PIPELINE_IMPORT_PATH = SHOPEE_STORAGE / "imports" / "affiliate_catalog.json"

OFFICIAL_AFFILIATE_URL = "https://affiliate.shopee.com.br/"
OFFICIAL_HELP_URL = "https://help.shopee.com.br/portal?source=10"
_SHOPEE_HOST_RE = re.compile(r"(^|\.)shopee\.com\.br$", re.IGNORECASE)
_SHOPEE_MEDIA_HOST_RE = re.compile(
    r"(^|\.)(shopee\.com\.br|shopeemobile\.com|susercontent\.com)$",
    re.IGNORECASE,
)


class ShopeeCatalogError(ValueError):
    pass


@dataclass(frozen=True)
class ShopeeProduct:
    product_id: str
    title: str
    category: str
    price_display: str
    affiliate_url: str
    image_url: str
    video_url: str
    commission_rate: float
    commission_amount: float
    sold_count: int
    media_rights_confirmed: bool
    description: str = ""
    features: tuple[str, ...] = ()
    rating: float = 0.0
    review_count: int = 0
    official_url: str = ""
    source: str = "shopee_affiliate_export"

    @property
    def score(self) -> float:
        sales_signal = min(max(self.sold_count, 0), 1_000_000) ** 0.5
        return round(
            sales_signal
            + max(self.commission_rate, 0) * 3
            + max(self.commission_amount, 0),
            2,
        )

    @property
    def ready_for_video(self) -> bool:
        return bool(
            self.affiliate_url
            and self.title
            and (self.image_url or self.video_url)
            and self.media_rights_confirmed
        )

    def serialized(self) -> dict[str, Any]:
        result = asdict(self)
        result["score"] = self.score
        result["ready_for_video"] = self.ready_for_video
        return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any, maximum: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:maximum]


def _number(value: Any) -> float:
    text = re.sub(r"[^0-9,.-]", "", str(value or "")).strip()
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ShopeeCatalogError(f"Valor numerico invalido: {value}") from exc


def _integer(value: Any) -> int:
    return max(0, int(_number(value)))


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_affiliate_url(value: Any) -> str:
    url = _clean(value, 2000)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not _SHOPEE_HOST_RE.search(host):
        raise ShopeeCatalogError(
            "O link de afiliado deve ser HTTPS e pertencer a shopee.com.br."
        )
    return url


def _optional_url(value: Any, field_name: str) -> str:
    url = _clean(value, 2000)
    if not url:
        return ""
    if not _is_http_url(url):
        raise ShopeeCatalogError(f"{field_name} deve ser uma URL HTTP/HTTPS valida.")
    host = (urlparse(url).hostname or "").lower()
    if not _SHOPEE_MEDIA_HOST_RE.search(host):
        raise ShopeeCatalogError(
            f"{field_name} deve usar midia oficial da Shopee ou de um CDN Shopee."
        )
    return url


def _official_url(value: Any) -> str:
    url = _clean(value, 2000)
    if not url:
        return ""
    if not _is_http_url(url) or urlparse(url).scheme != "https":
        raise ShopeeCatalogError(
            "official_url deve ser uma URL HTTPS valida."
        )
    return url


def _row_value(row: dict[str, Any], *names: str) -> Any:
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(key).lower()): value
        for key, value in row.items()
    }
    for name in names:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        if key in normalized:
            return normalized[key]
    return ""


def _features(value: Any) -> tuple[str, ...]:
    return tuple(
        feature
        for feature in (
            _clean(part, 240)
            for part in str(value or "").split("|")
        )
        if feature
    )[:8]


def _product_id(row: dict[str, Any], affiliate_url: str) -> str:
    supplied = _clean(
        _row_value(row, "product_id", "item_id", "id_produto", "id"),
        80,
    )
    if supplied:
        return supplied
    return "S" + hashlib.sha1(affiliate_url.encode("utf-8")).hexdigest()[:15].upper()


def parse_csv(content: bytes, *, rights_confirmed: bool) -> list[ShopeeProduct]:
    if not rights_confirmed:
        raise ShopeeCatalogError(
            "Confirme que as imagens/videos foram fornecidos pela Shopee ou pelo "
            "vendedor e que voce tem autorizacao para reutiliza-los."
        )
    if len(content) > 5_000_000:
        raise ShopeeCatalogError("O CSV excede o limite de 5 MB.")

    decoded: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ShopeeCatalogError("Nao foi possivel identificar a codificacao do CSV.")

    sample = decoded[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(decoded), dialect=dialect)
    if not reader.fieldnames:
        raise ShopeeCatalogError("O CSV nao possui cabecalho.")

    products: list[ShopeeProduct] = []
    errors: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        if not any(_clean(value) for value in row.values()):
            continue
        try:
            affiliate_url = _validate_affiliate_url(
                _row_value(
                    row,
                    "affiliate_url",
                    "link_afiliado",
                    "link de afiliado",
                    "url",
                )
            )
            title = _clean(
                _row_value(row, "title", "nome_produto", "produto", "nome"),
                500,
            )
            if not title:
                raise ShopeeCatalogError("titulo do produto ausente")
            product = ShopeeProduct(
                product_id=_product_id(row, affiliate_url),
                title=title,
                category=_clean(
                    _row_value(row, "category", "categoria"), 160
                )
                or "outros",
                price_display=_clean(
                    _row_value(row, "price", "preco", "price_display"), 80
                ),
                affiliate_url=affiliate_url,
                image_url=_optional_url(
                    _row_value(row, "image_url", "imagem", "url_imagem"),
                    "image_url",
                ),
                video_url=_optional_url(
                    _row_value(row, "video_url", "video", "url_video"),
                    "video_url",
                ),
                commission_rate=max(
                    0.0,
                    _number(
                        _row_value(
                            row,
                            "commission_rate",
                            "comissao_percentual",
                            "comissao",
                        )
                    ),
                ),
                commission_amount=max(
                    0.0,
                    _number(
                        _row_value(
                            row,
                            "commission_amount",
                            "valor_comissao",
                        )
                    ),
                ),
                sold_count=_integer(
                    _row_value(
                        row,
                        "sold_count",
                        "vendidos",
                        "unidades_vendidas",
                    )
                ),
                media_rights_confirmed=True,
                description=_clean(
                    _row_value(row, "description", "descricao"),
                    1200,
                ),
                features=_features(
                    _row_value(
                        row,
                        "features",
                        "destaques",
                        "caracteristicas",
                    )
                ),
                rating=max(
                    0.0,
                    min(
                        5.0,
                        _number(
                            _row_value(row, "rating", "avaliacao", "nota")
                        ),
                    ),
                ),
                review_count=_integer(
                    _row_value(
                        row,
                        "review_count",
                        "avaliacoes",
                        "quantidade_avaliacoes",
                    )
                ),
                official_url=_official_url(
                    _row_value(
                        row,
                        "official_url",
                        "pagina_oficial",
                        "url_oficial",
                    )
                ),
            )
            products.append(product)
        except ShopeeCatalogError as exc:
            errors.append(f"linha {line_number}: {exc}")

    if errors:
        preview = "; ".join(errors[:8])
        suffix = f"; e mais {len(errors) - 8} erro(s)" if len(errors) > 8 else ""
        raise ShopeeCatalogError(preview + suffix)
    if not products:
        raise ShopeeCatalogError("O CSV nao contem produtos validos.")

    deduplicated = {product.product_id: product for product in products}
    return sorted(
        deduplicated.values(),
        key=lambda product: product.score,
        reverse=True,
    )


def save_catalog(products: list[ShopeeProduct]) -> dict[str, Any]:
    SHOPEE_STORAGE.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _now_iso(),
        "source": "shopee_affiliate_export",
        "products": [product.serialized() for product in products],
    }
    temporary = CATALOG_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(CATALOG_PATH)
    materialize_pipeline_import(products)
    return payload


def load_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        return {"updated_at": None, "source": None, "products": []}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ShopeeCatalogError(f"Catalogo Shopee corrompido: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("products"), list):
        raise ShopeeCatalogError("O catalogo Shopee possui formato invalido.")
    return data


def list_products() -> list[dict[str, Any]]:
    products = load_catalog()["products"]
    return sorted(
        products,
        key=lambda product: float(product.get("score") or 0),
        reverse=True,
    )


def materialize_pipeline_import(products: list[ShopeeProduct]) -> None:
    PIPELINE_IMPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for product in products:
        if not product.ready_for_video:
            continue
        for market, language in (("BR", "pt-BR"), ("US", "en-US")):
            records.append(
                {
                    "marketplace_code": market,
                    "platform": "shopee",
                    "language": language,
                    "asin": (
                        "S"
                        + hashlib.sha1(
                            f"{product.product_id}:{language}".encode("utf-8")
                        ).hexdigest()[:9].upper()
                    ),
                    "product_id": product.product_id,
                    "title": product.title,
                    "price_display": product.price_display,
                    "image_url": product.image_url,
                    "listing_video_url": product.video_url,
                    "affiliate_url": product.affiliate_url,
                    "source": product.source,
                    "category": product.category,
                    "category_label": product.category,
                    "commission_rate": product.commission_rate,
                    "commission_amount": product.commission_amount,
                    "sold_count": product.sold_count,
                    "media_rights_confirmed": product.media_rights_confirmed,
                    "description": product.description,
                    "features": list(product.features),
                    "rating": product.rating,
                    "review_count": product.review_count,
                    "official_page_urls": (
                        [product.official_url]
                        if product.official_url
                        else []
                    ),
                }
            )
    temporary = PIPELINE_IMPORT_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(PIPELINE_IMPORT_PATH)


def status() -> dict[str, Any]:
    catalog = load_catalog()
    products = catalog["products"]
    return {
        "affiliate_url": OFFICIAL_AFFILIATE_URL,
        "help_url": OFFICIAL_HELP_URL,
        "catalog_updated_at": catalog.get("updated_at"),
        "product_count": len(products),
        "ready_count": sum(
            1 for product in products if product.get("ready_for_video")
        ),
        "program_status": "requires_user_login",
        "workflow": [
            "Entrar no portal oficial da Shopee e concluir a inscricao.",
            "Aguardar a aprovacao e acessar o catalogo de ofertas do afiliado.",
            "Exportar os produtos com vendas e comissoes oficiais.",
            "Informar somente midia oficial/licenciada do produto exato.",
            "Importar o CSV no Atlas, revisar o ranking e gerar PT + EN.",
            "Validar os videos antes de publicar ou incluir na Live Video.",
        ],
    }
