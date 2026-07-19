"""affiliate product identity guard

Revision ID: 7c91e4d8a2f0
Revises: c6534927a384
"""

from typing import Sequence, Union

from alembic import op


revision: str = "7c91e4d8a2f0"
down_revision: Union[str, None] = "c6534927a384"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Normaliza todos os ASINs existentes.
    op.execute(
        """
        UPDATE affiliate_products
        SET asin = UPPER(BTRIM(asin))
        """
    )

    # Transfere eventuais referências dos duplicados para o registro
    # canônico, definido como o produto de menor ID.
    op.execute(
        """
        WITH product_identity AS (
            SELECT
                id AS source_id,
                MIN(id) OVER (
                    PARTITION BY marketplace, UPPER(BTRIM(asin))
                ) AS canonical_id
            FROM affiliate_products
        )
        UPDATE affiliate_contents AS content
        SET product_id = identity.canonical_id
        FROM product_identity AS identity
        WHERE content.product_id = identity.source_id
          AND identity.source_id <> identity.canonical_id
        """
    )

    # Remove registros duplicados depois de consolidar suas referências.
    op.execute(
        """
        WITH ranked_products AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY marketplace, UPPER(BTRIM(asin))
                    ORDER BY id
                ) AS duplicate_position
            FROM affiliate_products
        )
        DELETE FROM affiliate_products AS product
        USING ranked_products AS ranked
        WHERE product.id = ranked.id
          AND ranked.duplicate_position > 1
        """
    )

    # Impede ASIN vazio, com espaços externos ou em letras minúsculas.
    op.create_check_constraint(
        "ck_affiliate_products_asin_normalized",
        "affiliate_products",
        "asin <> '' AND asin = UPPER(BTRIM(asin))",
    )

    # Impede definitivamente o mesmo ASIN no mesmo marketplace.
    op.create_unique_constraint(
        "uq_affiliate_products_marketplace_asin",
        "affiliate_products",
        ["marketplace", "asin"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_affiliate_products_marketplace_asin",
        "affiliate_products",
        type_="unique",
    )

    op.drop_constraint(
        "ck_affiliate_products_asin_normalized",
        "affiliate_products",
        type_="check",
    )
