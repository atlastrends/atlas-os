"""security foundation

Revision ID: b91f3d7a5c20
Revises: a7d19c4e2f60
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b91f3d7a5c20"
down_revision: Union[str, None] = "a7d19c4e2f60"

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
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="creator",
        ),
    )

    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('admin', 'reviewer', 'creator')",
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "submitted_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "reviewed_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.add_column(
        "affiliate_contents",
        sa.Column(
            "approved_by_user_id",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_affiliate_contents_submitted_by_user",
        "affiliate_contents",
        "users",
        ["submitted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_affiliate_contents_reviewed_by_user",
        "affiliate_contents",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_foreign_key(
        "fk_affiliate_contents_approved_by_user",
        "affiliate_contents",
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_affiliate_contents_submitted_by_user_id",
        "affiliate_contents",
        ["submitted_by_user_id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_reviewed_by_user_id",
        "affiliate_contents",
        ["reviewed_by_user_id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_contents_approved_by_user_id",
        "affiliate_contents",
        ["approved_by_user_id"],
        unique=False,
    )

    op.create_table(
        "affiliate_content_audit_logs",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "from_status",
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(
                astext_type=sa.Text()
            ),
            nullable=False,
            server_default=sa.text(
                "'{}'::jsonb"
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["content_id"],
            ["affiliate_contents.id"],
            name=(
                "fk_affiliate_content_audit_content"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=(
                "fk_affiliate_content_audit_actor"
            ),
            ondelete="SET NULL",
        ),
    )

    op.create_index(
        "ix_affiliate_content_audit_logs_id",
        "affiliate_content_audit_logs",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_content_audit_content_created",
        "affiliate_content_audit_logs",
        ["content_id", "created_at"],
        unique=False,
    )

    op.create_index(
        "ix_affiliate_content_audit_actor_created",
        "affiliate_content_audit_logs",
        ["actor_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_content_audit_actor_created",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_index(
        "ix_affiliate_content_audit_content_created",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_index(
        "ix_affiliate_content_audit_logs_id",
        table_name="affiliate_content_audit_logs",
    )

    op.drop_table(
        "affiliate_content_audit_logs"
    )

    op.drop_index(
        "ix_affiliate_contents_approved_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_reviewed_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_index(
        "ix_affiliate_contents_submitted_by_user_id",
        table_name="affiliate_contents",
    )

    op.drop_constraint(
        "fk_affiliate_contents_approved_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_affiliate_contents_reviewed_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_affiliate_contents_submitted_by_user",
        "affiliate_contents",
        type_="foreignkey",
    )

    op.drop_column(
        "affiliate_contents",
        "approved_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "reviewed_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "submitted_by_user_id",
    )

    op.drop_column(
        "affiliate_contents",
        "submitted_at",
    )

    op.drop_constraint(
        "ck_users_role",
        "users",
        type_="check",
    )

    op.drop_column(
        "users",
        "role",
    )
