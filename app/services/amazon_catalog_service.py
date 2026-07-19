import csv
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.models.affiliate import MarketplaceEnum
from app.schemas.amazon_catalog import (
    AmazonMarketplace,
    AmazonProductInput,
)


ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

ASIN_PATH_PATTERNS = [
    re.compile(r"/dp/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE),
    re.compile(
        r"/gp/product/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/exec/obidos/ASIN/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
]

SHORT_DOMAINS = {
    "a.co",
    "www.a.co",
    "amzn.to",
    "www.amzn.to",
}

MARKETPLACE_CONFIG = {
    AmazonMarketplace.AMAZON_BR: {
        "database_enum": MarketplaceEnum.AMAZON_BR,
        "currency": "BRL",
        "canonical_host": "www.amazon.com.br",
        "allowed_hosts": {
            "amazon.com.br",
            "www.amazon.com.br",
        },
        "associate_tag_env": "AMAZON_BR_ASSOCIATE_TAG",
    },
    AmazonMarketplace.AMAZON_US: {
        "database_enum": MarketplaceEnum.AMAZON_US,
        "currency": "USD",
        "canonical_host": "www.amazon.com",
        "allowed_hosts": {
            "amazon.com",
            "www.amazon.com",
            "smile.amazon.com",
        },
        "associate_tag_env": "AMAZON_US_ASSOCIATE_TAG",
    },
}


@dataclass
class ValidatedAmazonProduct:
    marketplace: MarketplaceEnum
    asin: str
    title: str
    category: Optional[str]
    description: Optional[str]
    features: list[str]
    original_url: str
    product_url: str
    affiliate_url: str
    associate_tag: str
    image_url: Optional[str]
    price_text: Optional[str]
    currency: str
    notes: Optional[str]
    is_short_affiliate_url: bool
    warnings: list[str]


class AmazonCatalogService:
    def public_base_url(self) -> str:
        return os.getenv(
            "ATLAS_PUBLIC_BASE_URL",
            "http://localhost:8000",
        ).strip().rstrip("/")

    def csv_max_rows(self) -> int:
        raw_value = os.getenv("AMAZON_CSV_MAX_ROWS", "500")

        try:
            return max(1, min(int(raw_value), 5000))
        except ValueError:
            return 500

    def expected_tag(
        self,
        marketplace: AmazonMarketplace,
    ) -> str:
        config = MARKETPLACE_CONFIG[marketplace]
        environment_name = config["associate_tag_env"]
        tag = os.getenv(environment_name, "").strip()

        if not tag:
            raise ValueError(
                f"{environment_name} nao esta configurada."
            )

        return tag

    @staticmethod
    def clean_optional(
        value,
    ) -> Optional[str]:
        if value is None:
            return None

        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def normalize_url(url: str) -> str:
        normalized = str(url or "").strip()

        if not normalized:
            raise ValueError("URL obrigatoria.")

        parsed = urlparse(normalized)

        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError(
                "A URL deve usar http ou https."
            )

        if not parsed.netloc:
            raise ValueError("URL sem dominio valido.")

        clean_parsed = parsed._replace(
            fragment="",
        )

        return urlunparse(clean_parsed)

    @staticmethod
    def url_host(url: str) -> str:
        return (
            urlparse(url)
            .netloc
            .split("@")[-1]
            .split(":")[0]
            .lower()
            .strip(".")
        )

    @staticmethod
    def extract_asin_from_url(url: str) -> Optional[str]:
        parsed = urlparse(url)
        path = parsed.path or ""

        for pattern in ASIN_PATH_PATTERNS:
            match = pattern.search(path)

            if match:
                return match.group(1).upper()

        query = parse_qs(parsed.query)

        for key in ("asin", "ASIN"):
            values = query.get(key)

            if values:
                candidate = str(values[0]).strip().upper()

                if ASIN_PATTERN.fullmatch(candidate):
                    return candidate

        return None

    def validate_domain(
        self,
        url: str,
        marketplace: AmazonMarketplace,
        allow_short: bool,
    ) -> tuple[bool, str]:
        host = self.url_host(url)
        config = MARKETPLACE_CONFIG[marketplace]

        if host in config["allowed_hosts"]:
            return False, host

        if allow_short and host in SHORT_DOMAINS:
            return True, host

        expected_domains = ", ".join(
            sorted(config["allowed_hosts"])
        )

        raise ValueError(
            f"Dominio {host!r} nao pertence ao marketplace "
            f"{marketplace.value}. Esperado: {expected_domains}."
        )

    @staticmethod
    def extract_tag(url: str) -> Optional[str]:
        query = parse_qs(urlparse(url).query)
        values = query.get("tag")

        if not values:
            return None

        return str(values[0]).strip() or None

    def canonical_product_url(
        self,
        marketplace: AmazonMarketplace,
        asin: str,
    ) -> str:
        host = MARKETPLACE_CONFIG[marketplace]["canonical_host"]
        return f"https://{host}/dp/{asin}"

    def validate_image_url(
        self,
        image_url: Optional[str],
    ) -> Optional[str]:
        if not image_url:
            return None

        normalized = self.normalize_url(image_url)
        parsed = urlparse(normalized)
        extension = os.path.splitext(parsed.path.lower())[1]

        if extension and extension not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        }:
            raise ValueError(
                "image_url deve apontar para JPG, PNG ou WEBP."
            )

        return normalized

    def validate_product(
        self,
        payload: AmazonProductInput,
    ) -> ValidatedAmazonProduct:
        marketplace = payload.marketplace
        config = MARKETPLACE_CONFIG[marketplace]

        asin = payload.asin.strip().upper()

        if not ASIN_PATTERN.fullmatch(asin):
            raise ValueError(
                "ASIN invalido. Use exatamente 10 letras ou numeros."
            )

        expected_tag = self.expected_tag(marketplace)
        supplied_tag = (
            payload.associate_tag.strip()
            if payload.associate_tag
            else expected_tag
        )

        if supplied_tag != expected_tag:
            raise ValueError(
                f"associate_tag invalida para {marketplace.value}."
            )

        affiliate_url = self.normalize_url(
            payload.affiliate_url
        )

        is_short_url, _ = self.validate_domain(
            url=affiliate_url,
            marketplace=marketplace,
            allow_short=True,
        )

        affiliate_url_asin = self.extract_asin_from_url(
            affiliate_url
        )

        affiliate_url_tag = self.extract_tag(
            affiliate_url
        )

        warnings = []

        if is_short_url:
            warnings.append(
                "Link Amazon encurtado aceito. O destino, ASIN e tag "
                "devem ter sido conferidos no SiteStripe ou Mobile GetLink."
            )
        else:
            if affiliate_url_asin and affiliate_url_asin != asin:
                raise ValueError(
                    "O ASIN da affiliate_url nao corresponde "
                    "ao ASIN informado."
                )

            if not affiliate_url_tag:
                raise ValueError(
                    "A affiliate_url completa nao possui o parametro tag. "
                    "Gere o link pelo SiteStripe."
                )

            if affiliate_url_tag != expected_tag:
                raise ValueError(
                    "A tag presente na affiliate_url nao corresponde "
                    "a conta configurada."
                )

        product_url = self.canonical_product_url(
            marketplace=marketplace,
            asin=asin,
        )

        if payload.original_url:
            original_url = self.normalize_url(
                payload.original_url
            )

            original_is_short, _ = self.validate_domain(
                url=original_url,
                marketplace=marketplace,
                allow_short=False,
            )

            if original_is_short:
                raise ValueError(
                    "original_url nao pode ser link encurtado."
                )

            original_asin = self.extract_asin_from_url(
                original_url
            )

            if original_asin and original_asin != asin:
                raise ValueError(
                    "O ASIN da original_url nao corresponde "
                    "ao ASIN informado."
                )
        else:
            original_url = product_url

        currency = (
            payload.currency
            or config["currency"]
        ).strip().upper()

        if currency != config["currency"]:
            raise ValueError(
                f"Moeda invalida para {marketplace.value}. "
                f"Use {config['currency']}."
            )

        image_url = self.validate_image_url(
            payload.image_url
        )

        if payload.price_text:
            warnings.append(
                "Preco armazenado apenas como valor observado. "
                "Confirme o preco atual na Amazon antes de publicar."
            )

        return ValidatedAmazonProduct(
            marketplace=config["database_enum"],
            asin=asin,
            title=payload.title.strip(),
            category=self.clean_optional(payload.category),
            description=self.clean_optional(
                payload.description
            ),
            features=payload.features,
            original_url=original_url,
            product_url=product_url,
            affiliate_url=affiliate_url,
            associate_tag=expected_tag,
            image_url=image_url,
            price_text=self.clean_optional(
                payload.price_text
            ),
            currency=currency,
            notes=self.clean_optional(payload.notes),
            is_short_affiliate_url=is_short_url,
            warnings=warnings,
        )

    @staticmethod
    def split_features(value: Optional[str]) -> list[str]:
        if not value:
            return []

        result = []
        seen = set()

        for item in re.split(r"[|;\n]+", str(value)):
            normalized = item.strip()

            if not normalized:
                continue

            key = normalized.lower()

            if key in seen:
                continue

            seen.add(key)
            result.append(normalized)

        return result[:20]

    @staticmethod
    def parse_csv_text(
        csv_text: str,
    ) -> list[dict]:
        if not csv_text or not csv_text.strip():
            raise ValueError("Arquivo CSV vazio.")

        sample = csv_text[:4096]

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=",;",
            )
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(
            io.StringIO(csv_text),
            dialect=dialect,
        )

        if not reader.fieldnames:
            raise ValueError(
                "CSV sem cabecalho."
            )

        normalized_fieldnames = [
            str(field or "").strip().lower()
            for field in reader.fieldnames
        ]

        required = {
            "marketplace",
            "asin",
            "title",
            "affiliate_url",
        }

        missing = required.difference(
            normalized_fieldnames
        )

        if missing:
            raise ValueError(
                "Campos obrigatorios ausentes no CSV: "
                + ", ".join(sorted(missing))
            )

        rows = []

        for raw_row in reader:
            normalized_row = {}

            for key, value in raw_row.items():
                normalized_key = str(
                    key or ""
                ).strip().lower()

                normalized_row[normalized_key] = (
                    str(value).strip()
                    if value is not None
                    else ""
                )

            if not any(normalized_row.values()):
                continue

            rows.append(normalized_row)

        return rows

    def csv_row_to_payload(
        self,
        row: dict,
    ) -> AmazonProductInput:
        marketplace = str(
            row.get("marketplace") or ""
        ).strip().lower()

        return AmazonProductInput(
            marketplace=marketplace,
            asin=row.get("asin", ""),
            title=row.get("title", ""),
            category=self.clean_optional(
                row.get("category")
            ),
            description=self.clean_optional(
                row.get("description")
            ),
            features=self.split_features(
                row.get("features")
            ),
            original_url=self.clean_optional(
                row.get("original_url")
            ),
            affiliate_url=row.get(
                "affiliate_url",
                "",
            ),
            associate_tag=self.clean_optional(
                row.get("associate_tag")
            ),
            image_url=self.clean_optional(
                row.get("image_url")
            ),
            price_text=self.clean_optional(
                row.get("price_text")
            ),
            currency=self.clean_optional(
                row.get("currency")
            ),
            notes=self.clean_optional(
                row.get("notes")
            ),
        )

    def affiliate_link_with_tracking(
        self,
        product_id: int,
        platform: Optional[str] = None,
        campaign: Optional[str] = None,
    ) -> str:
        query = {}

        if platform:
            query["platform"] = platform

        if campaign:
            query["campaign"] = campaign

        suffix = ""

        if query:
            suffix = "?" + urlencode(query)

        return (
            f"{self.public_base_url()}"
            f"/affiliate/amazon/go/{product_id}"
            f"{suffix}"
        )

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)


amazon_catalog_service = AmazonCatalogService()