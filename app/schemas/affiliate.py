from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketplaceEnum(str, Enum):
    AMAZON_US = "amazon_us"
    AMAZON_BR = "amazon_br"


class ContentStatusEnum(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class ProductCreate(BaseModel):
    marketplace: MarketplaceEnum
    asin: str
    title: str
    original_url: str
    category: Optional[str] = None
    price_text: Optional[str] = None
    currency: Optional[str] = None
    affiliate_url: str
    associate_tag: str

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: str) -> str:
        normalized = str(value or "").strip().upper()

        if not normalized:
            raise ValueError("asin é obrigatório.")

        if any(character.isspace() for character in normalized):
            raise ValueError("asin não pode conter espaços.")

        return normalized

    @field_validator(
        "title",
        "original_url",
        "affiliate_url",
        "associate_tag",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()

        if not normalized:
            raise ValueError("O campo não pode ser vazio.")

        return normalized

    @field_validator("category", "price_text", "currency")
    @classmethod
    def normalize_optional_text(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None

        normalized = str(value).strip()
        return normalized or None

    @field_validator("currency")
    @classmethod
    def normalize_currency(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        return value.upper() if value else None


class ProductResponse(ProductCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class ProductUpsertResponse(BaseModel):
    action: str
    product: ProductResponse


class ContentGenerateRequest(BaseModel):
    product_id: int
    platform: str = Field(
        ...,
        description="Ex.: instagram, tiktok, youtube ou shorts",
    )

    @field_validator("platform")
    @classmethod
    def normalize_platform(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()

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

        normalized = aliases.get(normalized, normalized)

        allowed = {
            "tiktok",
            "instagram",
            "youtube",
            "facebook",
        }

        if normalized not in allowed:
            raise ValueError(
                "Plataforma inválida. Use tiktok, instagram, "
                "youtube ou facebook."
            )

        return normalized


class ContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    platform: str
    hook_1: Optional[str] = None
    hook_2: Optional[str] = None
    script: str
    caption: Optional[str] = None
    trigger_keyword: Optional[str] = None
    seo_tags: Optional[str] = None
    language: Optional[str] = None
    disclosure: Optional[str] = None
    content_fingerprint: Optional[str] = None
    generation_type: Optional[str] = None
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    status: ContentStatusEnum
    created_at: datetime
    updated_at: Optional[datetime] = None
