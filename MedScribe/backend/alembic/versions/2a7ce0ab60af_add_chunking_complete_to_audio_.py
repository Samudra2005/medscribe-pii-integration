"""add chunking_complete to audio_processing_status

Revision ID: 2a7ce0ab60af
Revises: 6d2d12eba731
Create Date: 2026-08-27 10:49:55.670105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a7ce0ab60af'
down_revision: Union[str, Sequence[str], None] = '6d2d12eba731'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE audio_processing_status "
        "ADD VALUE IF NOT EXISTS 'chunking_complete'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
