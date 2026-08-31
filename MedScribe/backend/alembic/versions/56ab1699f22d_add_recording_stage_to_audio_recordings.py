"""add recording_stage to audio_recordings

Revision ID: 56ab1699f22d
Revises: 2a7ce0ab60af
Create Date: 2026-08-30 07:05:29.969108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '56ab1699f22d'
down_revision: Union[str, Sequence[str], None] = '2a7ce0ab60af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    recording_stage_enum = postgresql.ENUM(
        "nurse_intake",
        "doctor_consultation",
        name="recording_stage",
    )
    recording_stage_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "audio_recordings",
        sa.Column(
            "recording_stage",
            recording_stage_enum,
            server_default="doctor_consultation",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("audio_recordings", "recording_stage")

    recording_stage_enum = postgresql.ENUM(
        "nurse_intake",
        "doctor_consultation",
        name="recording_stage",
    )
    recording_stage_enum.drop(op.get_bind(), checkfirst=True)
