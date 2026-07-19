"""add_hashed_password

Revision ID: a88355ba762e
Revises: 496aa6fa4b37
Create Date: 2026-07-06 23:14:10.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a88355ba762e'
down_revision: Union[str, None] = '496aa6fa4b37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('users', 'hashed_password')
