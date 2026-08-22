from datetime import UTC, datetime

import pytest

from agent_quality_harness.domain.models import EvalCase, EvalDataset
from agent_quality_harness.services import _sha256, verify_dataset_integrity


def test_dataset_integrity_detects_case_drift() -> None:
    canonical = {
        "id": "case-1",
        "input": {"prompt": "original"},
        "expected": {},
        "tags": [],
    }
    case_hash = _sha256(canonical)
    dataset = EvalDataset(
        name="frozen",
        version="v1",
        split="test",
        frozen_at=datetime.now(UTC),
        sha256=_sha256(
            {
                "name": "frozen",
                "version": "v1",
                "split": "test",
                "case_hashes": [case_hash],
            }
        ),
    )
    case = EvalCase(
        external_id="case-1",
        ordinal=0,
        input_data={"prompt": "tampered"},
        expected={},
        tags=[],
        sha256=case_hash,
    )

    with pytest.raises(ValueError, match="case case-1"):
        verify_dataset_integrity(dataset, [case])
