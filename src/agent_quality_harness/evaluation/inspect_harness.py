import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from inspect_ai import Task
from inspect_ai import eval as inspect_eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ModelOutput
from inspect_ai.scorer import Score, Scorer, Target, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver

from agent_quality_harness.adapters.base import (
    TargetAdapter,
    TargetRunResult,
    ToolTargetAdapter,
)
from agent_quality_harness.core.telemetry import (
    add_usage_attributes,
    agent_span_attributes,
    current_trace_id,
    get_tracer,
    tool_span_attributes,
)
from agent_quality_harness.evaluation.scoring import ScoreReport, score_agent_result


@dataclass(frozen=True, slots=True)
class HarnessCase:
    id: str
    input_data: Mapping[str, Any]
    expected: Mapping[str, Any]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HarnessResult:
    case_id: str
    result: TargetRunResult
    trace_id: str | None
    latency_ms: int
    scores: ScoreReport


class InspectHarness:
    def __init__(self, *, max_samples: int = 8, log_dir: Path | str = ".tmp/inspect-logs"):
        self.max_samples = max_samples
        self.log_dir = Path(log_dir)

    def build_task(
        self,
        cases: Sequence[HarnessCase],
        adapter: TargetAdapter,
        *,
        target_name: str,
        target_version: str,
        target_id: int = 0,
        version_id: int = 0,
        protocol: str = "unknown",
        bound_skills: Sequence[Mapping[str, Any]] = (),
        capture: list[HarnessResult] | None = None,
    ) -> Task:
        samples = [
            Sample(
                id=case.id,
                input=json.dumps(case.input_data, ensure_ascii=False, sort_keys=True),
                target=json.dumps(case.expected, ensure_ascii=False, sort_keys=True),
                metadata={
                    "input_data": dict(case.input_data),
                    "expected": dict(case.expected),
                    "tags": list(case.tags),
                },
            )
            for case in cases
        ]
        return Task(
            dataset=MemoryDataset(samples, name=f"{target_name}-{target_version}"),
            solver=_adapter_solver(
                adapter,
                target_name,
                target_version,
                target_id,
                version_id,
                protocol,
                bound_skills,
                capture,
            ),
            scorer=_deterministic_scorer(),
            name="agent_target_eval",
            version=target_version,
            metadata={"target_name": target_name, "target_version": target_version},
        )

    def run(self, task: Task) -> list[EvalLog]:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        return inspect_eval(
            task,
            model="mockllm/model",
            display="none",
            log_dir=str(self.log_dir),
            max_samples=self.max_samples,
            fail_on_error=False,
            ctl_server=False,
        )

    async def run_async(self, task: Task) -> list[EvalLog]:
        return await asyncio.to_thread(self.run, task)


@solver
def _adapter_solver(
    adapter: TargetAdapter,
    target_name: str,
    target_version: str,
    target_id: int,
    version_id: int,
    protocol: str,
    bound_skills: Sequence[Mapping[str, Any]],
    capture: list[HarnessResult] | None,
) -> Solver:
    async def solve(state: TaskState, _: Generate) -> TaskState:
        tracer = get_tracer()
        case_id = str(state.sample_id)
        with tracer.start_as_current_span("eval.case", attributes={"aqh.case.id": case_id}):
            is_tool = isinstance(adapter, ToolTargetAdapter)
            attributes = (
                tool_span_attributes(
                    target_id=target_id,
                    version_id=version_id,
                    protocol=protocol,
                )
                if is_tool
                else agent_span_attributes(
                    target_id=target_id,
                    version_id=version_id,
                    protocol=protocol,
                    model=None,
                )
            )
            attributes["aqh.target.name"] = target_name
            if not is_tool:
                attributes["gen_ai.agent.name"] = target_name
            attributes["aqh.target.version"] = target_version
            started = perf_counter()
            span_name = "tool.execute" if is_tool else "agent.invoke"
            with tracer.start_as_current_span(span_name, attributes=attributes) as span:
                target_context = {
                    "case_id": case_id,
                    "target_name": target_name,
                    "target_version": target_version,
                }
                result = (
                    await adapter.execute(state.metadata["input_data"], target_context)
                    if is_tool
                    else await adapter.invoke(state.metadata["input_data"], target_context)
                )
                latency_ms = round((perf_counter() - started) * 1000)
                trace_id = current_trace_id()
                usage = asdict(result.usage)
                scores = score_agent_result(
                    state.metadata["expected"], result, bound_skills=bound_skills
                )
                add_usage_attributes(span, usage)
                state.metadata["aqh_result"] = {
                    "run_id": result.run_id,
                    "final_action": result.final_action,
                    "output": dict(result.output),
                    "usage": usage,
                    "measurement_status": result.usage.status.value,
                    "model_cost": _decimal_string(result.model_cost),
                    "external_tool_cost": _decimal_string(result.external_tool_cost),
                    "trace_id": trace_id,
                    "latency_ms": latency_ms,
                }
                state.metadata["aqh_scores"] = scores.as_dict()
                if capture is not None:
                    capture.append(
                        HarnessResult(
                            case_id=case_id,
                            result=result,
                            trace_id=trace_id,
                            latency_ms=latency_ms,
                            scores=scores,
                        )
                    )
                state.output = ModelOutput(
                    model=f"agent-target/{target_name}",
                    completion=json.dumps(result.output, ensure_ascii=False, sort_keys=True),
                    metadata={"final_action": result.final_action},
                )
                state.completed = True
        return state

    return solve


@scorer(metrics=[])
def _deterministic_scorer() -> Scorer:
    async def score(state: TaskState, _: Target) -> Score:
        report = state.metadata["aqh_scores"]
        return Score(
            value=float(report["score"]),
            explanation=None if report["passed"] else "deterministic assertions failed",
            metadata=report,
        )

    return score


def _decimal_string(value: Any) -> str | None:
    return None if value is None else str(value)
