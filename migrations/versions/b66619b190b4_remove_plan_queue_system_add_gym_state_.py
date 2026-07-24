"""remove plan queue system, add gym_state rotation_order

Revision ID: b66619b190b4
Revises: 70168206a7fa
Create Date: 2026-07-24 18:03:38.373776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b66619b190b4'
down_revision: Union[str, Sequence[str], None] = '70168206a7fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Hand-ordered (autogenerate's order violates FK dependencies): plan_exercises
    has no dependents so it drops first; gym_state/workout_sessions FK
    constraints into plan_days/workout_plans must be dropped before those
    tables can be dropped; only then can the now-orphaned FK columns go.
    """
    # 1) Leaf table — nothing references plan_exercises.
    op.drop_index(op.f('ix_plan_exercises_exercise_id'), table_name='plan_exercises')
    op.drop_index(op.f('ix_plan_exercises_plan_day_id'), table_name='plan_exercises')
    op.drop_table('plan_exercises')

    # 2) Drop FKs pointing at plan_days, then plan_days itself.
    op.drop_constraint(op.f('gym_state_last_completed_day_id_fkey'), 'gym_state', type_='foreignkey')
    op.drop_constraint(op.f('workout_sessions_plan_day_id_fkey'), 'workout_sessions', type_='foreignkey')
    op.drop_index(op.f('ix_workout_sessions_plan_day_id'), table_name='workout_sessions')
    op.drop_index(op.f('ix_plan_days_plan_id'), table_name='plan_days')
    op.drop_table('plan_days')

    # 3) Drop FKs pointing at workout_plans, then workout_plans itself.
    op.drop_constraint(op.f('gym_state_active_plan_id_fkey'), 'gym_state', type_='foreignkey')
    op.drop_constraint(op.f('workout_sessions_plan_id_fkey'), 'workout_sessions', type_='foreignkey')
    op.drop_index(op.f('ix_workout_plans_user_id'), table_name='workout_plans')
    op.drop_table('workout_plans')

    # 4) Now safe to drop the orphaned columns (constraints already gone).
    op.drop_column('gym_state', 'active_plan_id')
    op.drop_column('gym_state', 'last_completed_day_id')
    op.drop_column('workout_sessions', 'plan_id')
    op.drop_column('workout_sessions', 'plan_day_id')

    # 5) New rotation-order setting.
    op.add_column('gym_state', sa.Column('rotation_order', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema — reverse of upgrade, recreating tables before the FKs
    that point at them."""
    op.drop_column('gym_state', 'rotation_order')

    op.create_table('workout_plans',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('user_id', sa.UUID(), autoincrement=False, nullable=True),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('goal', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('is_custom', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.Column('updated_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('workout_plans_user_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('workout_plans_pkey'))
    )
    op.create_index(op.f('ix_workout_plans_user_id'), 'workout_plans', ['user_id'], unique=False)

    op.create_table('plan_days',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('plan_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('order_index', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['workout_plans.id'], name=op.f('plan_days_plan_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('plan_days_pkey'))
    )
    op.create_index(op.f('ix_plan_days_plan_id'), 'plan_days', ['plan_id'], unique=False)

    op.add_column('workout_sessions', sa.Column('plan_day_id', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('workout_sessions', sa.Column('plan_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('workout_sessions_plan_id_fkey'), 'workout_sessions', 'workout_plans', ['plan_id'], ['id'])
    op.create_foreign_key(op.f('workout_sessions_plan_day_id_fkey'), 'workout_sessions', 'plan_days', ['plan_day_id'], ['id'])
    op.create_index(op.f('ix_workout_sessions_plan_day_id'), 'workout_sessions', ['plan_day_id'], unique=False)

    op.add_column('gym_state', sa.Column('active_plan_id', sa.UUID(), autoincrement=False, nullable=True))
    op.add_column('gym_state', sa.Column('last_completed_day_id', sa.UUID(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('gym_state_active_plan_id_fkey'), 'gym_state', 'workout_plans', ['active_plan_id'], ['id'])
    op.create_foreign_key(op.f('gym_state_last_completed_day_id_fkey'), 'gym_state', 'plan_days', ['last_completed_day_id'], ['id'])

    op.create_table('plan_exercises',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('plan_day_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('exercise_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('order_index', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('target_sets', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('target_reps', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('target_rest_seconds', sa.INTEGER(), autoincrement=False, nullable=True),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id'], name=op.f('plan_exercises_exercise_id_fkey')),
    sa.ForeignKeyConstraint(['plan_day_id'], ['plan_days.id'], name=op.f('plan_exercises_plan_day_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('plan_exercises_pkey'))
    )
    op.create_index(op.f('ix_plan_exercises_plan_day_id'), 'plan_exercises', ['plan_day_id'], unique=False)
    op.create_index(op.f('ix_plan_exercises_exercise_id'), 'plan_exercises', ['exercise_id'], unique=False)
