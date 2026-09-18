import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header

from agent_quality_harness.adapters import AgentRunResult
from agent_quality_harness.evaluation import HarnessCase, InspectHarness
from agent_quality_harness.judging import (
    JudgeObservation,
    OpenAICompatibleHallucinationJudge,
)


async def test_openai_compatible_judge_sends_only_bounded_claim_evidence() -> None:
    app = FastAPI()
    observed: dict[str, Any] = {}

    @app.post("/v1/chat/completions")
    async def complete(body: dict[str, Any], authorization: str = Header()) -> dict:
        assert authorization == "Bearer private-key"
        observed.update(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"verdict":"unsupported","confidence":0.91,'
                            '"unsupported_claim_ids":["claim-2"]}'
                        )
                    }
                }
            ],
            "usage": {"total_tokens": 37},
        }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://target") as client:
        judge = OpenAICompatibleHallucinationJudge(
            base_url="http://target/v1",
            model="judge-v1",
            api_key="private-key",
            client=client,
        )
        result = await judge.evaluate(
            case_id="case-1",
            specification={"required_claim_ids": ["claim-1", "claim-2"]},
            output={
                "claims": [{"id": "claim-1", "text": "supported"}],
                "evidence": [{"id": "ref-1", "text": "source"}],
                "private": "must-not-leave-platform",
            },
        )

    assert result.status == "known"
    assert result.verdict == "unsupported"
    assert result.judge_tokens == 37
    serialized = str(observed)
    assert "must-not-leave-platform" not in serialized
    assert "private-key" not in serialized


class JudgeAdapter:
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        del input_data, context
        return AgentRunResult(
            run_id="judge-case",
            final_action="answer",
            output={"claims": [{"id": "claim-1"}], "evidence": [{"id": "ref-1"}]},
        )

    async def cancel(self, run_id: str) -> bool:
        return True


class FixtureJudge:
    async def evaluate(
        self,
        *,
        case_id: str,
        specification: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> JudgeObservation:
        del case_id, specification, output
        return JudgeObservation(
            status="known",
            verdict="unsupported",
            confidence=0.9,
            unsupported_claim_ids=("claim-1",),
            model="fixture-judge",
            prompt_version="fixture-v1",
            response_sha256="a" * 64,
            judge_tokens=12,
        )


def test_inspect_records_non_blocking_judge_signal_and_usage(tmp_path: Path) -> None:
    captures = []
    harness = InspectHarness(
        max_samples=1,
        log_dir=tmp_path / "logs",
        judge=FixtureJudge(),
    )
    task = harness.build_task(
        [
            HarnessCase(
                id="judge-case",
                input_data={},
                expected={"judge": {"required": True, "minimum_confidence": 0.8}},
            )
        ],
        JudgeAdapter(),
        target_name="judge-target",
        target_version="v1",
        capture=captures,
    )

    logs = harness.run(task)

    assert logs[0].status == "success"
    assert captures[0].scores.passed is True
    judge_rule = captures[0].scores.rules[-1]
    assert judge_rule.category == "hallucination_judge"
    assert judge_rule.passed is False
    assert judge_rule.critical is False
    assert captures[0].result.usage.judge_tokens == 12
    assert captures[0].result.events[-1].event_type == "judge.completed"


def test_hallucination_calibration_fixture_is_versioned_and_balanced() -> None:
    path = Path(__file__).parents[1] / "datasets" / "hallucination-judge-calibration-v1.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["schema"] == "aqh.hallucination-calibration/v1"
    assert document["version"] == "v1"
    labels = [case["expected"] for case in document["cases"]]
    assert len(labels) == 8
    assert set(labels) == {"supported", "unsupported", "uncertain"}
