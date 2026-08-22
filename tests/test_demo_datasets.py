import json
from pathlib import Path

from agent_quality_harness.api.schemas import DatasetImport


def test_demo_fixture_dataset_sizes_and_contracts() -> None:
    root = Path(__file__).parents[1] / "datasets"
    core = json.loads((root / "demo-fixture-core-v1.json").read_text(encoding="utf-8"))
    stability = json.loads(
        (root / "demo-fixture-stability-v1.json").read_text(encoding="utf-8")
    )

    assert core["demo_fixture"] is True
    assert stability["demo_fixture"] is True
    assert len(DatasetImport.model_validate(core).cases) == 80
    assert len(DatasetImport.model_validate(stability).cases) == 20
    assert stability["required_runs"] == 3
