"""remove unused equipment table and exercises.equipment_id

Revision ID: a75da770acd0
Revises: b66619b190b4
Create Date: 2026-07-24 18:15:00.616483

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a75da770acd0'
down_revision: Union[str, Sequence[str], None] = 'b66619b190b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Hand-ordered: the FK on exercises.equipment_id must be dropped before the
    equipment table it points at (autogenerate's order violates this).
    """
    op.drop_index(op.f('ix_exercises_equipment_id'), table_name='exercises')
    op.drop_constraint(op.f('exercises_equipment_id_fkey'), 'exercises', type_='foreignkey')
    op.drop_column('exercises', 'equipment_id')

    op.drop_index(op.f('ix_equipment_name'), table_name='equipment')
    op.drop_table('equipment')


def downgrade() -> None:
    """Downgrade schema — reverse of upgrade: recreate equipment before the FK
    on exercises that points at it."""
    op.create_table('equipment',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('equipment_pkey'))
    )
    op.create_index(op.f('ix_equipment_name'), 'equipment', ['name'], unique=True)

    op.add_column('exercises', sa.Column('equipment_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('exercises_equipment_id_fkey'), 'exercises', 'equipment', ['equipment_id'], ['id'])
    op.create_index(op.f('ix_exercises_equipment_id'), 'exercises', ['equipment_id'], unique=False)
