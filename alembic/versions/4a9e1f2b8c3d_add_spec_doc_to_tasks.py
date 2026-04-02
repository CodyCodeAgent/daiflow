"""add spec_doc to tasks

Revision ID: 4a9e1f2b8c3d
Revises: b1f29da015be
Create Date: 2026-03-24 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4a9e1f2b8c3d"
down_revision: Union[str, Sequence[str], None] = "b1f29da015be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column("spec_doc", sa.Text(), nullable=True, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("spec_doc")
