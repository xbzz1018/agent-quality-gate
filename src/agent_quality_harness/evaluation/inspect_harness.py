import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
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
    AgentRunEvent,
    AgentRunResult,
    TargetAdapter,
    TargetRunResult,
    TokenUsage,
    ToolRunResult,
    ToolTargetAdapter,
)
from agent_quality_harness.core.telemetry import (
    add_usage_attributes,
    agent_span_attributes,
    current_trace_id,
    get_tracer,
    tool_span_attributes,
)
from agent_quality_harness.evaluation.scoring import RuleScore, ScoreReport, score_agent_result
from agent_quality_harness.judging import DisabledHallucinationJudge, HallucinationJudge


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
    failure_type: str | None = None


class InspectHarness:
    def __init__(
        self,
        *,
        max_samples: int = 8,
        log_dir: Path | str = ".tmp/inspect-logs",
        judge: HallucinationJudge | None = None,
    ):
        self.max_samples = max_samples
        self.log_dir = Path(log_dir)
        self.judge = judge or DisabledHallucinationJudge()

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
        time_limit_seconds: int | None = None,
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
                self.judge,
            ),
            scorer=_deterministic_scorer(),
            name="agent_target_eval",
            version=target_version,
            metadata={"target_name": target_name, "target_version": target_version},
            time_limit=time_limit_seconds,
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
    judge: HallucinationJudge,
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
                failure_type = None
                try:
                    result = (
                        await adapter.execute(state.metadata["input_data"], target_context)
                        if is_tool
                        else await adapter.invoke(state.metadata["input_data"], target_context)
                    )
                except Exception as error:
                    failure_type = _target_failure_type(error)
                    result = _failure_result(is_tool=is_tool, failure_type=failure_type)
                latency_ms = round((perf_counter() - started) * 1000)
                trace_id = current_trace_id()
                usage = asdict(result.usage)
                scores = score_agent_result(
                    state.metadata["expected"], result, bound_skills=bound_skills
                )
                result, scores = await _apply_hallucination_judge(
                    case_id=case_id,
                    expected=state.metadata["expected"],
                    result=result,
                    scores=scores,
                    judge=judge,
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
                            failure_type=failure_type,
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


def _target_failure_type(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "target_timeout"
    return "target_error"


def _failure_result(*, is_tool: bool, failure_type: str) -> TargetRunResult:
    event = AgentRunEvent("target.failed", {"error_type": failure_type})
    if is_tool:
        return ToolRunResult(
            operation_id=None,
            final_action="error",
            output={"status": "failed", "error_type": failure_type},
            events=(event,),
            usage=TokenUsage(),
        )
    return AgentRunResult(
        run_id=None,
        final_action="error",
        output={"status": "failed", "error_type": failure_type},
        events=(event,),
        usage=TokenUsage(),
    )


async def _apply_hallucination_judge(
    *,
    case_id: str,
    expected: Mapping[str, Any],
    result: TargetRunResult,
    scores: ScoreReport,
    judge: HallucinationJudge,
) -> tuple[TargetRunResult, ScoreReport]:
    specification = expected.get("judge")
    if not isinstance(specification, Mapping):
        return result, scores
    observation = await judge.evaluate(
        case_id=case_id,
        specification=specification,
        output=result.output,
    )
    minimum_confidence = float(specification.get("minimum_confidence", 0.7))
    passed = (
        observation.status == "known"
        and observation.verdict == "supported"
        and observation.confidence is not None
        and observation.confidence >= minimum_confidence
    )
    observed = {
        "status": observation.status,
        "verdict": observation.verdict,
        "confidence": observation.confidence,
        "unsupported_claim_ids": list(observation.unsupported_claim_ids),
        "model": observation.model,
        "prompt_version": observation.prompt_version,
        "response_sha256": observation.response_sha256,
        "error_type": observation.error_type,
    }
    rule = RuleScore(
        rule_id="hallucination.judge",
        category="hallucination_judge",
        expected={"verdict": "supported", "minimum_confidence": minimum_confidence},
        observed=observed,
        score=1.0 if passed else 0.0,
        critical=False,
        failure_reason=None if passed else "bounded hallucination Judge did not confirm support",
    )
    rules = scores.rules + (rule,)
    combined = ScoreReport(
        passed=scores.passed,
        score=round(sum(item.score for item in rules) / len(rules), 6),
        rules=rules,
    )
    usage = replace(result.usage, judge_tokens=observation.judge_tokens)
    event = AgentRunEvent(
        "judge.completed",
        {
            "status": observation.status,
            "verdict": observation.verdict,
            "confidence": observation.confidence,
            "model": observation.model,
            "prompt_version": observation.prompt_version,
            "response_sha256": observation.response_sha256,
            "error_type": observation.error_type,
        },
    )
    return replace(result, usage=usage, events=result.events + (event,)), combined
