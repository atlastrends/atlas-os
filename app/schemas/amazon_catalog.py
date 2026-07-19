from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


class AmazonMarketplace(str, Enum):
    AMAZON_BR = "amazon_br"
    AMAZON_US = "amazon_us"


class AmazonDataSource(str, Enum):
    MANUAL = "manual"
    CSV = "csv"
    CREATORS_API = "creators_api"


class AmazonCatalogStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class AmazonProductInput(BaseModel):
    marketplace: AmazonMarketplace
    asin: str
    title: str

    category: Optional[str] = None
    description: Optional[str] = None
    features: list[str] = Field(default_factory=list)

    original_url: Optional[str] = None
    affiliate_url: str
    associate_tag: Optional[str] = None
    image_url: Optional[str] = None

    price_text: Optional[str] = None
    currency: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("asin")
    @classmethod
    def normalize_asin(cls, value: str) -> str:
        normalized = str(value or "").strip().upper()

        if not normalized:
            raise ValueError("asin e obrigatorio.")

        if len(normalized) != 10:
            raise ValueError(
                "asin deve possuir exatamente 10 caracteres."
            )

        if not normalized.isalnum():
            raise ValueError(
                "asin deve conter somente letras e numeros."
            )

        return normalized

    @field_validator("title", "affiliate_url")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()

        if not normalized:
            raise ValueError("O campo nao pode ser vazio.")

        return normalized

    @field_validator(
        "category",
        "description",
        "original_url",
        "associate_tag",
        "image_url",
        "price_text",
        "currency",
        "notes",
    )
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

    @field_validator("features")
    @classmethod
    def normalize_features(
        cls,
        values: list[str],
    ) -> list[str]:
        result = []
        seen = set()

        for value in values or []:
            normalized = str(value or "").strip()

            if not normalized:
                continue

            key = normalized.lower()

            if key in seen:
                continue

            seen.add(key)
            result.append(normalized)

        return result[:20]


class AmazonProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    marketplace: AmazonMarketplace
    asin: str
    title: str
    category: Optional[str] = None
    description: Optional[str] = None
    features: list[str] = Field(default_factory=list)

    original_url: str
    product_url: Optional[str] = None
    affiliate_url: str
    associate_tag: str
    image_url: Optional[str] = None

    price_text: Optional[str] = None
    currency: Optional[str] = None
    price_observed_at: Optional[datetime] = None
    affiliate_url_verified_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None

    data_source: AmazonDataSource
    catalog_status: AmazonCatalogStatus
    notes: Optional[str] = None

    click_count: int
    is_short_affiliate_url: bool

    created_at: datetime
    updated_at: Optional[datetime] = None

    atlas_link: Optional[str] = None


class AmazonProductUpsertResponse(BaseModel):
    ok: bool = True
    action: str
    warnings: list[str] = Field(default_factory=list)
    product: AmazonProductResponse


class AmazonCatalogListResponse(BaseModel):
    ok: bool = True
    total: int
    limit: int
    offset: int
    products: list[AmazonProductResponse]


class AmazonCsvRowResult(BaseModel):
    row: int
    action: Optional[str] = None
    marketplace: Optional[str] = None
    asin: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class AmazonCsvImportResponse(BaseModel):
    ok: bool
    dry_run: bool
    processed: int
    created: int
    updated: int
    failed: int
    results: list[AmazonCsvRowResult]


class AmazonStatusUpdate(BaseModel):
    status: AmazonCatalogStatus


class AmazonConfigResponse(BaseModel):
    public_base_url: str
    amazon_br_configured: bool
    amazon_us_configured: bool
    csv_max_rows: int
    supported_marketplaces: list[str]
    accepted_sources: list[str]