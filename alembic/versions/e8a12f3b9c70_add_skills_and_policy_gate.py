"""add skills and policy gate

Revision ID: e8a12f3b9c70
Revises: c6f2d79e401a
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e8a12f3b9c70"
down_revision: str | None = "c6f2d79e401a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_skill_packages_org_name"),
    )
    op.create_index("ix_skill_packages_organization_id", "skill_packages", ["organization_id"])
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("package_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=True),
        sa.Column("manifest", jsonb, nullable=False),
        sa.Column("files", jsonb, nullable=False),
        sa.Column(
            "frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["package_id"], ["skill_packages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("package_id", "sha256", name="uq_skill_versions_package_sha256"),
        sa.UniqueConstraint("package_id", "version", name="uq_skill_versions_package_version"),
    )
    op.create_index("ix_skill_versions_package_id", "skill_versions", ["package_id"])
    op.create_table(
        "agent_version_skills",
        sa.Column("agent_version_id", sa.BigInteger(), nullable=False),
        sa.Column("skill_version_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "attached_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("agent_version_id", "skill_version_id"),
    )
    op.create_table(
        "skill_scans",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("skill_version_id", sa.BigInteger(), nullable=False),
        sa.Column("scanner_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("findings", jsonb, nullable=False),
        sa.Column("summary", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('pass', 'warn', 'block')", name="ck_skill_scans_status"),
        sa.ForeignKeyConstraint(["skill_version_id"], ["skill_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_scans_version_created", "skill_scans", ["skill_version_id", "created_at"]
    )
    op.create_table(
        "policy_bundles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("package_path", sa.String(length=300), nullable=False),
        sa.Column("entrypoint", sa.String(length=100), nullable=False),
        sa.Column("rego", sa.Text(), nullable=False),
        sa.Column("data", jsonb, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("validation_errors", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('validated', 'invalid')", name="ck_policy_bundles_status"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "name", "version", name="uq_policy_bundles_org_name_version"
        ),
        sa.UniqueConstraint("organization_id", "sha256", name="uq_policy_bundles_org_sha256"),
    )
    op.create_index("ix_policy_bundles_organization_id", "policy_bundles", ["organization_id"])
    op.add_column("gate_policies", sa.Column("policy_bundle_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gate_policies_policy_bundle_id",
        "gate_policies",
        "policy_bundles",
        ["policy_bundle_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_gate_policies_policy_bundle_id", "gate_policies", ["policy_bundle_id"])
    op.create_table(
        "policy_evaluations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("policy_bundle_id", sa.BigInteger(), nullable=False),
        sa.Column("decision_id", sa.String(length=100), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reasons", jsonb, nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('ship', 'warn', 'block')", name="ck_policy_evaluations_decision"
        ),
        sa.ForeignKeyConstraint(["policy_bundle_id"], ["policy_bundles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        "ix_policy_evaluations_policy_bundle_id",
        "policy_evaluations",
        ["policy_bundle_id"],
    )
    op.create_index("ix_policy_evaluations_decision_id", "policy_evaluations", ["decision_id"])
    op.add_column("gate_results", sa.Column("policy_evaluation_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_gate_results_policy_evaluation_id",
        "gate_results",
        "policy_evaluations",
        ["policy_evaluation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_gate_results_policy_evaluation_id", "gate_results", ["policy_evaluation_id"]
    )

    connection = op.get_bind()
    permission_rows = [
        ("skill:read", "Read Agent Skills and scans"),
        ("skill:scan", "Execute Agent Skill security scans"),
        ("skill:manage", "Manage Agent Skill versions and attachments"),
        ("policy:read", "Read Policy-as-Code bundles and evaluations"),
        ("policy:manage", "Manage Policy-as-Code bundles"),
    ]
    for code, name in permission_rows:
        connection.execute(
            sa.text(
                "INSERT INTO permissions (code, name, description) VALUES (:code, :name, '') "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "name": name},
        )
    role_codes = {
        "Administrator": [code for code, _ in permission_rows],
        "Evaluator": ["skill:read", "skill:scan", "policy:read"],
        "Viewer": ["skill:read", "policy:read"],
    }
    for role_name, codes in role_codes.items():
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                "WHERE r.name = :role_name AND p.code = ANY(:codes) "
                "ON CONFLICT DO NOTHING"
            ),
            {"role_name": role_name, "codes": codes},
        )


def downgrade() -> None:
    connection = op.get_bind()
    codes = ["skill:read", "skill:scan", "skill:manage", "policy:read", "policy:manage"]
    connection.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    connection.execute(
        sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes}
    )
    op.drop_constraint("uq_gate_results_policy_evaluation_id", "gate_results", type_="unique")
    op.drop_constraint("fk_gate_results_policy_evaluation_id", "gate_results", type_="foreignkey")
    op.drop_column("gate_results", "policy_evaluation_id")
    op.drop_index("ix_policy_evaluations_decision_id", table_name="policy_evaluations")
    op.drop_index("ix_policy_evaluations_policy_bundle_id", table_name="policy_evaluations")
    op.drop_table("policy_evaluations")
    op.drop_index("ix_gate_policies_policy_bundle_id", table_name="gate_policies")
    op.drop_constraint("fk_gate_policies_policy_bundle_id", "gate_policies", type_="foreignkey")
    op.drop_column("gate_policies", "policy_bundle_id")
    op.drop_index("ix_policy_bundles_organization_id", table_name="policy_bundles")
    op.drop_table("policy_bundles")
    op.drop_index("ix_skill_scans_version_created", table_name="skill_scans")
    op.drop_table("skill_scans")
    op.drop_table("agent_version_skills")
    op.drop_index("ix_skill_versions_package_id", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_index("ix_skill_packages_organization_id", table_name="skill_packages")
    op.drop_table("skill_packages")
