"""add meter shares table

Revision ID: 17f0c5f350b6
Revises: 57d5680c4a0a
Create Date: 2026-08-03 17:55:50.456828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '17f0c5f350b6'
down_revision: Union[str, Sequence[str], None] = '57d5680c4a0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('meter_shares', sa.Column('shared_with_user_id', sa.UUID(), nullable=False))
    op.create_index(op.f('ix_meter_shares_shared_with_user_id'), 'meter_shares', ['shared_with_user_id'], unique=False)
    op.create_foreign_key(None, 'meter_shares', 'users', ['shared_with_user_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(None, 'meter_shares', type_='foreignkey')
    op.drop_index(op.f('ix_meter_shares_shared_with_user_id'), table_name='meter_shares')
    op.drop_column('meter_shares', 'shared_with_user_id')
