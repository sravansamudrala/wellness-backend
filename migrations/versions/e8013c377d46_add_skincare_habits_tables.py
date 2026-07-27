"""add skincare habits tables

Revision ID: e8013c377d46
Revises: a75da770acd0
Create Date: 2026-07-27 13:33:32.176867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8013c377d46'
down_revision: Union[str, Sequence[str], None] = 'a75da770acd0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'skincare_habits',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_skincare_habits_user_name'),
    )
    op.create_index(op.f('ix_skincare_habits_user_id'), 'skincare_habits', ['user_id'], unique=False)

    op.create_table(
        'skincare_entry_habits',
        sa.Column('entry_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('habit_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['entry_id'], ['skincare_entries.id']),
        sa.ForeignKeyConstraint(['habit_id'], ['skincare_habits.id']),
        sa.PrimaryKeyConstraint('entry_id', 'habit_id'),
    )
    # NOTE: this migration intentionally does NOT touch the `equipment` table.
    # Autogenerate also detected `equipment` as a stale table to drop — that's
    # a pre-existing drift unrelated to this change (an earlier migration
    # apparently never ran its DROP TABLE against this DB) and is left alone
    # here; see the note left for the user rather than silently including it.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('skincare_entry_habits')
    op.drop_index(op.f('ix_skincare_habits_user_id'), table_name='skincare_habits')
    op.drop_table('skincare_habits')
