from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from agent_quality_harness.adapters.base import AgentRunEvent, AgentRunResult, TokenUsage
from agent_quality_harness.evaluation import HarnessCase, InspectHarness


class EchoAdapter:
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=f"fake-{context['case_id']}",
            final_action="answer",
            output={"text": input_data["prompt"]},
            usage=TokenUsage(input_tokens=2, output_tokens=1),
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        if False:
            yield AgentRunEvent("unused")

    async def cancel(self, run_id: str) -> bool:
        return True


def test_inspect_runs_adapter_cases_without_external_model(tmp_path: Path) -> None:
    harness = InspectHarness(max_samples=2, log_dir=tmp_path / "logs")
    task = harness.build_task(
        [
            HarnessCase(id="case-1", input_data={"prompt": "alpha"}, expected={}),
            HarnessCase(id="case-2", input_data={"prompt": "beta"}, expected={}),
        ],
        EchoAdapter(),
        target_name="echo",
        target_version="v1",
    )

    logs = harness.run(task)

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert logs[0].results is not None
    assert logs[0].results.total_samples == 2
