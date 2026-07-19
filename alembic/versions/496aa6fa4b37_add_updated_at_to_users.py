"""add updated_at to users

Revision ID: 496aa6fa4b37
Revises: 338520c92b44
Create Date: 2026-07-06 23:14:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '496aa6fa4b37'
down_revision: Union[str, None] = '338520c92b44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'updated_at')
