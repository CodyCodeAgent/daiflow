"""merge sub_path and dev_server branches

Revision ID: b1f29da015be
Revises: 1832bfac2bd1, f00cf03a47c7
Create Date: 2026-03-24 11:06:57.444471

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1f29da015be'
down_revision: Union[str, Sequence[str], None] = ('1832bfac2bd1', 'f00cf03a47c7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
