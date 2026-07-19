"""affiliate content governance

Revision ID: f4c2a1d9e7b0
Revises: e4b82d7c91aa
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2a1d9e7b0"
down_revision: Union[str, None] = "e4b82d7c91aa"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.add_column(
        "affiliate_contents",
        sa.Column(
            "language",
            sa.String(length=10),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "disclosure",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "content_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "generation_type",
            sa.String(length=30),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "review_notes",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.execute(
        """
        UPDATE affiliate_contents AS content
        SET
            language = CASE
                WHEN product.marketplace::text
                    IN ('AMAZON_US', 'amazon_us')
                    THEN 'en-US'
                ELSE 'pt-BR'
            END,
            disclosure = CASE
                WHEN product.marketplace::text
                    IN ('AMAZON_US', 'amazon_us')
                    THEN
                        'Ad. As an Amazon Associate I earn '
                        'from qualifying purchases.'
                ELSE
                    'Publicidade. Como Associado da Amazon, '
                    'recebo por compras qualificadas.'
            END,
            generation_type = 'legacy'
        FROM affiliate_products AS product
        WHERE product.id = content.product_id
        """
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_product_platform_status",
        "affiliate_contents",
        [
            "product_id",
            "platform",
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_contents_product_platform_status",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.drop_column(
        "affiliate_contents",
        "approved_at",
    )

    op.drop_column(
        "affiliate_contents",
        "reviewed_at",
    )

    op.drop_column(
        "affiliate_contents",
        "review_notes",
    )

    op.drop_column(
        "affiliate_contents",
        "generation_type",
    )

    op.drop_column(
        "affiliate_contents",
        "content_fingerprint",
    )

    op.drop_column(
        "affiliate_contents",
        "disclosure",
    )

    op.drop_column(
        "affiliate_contents",
        "language",
    )
