from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from agent_quality_harness.domain.models import Base


def test_postgresql_schema_compiles_with_expected_tables() -> None:
    expected = {
        "evaluation_targets",
        "agent_versions",
        "eval_datasets",
        "eval_cases",
        "eval_runs",
        "case_results",
        "gate_policies",
        "gate_results",
        "pricing_snapshots",
        "usage_measurements",
        "run_events",
        "organizations",
        "users",
        "memberships",
        "roles",
        "permissions",
        "role_permissions",
        "membership_roles",
        "auth_sessions",
        "service_accounts",
        "api_keys",
        "audit_logs",
        "system_settings",
        "skill_packages",
        "skill_versions",
        "agent_version_skills",
        "skill_scans",
        "policy_bundles",
        "policy_evaluations",
    }

    assert set(Base.metadata.tables) == expected
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
