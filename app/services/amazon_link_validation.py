import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse


ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")

ASIN_PATH_PATTERNS = (
    re.compile(
        r"/dp/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/gp/product/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/gp/aw/d/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"/product/([A-Z0-9]{10})(?:[/?]|$)",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class AmazonMarketplaceRule:
    marketplace: str
    label: str
    expected_tag: str
    currency: str
    amazon_domain: str


@dataclass(frozen=True)
class ValidatedAmazonLinks:
    marketplace: str
    asin: str
    original_url: str
    affiliate_url: str
    associate_tag: str
    currency: str
    is_short_affiliate_url: bool


def _environment_value(
    primary_name: str,
    secondary_name: str,
    default: str,
) -> str:
    value = os.getenv(
        primary_name,
        os.getenv(secondary_name, default),
    )

    return str(value or default).strip()


def marketplace_rules() -> dict[str, AmazonMarketplaceRule]:
    return {
        "amazon_br": AmazonMarketplaceRule(
            marketplace="amazon_br",
            label="Amazon Brasil",
            expected_tag=_environment_value(
                "AMAZON_BR_ASSOCIATE_TAG",
                "AMAZON_BR_TAG",
                "achadosatlasb-20",
            ),
            currency="BRL",
            amazon_domain="amazon.com.br",
        ),
        "amazon_us": AmazonMarketplaceRule(
            marketplace="amazon_us",
            label="Amazon USA",
            expected_tag=_environment_value(
                "AMAZON_US_ASSOCIATE_TAG",
                "AMAZON_US_TAG",
                "atlasfindsus-20",
            ),
            currency="USD",
            amazon_domain="amazon.com",
        ),
    }


def normalize_marketplace(marketplace: Any) -> str:
    raw_value = getattr(marketplace, "value", marketplace)
    normalized = str(raw_value or "").strip().lower()

    if normalized not in marketplace_rules():
        raise ValueError(
            "Marketplace invalido. Use amazon_br ou amazon_us."
        )

    return normalized


def normalize_asin(asin: Any) -> str:
    normalized = str(asin or "").strip().upper()

    if not ASIN_PATTERN.fullmatch(normalized):
        raise ValueError(
            "ASIN invalido. Informe exatamente 10 caracteres "
            "alfanumericos."
        )

    return normalized


def normalize_required_text(
    value: Any,
    field_name: str,
) -> str:
    normalized = str(value or "").strip()

    if not normalized:
        raise ValueError(f"{field_name} e obrigatorio.")

    return normalized


def normalize_currency(
    marketplace: Any,
    currency: Any,
) -> str:
    normalized_marketplace = normalize_marketplace(marketplace)
    rule = marketplace_rules()[normalized_marketplace]

    normalized_currency = str(currency or "").strip().upper()

    if not normalized_currency:
        return rule.currency

    if normalized_currency != rule.currency:
        raise ValueError(
            f"currency invalida para {rule.label}. "
            f"Esperado: {rule.currency}."
        )

    return normalized_currency


def _normalize_host(parsed_url) -> str:
    host = str(parsed_url.hostname or "").strip().lower()
    return host.rstrip(".")


def _is_amazon_host(
    host: str,
    expected_domain: str,
) -> bool:
    return (
        host == expected_domain
        or host.endswith("." + expected_domain)
    )


def _is_short_amazon_host(host: str) -> bool:
    return host in {
        "amzn.to",
        "www.amzn.to",
    }


def _extract_url_asin(path: str) -> str | None:
    for pattern in ASIN_PATH_PATTERNS:
        match = pattern.search(path or "")

        if match:
            return match.group(1).upper()

    return None


def _extract_tag_values(parsed_url) -> list[str]:
    query = parse_qs(
        parsed_url.query,
        keep_blank_values=True,
    )

    values = query.get("tag", [])

    return [
        str(value or "").strip()
        for value in values
    ]


def validate_amazon_url(
    *,
    url: Any,
    marketplace: Any,
    asin: Any,
    associate_tag: Any,
    field_name: str,
    require_tag_for_direct_url: bool,
) -> tuple[str, bool]:
    normalized_url = normalize_required_text(
        url,
        field_name,
    )

    normalized_marketplace = normalize_marketplace(
        marketplace
    )

    normalized_asin = normalize_asin(asin)

    normalized_tag = normalize_required_text(
        associate_tag,
        "associate_tag",
    )

    rule = marketplace_rules()[normalized_marketplace]

    try:
        parsed = urlparse(normalized_url)
    except Exception as error:
        raise ValueError(
            f"{field_name} invalida."
        ) from error

    if parsed.scheme.lower() != "https":
        raise ValueError(
            f"{field_name} deve usar HTTPS."
        )

    if parsed.username or parsed.password:
        raise ValueError(
            f"{field_name} nao pode conter usuario ou senha."
        )

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError(
            f"{field_name} possui porta invalida."
        ) from error

    if port not in {None, 443}:
        raise ValueError(
            f"{field_name} possui porta nao permitida."
        )

    host = _normalize_host(parsed)

    if not host:
        raise ValueError(
            f"{field_name} nao possui dominio valido."
        )

    is_short_url = _is_short_amazon_host(host)

    if not is_short_url and not _is_amazon_host(
        host,
        rule.amazon_domain,
    ):
        raise ValueError(
            f"{field_name} deve usar um dominio oficial da "
            f"{rule.label}."
        )

    if not is_short_url:
        url_asin = _extract_url_asin(parsed.path)

        if url_asin and url_asin != normalized_asin:
            raise ValueError(
                f"O ASIN presente em {field_name} nao corresponde "
                f"ao ASIN informado."
            )

    tag_values = _extract_tag_values(parsed)

    if any(not value for value in tag_values):
        raise ValueError(
            f"{field_name} possui tracking tag vazia."
        )

    if tag_values:
        unique_tags = set(tag_values)

        if len(unique_tags) != 1:
            raise ValueError(
                f"{field_name} possui tracking tags conflitantes."
            )

        url_tag = tag_values[0]

        if url_tag != normalized_tag:
            raise ValueError(
                f"A tracking tag presente em {field_name} nao "
                f"corresponde a associate_tag."
            )

        if url_tag != rule.expected_tag:
            raise ValueError(
                f"Tracking tag invalida para {rule.label}. "
                f"Esperado: {rule.expected_tag}."
            )

    elif require_tag_for_direct_url and not is_short_url:
        raise ValueError(
            f"{field_name} deve conter a tracking tag oficial "
            f"no parametro tag."
        )

    return normalized_url, is_short_url


def validate_amazon_product_links(
    *,
    marketplace: Any,
    asin: Any,
    original_url: Any,
    affiliate_url: Any,
    associate_tag: Any,
    currency: Any = None,
) -> ValidatedAmazonLinks:
    normalized_marketplace = normalize_marketplace(
        marketplace
    )

    normalized_asin = normalize_asin(asin)

    normalized_tag = normalize_required_text(
        associate_tag,
        "associate_tag",
    )

    rule = marketplace_rules()[normalized_marketplace]

    if normalized_tag != rule.expected_tag:
        raise ValueError(
            f"associate_tag invalido para {rule.label}. "
            f"Esperado: {rule.expected_tag}."
        )

    normalized_currency = normalize_currency(
        normalized_marketplace,
        currency,
    )

    validated_original_url, _ = validate_amazon_url(
        url=original_url,
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        associate_tag=normalized_tag,
        field_name="original_url",
        require_tag_for_direct_url=False,
    )

    (
        validated_affiliate_url,
        is_short_affiliate_url,
    ) = validate_amazon_url(
        url=affiliate_url,
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        associate_tag=normalized_tag,
        field_name="affiliate_url",
        require_tag_for_direct_url=True,
    )

    return ValidatedAmazonLinks(
        marketplace=normalized_marketplace,
        asin=normalized_asin,
        original_url=validated_original_url,
        affiliate_url=validated_affiliate_url,
        associate_tag=normalized_tag,
        currency=normalized_currency,
        is_short_affiliate_url=is_short_affiliate_url,
    )