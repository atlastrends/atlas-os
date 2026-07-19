import enum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class MarketplaceEnum(str, enum.Enum):
    AMAZON_US = "amazon_us"
    AMAZON_BR = "amazon_br"


class ContentStatusEnum(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"


class AffiliateProduct(Base):
    __tablename__ = "affiliate_products"

    __table_args__ = (
        UniqueConstraint(
            "marketplace",
            "asin",
            name="uq_affiliate_products_marketplace_asin",
        ),
        CheckConstraint(
            "asin <> '' AND asin = UPPER(BTRIM(asin))",
            name="ck_affiliate_products_asin_normalized",
        ),
        CheckConstraint(
            "catalog_status IN ('active', 'inactive', 'archived')",
            name="ck_affiliate_products_catalog_status",
        ),
        CheckConstraint(
            "data_source IN ('manual', 'csv', 'creators_api')",
            name="ck_affiliate_products_data_source",
        ),
        Index(
            "ix_affiliate_products_catalog_marketplace_status",
            "marketplace",
            "catalog_status",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    marketplace = Column(
        Enum(MarketplaceEnum),
        nullable=False,
    )

    asin = Column(
        String(10),
        nullable=False,
        index=True,
    )

    title = Column(
        String(500),
        nullable=False,
    )

    category = Column(
        String(255),
        nullable=True,
    )

    description = Column(
        Text,
        nullable=True,
    )

    features = Column(
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    original_url = Column(
        Text,
        nullable=False,
    )

    product_url = Column(
        Text,
        nullable=True,
    )

    affiliate_url = Column(
        Text,
        nullable=False,
    )

    associate_tag = Column(
        String(100),
        nullable=False,
    )

    image_url = Column(
        Text,
        nullable=True,
    )

    price_text = Column(
        String(100),
        nullable=True,
    )

    currency = Column(
        String(3),
        nullable=True,
    )

    price_observed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    affiliate_url_verified_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_verified_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    data_source = Column(
        String(30),
        nullable=False,
        default="manual",
        server_default="manual",
    )

    catalog_status = Column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
    )

    notes = Column(
        Text,
        nullable=True,
    )

    click_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    is_short_affiliate_url = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )

    contents = relationship(
        "AffiliateContent",
        back_populates="product",
        cascade="all, delete-orphan",
    )

    clicks = relationship(
        "AffiliateClick",
        back_populates="product",
        cascade="all, delete-orphan",
    )


class AffiliateContent(Base):
    __tablename__ = "affiliate_contents"

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey("affiliate_products.id"),
        nullable=False,
    )

    platform = Column(
        String,
        nullable=False,
    )

    hook_1 = Column(
        Text,
        nullable=True,
    )

    hook_2 = Column(
        Text,
        nullable=True,
    )

    script = Column(
        Text,
        nullable=False,
    )

    caption = Column(
        Text,
        nullable=True,
    )

    trigger_keyword = Column(
        String,
        nullable=True,
    )

    seo_tags = Column(
        String,
        nullable=True,
    )

    language = Column(
        String(10),
        nullable=True,
    )

    disclosure = Column(
        Text,
        nullable=True,
    )

    content_fingerprint = Column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )

    generation_type = Column(
        String(30),
        nullable=True,
    )

    review_notes = Column(
        Text,
        nullable=True,
    )

    reviewed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    approved_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    reviewed_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    approved_by_user_id = Column(
        Integer,
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    status = Column(
        Enum(ContentStatusEnum),
        default=ContentStatusEnum.DRAFT,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at = Column(
        DateTime(timezone=True),
        onupdate=func.now(),
    )

    product = relationship(
        "AffiliateProduct",
        back_populates="contents",
    )


class AffiliateClick(Base):
    __tablename__ = "affiliate_clicks"

    __table_args__ = (
        Index(
            "ix_affiliate_clicks_product_created",
            "product_id",
            "created_at",
        ),
    )

    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )

    product_id = Column(
        Integer,
        ForeignKey(
            "affiliate_products.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    platform = Column(
        String(50),
        nullable=True,
    )

    campaign = Column(
        String(100),
        nullable=True,
    )

    referrer = Column(
        Text,
        nullable=True,
    )

    user_agent = Column(
        Text,
        nullable=True,
    )

    ip_hash = Column(
        String(64),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    product = relationship(
        "AffiliateProduct",
        back_populates="clicks",
    )