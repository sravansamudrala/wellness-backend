"""add billed amount to meter readings

Revision ID: f740bbf6f245
Revises: 17f0c5f350b6
Create Date: 2026-08-27 18:04:06.828578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f740bbf6f245'
down_revision: Union[str, Sequence[str], None] = '17f0c5f350b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('meter_readings', sa.Column('billed_amount', sa.Numeric(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('meter_readings', 'billed_amount')
