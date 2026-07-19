from datetime import datetime
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.affiliate import (
    AffiliateClick,
    AffiliateProduct,
    MarketplaceEnum,
)
from app.services.amazon_catalog_service import (
    ValidatedAmazonProduct,
)


class AmazonCatalogRepository:
    def get(
        self,
        db: Session,
        product_id: int,
    ) -> Optional[AffiliateProduct]:
        return (
            db.query(AffiliateProduct)
            .filter(AffiliateProduct.id == product_id)
            .first()
        )

    def get_by_identity(
        self,
        db: Session,
        marketplace: MarketplaceEnum,
        asin: str,
    ) -> Optional[AffiliateProduct]:
        return (
            db.query(AffiliateProduct)
            .filter(
                AffiliateProduct.marketplace == marketplace,
                AffiliateProduct.asin == asin,
            )
            .first()
        )

    @staticmethod
    def apply_data(
        product: AffiliateProduct,
        data: ValidatedAmazonProduct,
        source: str,
        now: datetime,
    ) -> None:
        product.marketplace = data.marketplace
        product.asin = data.asin
        product.title = data.title
        product.category = data.category
        product.description = data.description
        product.features = data.features

        product.original_url = data.original_url
        product.product_url = data.product_url
        product.affiliate_url = data.affiliate_url
        product.associate_tag = data.associate_tag
        product.image_url = data.image_url

        product.price_text = data.price_text
        product.currency = data.currency
        product.notes = data.notes

        product.data_source = source
        product.catalog_status = "active"
        product.is_short_affiliate_url = (
            data.is_short_affiliate_url
        )

        product.last_verified_at = now
        product.affiliate_url_verified_at = now

        if data.price_text:
            product.price_observed_at = now
        else:
            product.price_observed_at = None

    def upsert(
        self,
        db: Session,
        data: ValidatedAmazonProduct,
        source: str,
        now: datetime,
    ) -> tuple[AffiliateProduct, str]:
        product = self.get_by_identity(
            db=db,
            marketplace=data.marketplace,
            asin=data.asin,
        )

        action = "updated"

        if product is None:
            product = AffiliateProduct()
            db.add(product)
            action = "created"

        self.apply_data(
            product=product,
            data=data,
            source=source,
            now=now,
        )

        db.flush()
        return product, action

    def list(
        self,
        db: Session,
        marketplace: Optional[MarketplaceEnum],
        catalog_status: Optional[str],
        query_text: Optional[str],
        limit: int,
        offset: int,
    ) -> tuple[int, list[AffiliateProduct]]:
        query = db.query(AffiliateProduct)

        if marketplace is not None:
            query = query.filter(
                AffiliateProduct.marketplace == marketplace
            )

        if catalog_status:
            query = query.filter(
                AffiliateProduct.catalog_status
                == catalog_status
            )

        if query_text:
            pattern = f"%{query_text.strip()}%"

            query = query.filter(
                or_(
                    AffiliateProduct.asin.ilike(pattern),
                    AffiliateProduct.title.ilike(pattern),
                    AffiliateProduct.category.ilike(pattern),
                )
            )

        total = query.count()

        products = (
            query
            .order_by(AffiliateProduct.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return total, products

    def update_status(
        self,
        db: Session,
        product: AffiliateProduct,
        status: str,
    ) -> AffiliateProduct:
        product.catalog_status = status
        db.flush()
        return product

    def register_click(
        self,
        db: Session,
        product: AffiliateProduct,
        platform: Optional[str],
        campaign: Optional[str],
        referrer: Optional[str],
        user_agent: Optional[str],
        ip_hash: Optional[str],
    ) -> AffiliateClick:
        click = AffiliateClick(
            product_id=product.id,
            platform=platform,
            campaign=campaign,
            referrer=referrer,
            user_agent=user_agent,
            ip_hash=ip_hash,
        )

        product.click_count = int(
            product.click_count or 0
        ) + 1

        db.add(click)
        db.flush()

        return click


amazon_catalog_repository = AmazonCatalogRepository()