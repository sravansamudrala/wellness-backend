"""add token_version to users

Revision ID: 34d5beab8d2f
Revises: d77e181f7484
Create Date: 2026-07-28 18:16:32.593616

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '34d5beab8d2f'
down_revision: Union[str, Sequence[str], None] = 'd77e181f7484'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('token_version', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'token_version')
