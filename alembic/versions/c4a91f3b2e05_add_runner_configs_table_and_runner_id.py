"""add runner_configs table and runner_id columns

Revision ID: c4a91f3b2e05
Revises: 0fde09830f02
Create Date: 2026-03-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a91f3b2e05'
down_revision: Union[str, Sequence[str], None] = '70995646c278'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'runner_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('runner_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_projects_runner_id',
            'runner_configs',
            ['runner_id'], ['id'],
            ondelete='SET NULL',
        )

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('runner_id', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_tasks_runner_id',
            'runner_configs',
            ['runner_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_tasks_runner_id', type_='foreignkey')
        batch_op.drop_column('runner_id')

    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projects_runner_id', type_='foreignkey')
        batch_op.drop_column('runner_id')

    op.drop_table('runner_configs')
