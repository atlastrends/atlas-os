"""affiliate content deduplication

Revision ID: a7d19c4e2f60
Revises: f4c2a1d9e7b0
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a7d19c4e2f60"
down_revision: Union[str, None] = "f4c2a1d9e7b0"

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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT content_fingerprint
                FROM affiliate_contents
                WHERE content_fingerprint IS NOT NULL
                GROUP BY content_fingerprint
                HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Existem fingerprints duplicados.';
            END IF;
        END
        $$;
        """
    )

    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_contents_content_fingerprint",
        table_name="affiliate_contents",
    )

    op.create_index(
        "ix_affiliate_contents_content_fingerprint",
        "affiliate_contents",
        ["content_fingerprint"],
        unique=False,
    )
