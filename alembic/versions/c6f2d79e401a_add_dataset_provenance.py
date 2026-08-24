"""add dataset provenance

Revision ID: c6f2d79e401a
Revises: b51a1e5e9a78
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c6f2d79e401a"
down_revision: str | None = "b51a1e5e9a78"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_datasets",
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("eval_datasets", "provenance", server_default=None)


def downgrade() -> None:
    op.drop_column("eval_datasets", "provenance")
