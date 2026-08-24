"""freeze security artifacts

Revision ID: f19c3a72d4e1
Revises: e8a12f3b9c70
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f19c3a72d4e1"
down_revision: str | None = "e8a12f3b9c70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION aqh_reject_frozen_security_artifact_change()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("skill_versions", "policy_bundles"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION aqh_reject_frozen_security_artifact_change()
            """
        )


def downgrade() -> None:
    for table in ("policy_bundles", "skill_versions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS aqh_reject_frozen_security_artifact_change()")
