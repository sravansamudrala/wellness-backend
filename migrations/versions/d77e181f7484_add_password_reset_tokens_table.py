"""add password_reset_tokens table

Revision ID: d77e181f7484
Revises: e8013c377d46
Create Date: 2026-07-27 17:46:00.872439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd77e181f7484'
down_revision: Union[str, Sequence[str], None] = 'e8013c377d46'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `password_reset_tokens` may already exist because a running `--reload`
    # server's startup create_all() can create new tables ahead of the
    # migration (see CLAUDE.md's create_all gotcha) — guard for idempotency,
    # same pattern as 2cae70d68811's `users` table creation.
    bind = op.get_bind()
    if "password_reset_tokens" not in sa.inspect(bind).get_table_names():
        op.create_table(
            'password_reset_tokens',
            sa.Column('id', sa.UUID(), nullable=False),
            sa.Column('user_id', sa.UUID(), nullable=False),
            sa.Column('token_hash', sa.String(), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            op.f('ix_password_reset_tokens_user_id'),
            'password_reset_tokens', ['user_id'], unique=False,
        )
        op.create_index(
            op.f('ix_password_reset_tokens_token_hash'),
            'password_reset_tokens', ['token_hash'], unique=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_password_reset_tokens_token_hash'), table_name='password_reset_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
