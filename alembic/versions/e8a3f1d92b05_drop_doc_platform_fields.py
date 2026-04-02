"""drop prd_doc_platform and tech_doc_platform from tasks

Revision ID: e8a3f1d92b05
Revises: 70995646c278
Create Date: 2026-04-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8a3f1d92b05'
down_revision: Union[str, Sequence[str], None] = '4a9e1f2b8c3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop platform columns that are no longer used."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('prd_doc_platform')
        batch_op.drop_column('tech_doc_platform')


def downgrade() -> None:
    """Re-add platform columns."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tech_doc_platform', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('prd_doc_platform', sa.String(), nullable=True))
