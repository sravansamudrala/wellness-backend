"""add electricity tracker and feature flags tables

Revision ID: 57d5680c4a0a
Revises: f7fc8dd18ad0
Create Date: 2026-08-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '57d5680c4a0a'
down_revision: Union[str, Sequence[str], None] = 'f7fc8dd18ad0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'feature_flags',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('feature_key', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'feature_key', name='uq_feature_flags_user_key'),
    )
    op.create_index(op.f('ix_feature_flags_user_id'), 'feature_flags', ['user_id'], unique=False)
    op.create_index(op.f('ix_feature_flags_feature_key'), 'feature_flags', ['feature_key'], unique=False)

    # meters first, without last_billed_reading_id — that FK points at
    # meter_readings, which doesn't exist yet. Added back below.
    op.create_table(
        'meters',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('meter_number', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meters_user_id'), 'meters', ['user_id'], unique=False)

    op.create_table(
        'meter_readings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('meter_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reading_value', sa.Numeric(), nullable=False),
        sa.Column('reading_date', sa.Date(), nullable=False),
        sa.Column('units_consumed', sa.Numeric(), nullable=True),
        sa.Column('entry_method', sa.String(), nullable=False),
        sa.Column('is_billed_reading', sa.Boolean(), nullable=False),
        sa.Column('photo_url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['meter_id'], ['meters.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meter_readings_meter_id'), 'meter_readings', ['meter_id'], unique=False)

    # Now that meter_readings exists, add the anchor-reading column + FK.
    op.add_column('meters', sa.Column('last_billed_reading_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_meters_last_billed_reading_id_meter_readings',
        'meters', 'meter_readings',
        ['last_billed_reading_id'], ['id'],
    )

    op.create_table(
        'meter_switch_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('outgoing_meter_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('incoming_meter_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('outgoing_reading_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('incoming_reading_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reading_date', sa.Date(), nullable=False),
        sa.Column('switched_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['outgoing_meter_id'], ['meters.id']),
        sa.ForeignKeyConstraint(['incoming_meter_id'], ['meters.id']),
        sa.ForeignKeyConstraint(['outgoing_reading_id'], ['meter_readings.id']),
        sa.ForeignKeyConstraint(['incoming_reading_id'], ['meter_readings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meter_switch_events_user_id'), 'meter_switch_events', ['user_id'], unique=False)

    op.create_table(
        'slab_thresholds',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('meter_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slab_min', sa.Numeric(), nullable=False),
        sa.Column('slab_max', sa.Numeric(), nullable=True),
        sa.ForeignKeyConstraint(['meter_id'], ['meters.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_slab_thresholds_meter_id'), 'slab_thresholds', ['meter_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_slab_thresholds_meter_id'), table_name='slab_thresholds')
    op.drop_table('slab_thresholds')

    op.drop_index(op.f('ix_meter_switch_events_user_id'), table_name='meter_switch_events')
    op.drop_table('meter_switch_events')

    op.drop_constraint('fk_meters_last_billed_reading_id_meter_readings', 'meters', type_='foreignkey')
    op.drop_column('meters', 'last_billed_reading_id')

    op.drop_index(op.f('ix_meter_readings_meter_id'), table_name='meter_readings')
    op.drop_table('meter_readings')

    op.drop_index(op.f('ix_meters_user_id'), table_name='meters')
    op.drop_table('meters')

    op.drop_index(op.f('ix_feature_flags_feature_key'), table_name='feature_flags')
    op.drop_index(op.f('ix_feature_flags_user_id'), table_name='feature_flags')
    op.drop_table('feature_flags')