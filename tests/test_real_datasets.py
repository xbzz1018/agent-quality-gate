import json
from pathlib import Path

from agent_quality_harness.api.schemas import DatasetImport

DATASETS = Path(__file__).resolve().parents[1] / "datasets"


def test_agrigraph_real_dataset_is_frozen_from_exact_generation_selection() -> None:
    payload = json.loads(
        (DATASETS / "real-agrigraph-generation-test-v2.json").read_text(encoding="utf-8")
    )
    dataset = DatasetImport.model_validate(payload)

    assert len(dataset.cases) == 40
    assert dataset.split == "characterization"
    assert dataset.provenance["selection"] == {
        "expected_count": 40,
        "generationSelected": True,
    }
    assert dataset.provenance["source_dirty"] is True
    assert len(dataset.provenance["source_tree_sha256"]) == 64
    assert all("real-target" in case.tags for case in dataset.cases)


def test_document_real_dataset_contains_hash_assertions_not_raw_ground_truth() -> None:
    path = DATASETS / "real-document-autoflow-dev-v2.1.json"
    raw = path.read_text(encoding="utf-8")
    dataset = DatasetImport.model_validate_json(raw)

    assert len(dataset.cases) == 24
    assert dataset.provenance["selection"]["model"] == "deepseek-v4-flash"
    assert len(dataset.provenance["quality_report_sha256"]) == 64
    assert "ground_truth" not in raw
    assert "normalized_value" not in raw
    assert all(
        case.input.keys() == {"source_file_sha256", "source_sample_id"} for case in dataset.cases
    )
    assert all(
        any(
            rule.id and rule.id.startswith("field.") and len(str(rule.value)) == 64
            for rule in case.expected.output.assertions
        )
        for case in dataset.cases
    )
