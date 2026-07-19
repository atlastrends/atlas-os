"""amazon catalog workaround

Revision ID: e4b82d7c91aa
Revises: 7c91e4d8a2f0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e4b82d7c91aa"
down_revision: Union[str, None] = "7c91e4d8a2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # LEGACY_SAFE_NO_NARROW_ASIN
    # Coluna legada preservada sem reducao de tamanho.
    # Novos valores continuam validados pela aplicacao.


    # LEGACY_SAFE_NO_NARROW_TITLE
    # Coluna legada preservada sem reducao de tamanho.
    # Novos valores continuam validados pela aplicacao.


    # LEGACY_SAFE_NO_NARROW_CATEGORY
    # Coluna legada preservada sem reducao de tamanho.
    # Novos valores continuam validados pela aplicacao.


    op.add_column(
        "affiliate_products",
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "product_url",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "image_url",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "price_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "affiliate_url_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "last_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "data_source",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "catalog_status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "click_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "affiliate_products",
        sa.Column(
            "is_short_affiliate_url",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.execute(
        """
        UPDATE affiliate_products
        SET product_url = CASE
            WHEN marketplace::text = 'AMAZON_BR'
                THEN 'https://www.amazon.com.br/dp/' || asin
            ELSE 'https://www.amazon.com/dp/' || asin
        END
        WHERE product_url IS NULL
        """
    )

    op.create_check_constraint(
        "ck_affiliate_products_catalog_status",
        "affiliate_products",
        "catalog_status IN ('active', 'inactive', 'archived')",
    )

    op.create_check_constraint(
        "ck_affiliate_products_data_source",
        "affiliate_products",
        "data_source IN ('manual', 'csv', 'creators_api')",
    )

    op.create_index(
        "ix_affiliate_products_catalog_marketplace_status",
        "affiliate_products",
        ["marketplace", "catalog_status"],
        unique=False,
    )

    op.create_table(
        "affiliate_clicks",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "platform",
            sa.String(length=50),
            nullable=True,
        ),
        sa.Column(
            "campaign",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "referrer",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "user_agent",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "ip_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["affiliate_products.id"],
            ondelete="CASCADE",
        ),
    )

    op.create_index(
        "ix_affiliate_clicks_id",
        "affiliate_clicks",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_clicks_product_created",
        "affiliate_clicks",
        ["product_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_clicks_product_created",
        table_name="affiliate_clicks",
    )

    op.drop_index(
        "ix_affiliate_clicks_id",
        table_name="affiliate_clicks",
    )

    op.drop_table("affiliate_clicks")

    op.drop_index(
        "ix_affiliate_products_catalog_marketplace_status",
        table_name="affiliate_products",
    )

    op.drop_constraint(
        "ck_affiliate_products_data_source",
        "affiliate_products",
        type_="check",
    )

    op.drop_constraint(
        "ck_affiliate_products_catalog_status",
        "affiliate_products",
        type_="check",
    )

    op.drop_column(
        "affiliate_products",
        "is_short_affiliate_url",
    )

    op.drop_column(
        "affiliate_products",
        "click_count",
    )

    op.drop_column(
        "affiliate_products",
        "notes",
    )

    op.drop_column(
        "affiliate_products",
        "catalog_status",
    )

    op.drop_column(
        "affiliate_products",
        "data_source",
    )

    op.drop_column(
        "affiliate_products",
        "last_verified_at",
    )

    op.drop_column(
        "affiliate_products",
        "affiliate_url_verified_at",
    )

    op.drop_column(
        "affiliate_products",
        "price_observed_at",
    )

    op.drop_column(
        "affiliate_products",
        "image_url",
    )

    op.drop_column(
        "affiliate_products",
        "product_url",
    )

    op.drop_column(
        "affiliate_products",
        "features",
    )

    op.drop_column(
        "affiliate_products",
        "description",
    )