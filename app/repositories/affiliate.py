from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.affiliate import (
    AffiliateContent,
    AffiliateProduct,
    ContentStatusEnum,
    MarketplaceEnum as DatabaseMarketplaceEnum,
)
from app.schemas.affiliate import ProductCreate
from app.services.amazon_link_validation import (
    validate_amazon_product_links,
)
from app.services.affiliate_content_governance import (
    create_governed_content,
)


class AffiliateRepository:
    @staticmethod
    def normalize_asin(asin: str) -> str:
        normalized = str(asin or "").strip().upper()

        if not normalized:
            raise ValueError("asin é obrigatório.")

        if any(character.isspace() for character in normalized):
            raise ValueError("asin não pode conter espaços.")

        return normalized

    @staticmethod
    def normalize_marketplace(marketplace) -> DatabaseMarketplaceEnum:
        raw_value = getattr(marketplace, "value", marketplace)
        normalized = str(raw_value or "").strip().lower()

        try:
            return DatabaseMarketplaceEnum(normalized)
        except ValueError as error:
            raise ValueError(
                "Marketplace inválido. Use amazon_br ou amazon_us."
            ) from error

    @staticmethod
    def normalize_currency(
        marketplace: DatabaseMarketplaceEnum,
        currency: str | None,
    ) -> str:
        expected_by_marketplace = {
            DatabaseMarketplaceEnum.AMAZON_BR: "BRL",
            DatabaseMarketplaceEnum.AMAZON_US: "USD",
        }

        expected_currency = expected_by_marketplace[marketplace]
        normalized_currency = str(currency or "").strip().upper()

        if not normalized_currency:
            return expected_currency

        if normalized_currency != expected_currency:
            raise ValueError(
                f"Moeda inválida para {marketplace.value}. "
                f"Use {expected_currency}."
            )

        return normalized_currency

    def get_product(
        self,
        db: Session,
        product_id: int,
    ) -> AffiliateProduct | None:
        return (
            db.query(AffiliateProduct)
            .filter(AffiliateProduct.id == product_id)
            .first()
        )

    def get_product_by_identity(
        self,
        db: Session,
        marketplace,
        asin: str,
    ) -> AffiliateProduct | None:
        normalized_asin = self.normalize_asin(asin)
        normalized_marketplace = self.normalize_marketplace(marketplace)

        return (
            db.query(AffiliateProduct)
            .filter(
                AffiliateProduct.marketplace == normalized_marketplace,
                AffiliateProduct.asin == normalized_asin,
            )
            .first()
        )

    @staticmethod
    def _apply_product_data(
        product: AffiliateProduct,
        product_in: ProductCreate,
        normalized_asin: str,
    ) -> None:
        normalized_marketplace = (
            AffiliateRepository.normalize_marketplace(
                product_in.marketplace
            )
        )

        normalized_currency = AffiliateRepository.normalize_currency(
            marketplace=normalized_marketplace,
            currency=product_in.currency,
        )

        validated_links = validate_amazon_product_links(
            marketplace=normalized_marketplace,
            asin=normalized_asin,
            original_url=product_in.original_url,
            affiliate_url=product_in.affiliate_url,
            associate_tag=product_in.associate_tag,
            currency=normalized_currency,
        )

        product.marketplace = normalized_marketplace
        product.asin = validated_links.asin
        product.title = product_in.title
        product.category = product_in.category
        product.original_url = validated_links.original_url
        product.affiliate_url = validated_links.affiliate_url
        product.associate_tag = validated_links.associate_tag
        product.price_text = product_in.price_text
        product.currency = validated_links.currency

        if hasattr(product, "product_url"):
            product.product_url = validated_links.original_url

        if hasattr(product, "is_short_affiliate_url"):
            product.is_short_affiliate_url = (
                validated_links.is_short_affiliate_url
            )

    def upsert_product(
        self,
        db: Session,
        product_in: ProductCreate,
    ) -> tuple[AffiliateProduct, Literal["created", "updated"]]:
        normalized_asin = self.normalize_asin(product_in.asin)

        existing = self.get_product_by_identity(
            db=db,
            marketplace=product_in.marketplace,
            asin=normalized_asin,
        )

        if existing:
            self._apply_product_data(
                product=existing,
                product_in=product_in,
                normalized_asin=normalized_asin,
            )

            try:
                db.commit()
                db.refresh(existing)
                return existing, "updated"
            except Exception:
                db.rollback()
                raise

        product = AffiliateProduct()

        self._apply_product_data(
            product=product,
            product_in=product_in,
            normalized_asin=normalized_asin,
        )

        db.add(product)

        try:
            db.commit()
            db.refresh(product)
            return product, "created"

        except IntegrityError:
            db.rollback()

            existing = self.get_product_by_identity(
                db=db,
                marketplace=product_in.marketplace,
                asin=normalized_asin,
            )

            if not existing:
                raise

            self._apply_product_data(
                product=existing,
                product_in=product_in,
                normalized_asin=normalized_asin,
            )

            try:
                db.commit()
                db.refresh(existing)
                return existing, "updated"
            except Exception:
                db.rollback()
                raise

        except Exception:
            db.rollback()
            raise

    def create_product(
        self,
        db: Session,
        product_in: ProductCreate,
    ) -> AffiliateProduct:
        product, _ = self.upsert_product(db, product_in)
        return product

    def list_products(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ):
        return (
            db.query(AffiliateProduct)
            .order_by(AffiliateProduct.id.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def save_content(
        self,
        db: Session,
        product_id: int,
        platform: str,
        ai_data: dict,
    ) -> AffiliateContent:
        product = self.get_product(
            db=db,
            product_id=product_id,
        )

        if not product:
            raise ValueError(
                f"Produto ID {product_id} nao encontrado."
            )

        content, _ = create_governed_content(
            db=db,
            product=product,
            platform=platform,
            data=ai_data,
            generation_type="repository",
        )

        return content


affiliate_repo = AffiliateRepository()


