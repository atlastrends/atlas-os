import hashlib
import json
import re
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    ContentStatusEnum,
    MarketplaceEnum,
)


DISCLOSURE_BR = (
    "Publicidade. Como associado da Amazon, "
    "eu ganho com compras qualificadas."
)

DISCLOSURE_US = (
    "Ad. As an Amazon Associate I earn "
    "from qualifying purchases."
)


def normalize_platform(
    value: Optional[str],
) -> str:
    normalized = str(
        value or "tiktok"
    ).strip().lower()

    aliases = {
        "tik": "tiktok",
        "tik tok": "tiktok",
        "tik-tok": "tiktok",
        "tt": "tiktok",
        "insta": "instagram",
        "ig": "instagram",
        "instagram reels": "instagram",
        "reels": "instagram",
        "yt": "youtube",
        "youtube shorts": "youtube",
        "shorts": "youtube",
        "fb": "facebook",
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    allowed = {
        "tiktok",
        "instagram",
        "youtube",
        "facebook",
    }

    if normalized not in allowed:
        raise ValueError(
            "Plataforma invalida. Use tiktok, "
            "instagram, youtube ou facebook."
        )

    return normalized


def marketplace_value(
    product: AffiliateProduct,
) -> str:
    marketplace = product.marketplace

    raw_value = getattr(
        marketplace,
        "value",
        marketplace,
    )

    return str(
        raw_value or ""
    ).strip().lower()


def governance_for_product(
    product: AffiliateProduct,
) -> Tuple[str, str]:
    marketplace = marketplace_value(product)

    if marketplace == MarketplaceEnum.AMAZON_US.value:
        return "en-US", DISCLOSURE_US

    return "pt-BR", DISCLOSURE_BR


def clean_text(
    value: Any,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )


def optional_text(
    value: Any,
) -> Optional[str]:
    cleaned = clean_text(value)
    return cleaned or None


def add_disclosure(
    value: Any,
    disclosure: str,
) -> str:
    text = clean_text(value)
    disclosure_clean = clean_text(disclosure)

    if not text:
        return disclosure_clean

    if disclosure_clean.lower() in text.lower():
        return text

    return (
        disclosure_clean
        + "\n\n"
        + text
    )


def content_fingerprint(
    product_id: int,
    platform: str,
    data: Dict[str, Any],
) -> str:
    canonical = {
        "product_id": int(product_id),
        "platform": clean_text(platform).lower(),
        "hook_1": clean_text(
            data.get("hook_1")
        ).lower(),
        "hook_2": clean_text(
            data.get("hook_2")
        ).lower(),
        "script": clean_text(
            data.get("script")
        ).lower(),
        "caption": clean_text(
            data.get("caption")
        ).lower(),
        "trigger_keyword": clean_text(
            data.get("trigger_keyword")
        ).upper(),
        "seo_tags": clean_text(
            data.get("seo_tags")
        ).lower(),
        "language": clean_text(
            data.get("language")
        ).lower(),
        "disclosure": clean_text(
            data.get("disclosure")
        ).lower(),
    }

    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


def prepare_content_data(
    product: AffiliateProduct,
    platform: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    language, disclosure = governance_for_product(
        product
    )

    normalized_platform = normalize_platform(
        platform
    )

    script = add_disclosure(
        data.get("script"),
        disclosure,
    )

    caption = add_disclosure(
        data.get("caption"),
        disclosure,
    )

    if not clean_text(script):
        raise ValueError(
            "O roteiro nao pode ser vazio."
        )

    prepared = {
        "platform": normalized_platform,
        "hook_1": optional_text(
            data.get("hook_1")
        ),
        "hook_2": optional_text(
            data.get("hook_2")
        ),
        "script": script,
        "caption": caption,
        "trigger_keyword": optional_text(
            data.get("trigger_keyword")
        ),
        "seo_tags": optional_text(
            data.get("seo_tags")
        ),
        "language": language,
        "disclosure": disclosure,
    }

    prepared["content_fingerprint"] = (
        content_fingerprint(
            product_id=product.id,
            platform=normalized_platform,
            data=prepared,
        )
    )

    return prepared


def find_by_fingerprint(
    db: Session,
    fingerprint: str,
) -> Optional[AffiliateContent]:
    return (
        db.query(AffiliateContent)
        .filter(
            AffiliateContent.content_fingerprint
            == fingerprint
        )
        .first()
    )


def create_governed_content(
    db: Session,
    product: AffiliateProduct,
    platform: str,
    data: Dict[str, Any],
    generation_type: str,
) -> Tuple[AffiliateContent, bool]:
    prepared = prepare_content_data(
        product=product,
        platform=platform,
        data=data,
    )

    fingerprint = prepared[
        "content_fingerprint"
    ]

    existing = find_by_fingerprint(
        db=db,
        fingerprint=fingerprint,
    )

    if existing is not None:
        print(
            "[AFFILIATE GOVERNANCE] "
            f"Conteudo duplicado reutilizado: "
            f"{existing.id}",
            flush=True,
        )

        return existing, True

    normalized_generation_type = clean_text(
        generation_type
    )[:30] or "unknown"

    content = AffiliateContent(
        product_id=product.id,
        platform=prepared["platform"],
        hook_1=prepared["hook_1"],
        hook_2=prepared["hook_2"],
        script=prepared["script"],
        caption=prepared["caption"],
        trigger_keyword=(
            prepared["trigger_keyword"]
        ),
        seo_tags=prepared["seo_tags"],
        language=prepared["language"],
        disclosure=prepared["disclosure"],
        content_fingerprint=fingerprint,
        generation_type=(
            normalized_generation_type
        ),
        status=ContentStatusEnum.DRAFT,
    )

    db.add(content)

    try:
        db.commit()
        db.refresh(content)

        print(
            "[AFFILIATE GOVERNANCE] "
            f"Conteudo criado: {content.id}",
            flush=True,
        )

        return content, False

    except IntegrityError:
        db.rollback()

        existing = find_by_fingerprint(
            db=db,
            fingerprint=fingerprint,
        )

        if existing is not None:
            print(
                "[AFFILIATE GOVERNANCE] "
                "Concorrencia de deduplicacao "
                f"resolvida com conteudo {existing.id}.",
                flush=True,
            )

            return existing, True

        raise

    except Exception:
        db.rollback()
        raise
