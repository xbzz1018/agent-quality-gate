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
    }

    assert set(Base.metadata.tables) == expected
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
