import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_quality_harness.api.schemas import (
    DatasetImport,
    EvalRunCreate,
    TargetCreate,
    VersionCreate,
)
from agent_quality_harness.domain.enums import RunStatus
from agent_quality_harness.domain.models import (
    AgentVersion,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    PricingSnapshot,
)

RUNNABLE_PROTOCOLS = {"http", "sse"}


def create_target(session: Session, payload: TargetCreate) -> EvaluationTarget:
    target = EvaluationTarget(**payload.model_dump())
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def create_version(session: Session, target_id: int, payload: VersionCreate) -> AgentVersion:
    if session.get(EvaluationTarget, target_id) is None:
        raise LookupError("target not found")
    data = payload.model_dump()
    metadata = data.pop("metadata")
    version = AgentVersion(target_id=target_id, metadata_json=metadata, **data)
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def import_dataset(session: Session, payload: DatasetImport) -> tuple[EvalDataset, int]:
    case_rows: list[tuple[dict, str]] = []
    seen_ids: set[str] = set()
    for case in payload.cases:
        if case.id in seen_ids:
            raise ValueError(f"duplicate case id: {case.id}")
        seen_ids.add(case.id)
        canonical = case.model_dump(mode="json", by_alias=True, exclude_none=True)
        case_rows.append((canonical, _sha256(canonical)))
    dataset_document = {
        "name": payload.name,
        "version": payload.version,
        "split": payload.split,
        "case_hashes": [case_hash for _, case_hash in case_rows],
    }
    dataset = EvalDataset(
        name=payload.name,
        version=payload.version,
        split=payload.split,
        sha256=_sha256(dataset_document),
        frozen_at=datetime.now(UTC),
    )
    for ordinal, (case, case_hash) in enumerate(case_rows):
        dataset.cases.append(
            EvalCase(
                external_id=case["id"],
                ordinal=ordinal,
                input_data=case["input"],
                expected=case["expected"],
                tags=case["tags"],
                sha256=case_hash,
            )
        )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset, len(case_rows)


def create_eval_run(session: Session, payload: EvalRunCreate) -> EvalRun:
    dataset = session.get(EvalDataset, payload.dataset_id)
    if dataset is None:
        raise LookupError("dataset not found")
    candidate = session.get(AgentVersion, payload.candidate_version_id)
    if candidate is None:
        raise LookupError("candidate version not found")
    candidate_target = session.get(EvaluationTarget, candidate.target_id)
    if candidate_target is None:
        raise LookupError("candidate target not found")
    if candidate_target.protocol.value not in RUNNABLE_PROTOCOLS:
        raise ValueError(
            f"{candidate_target.protocol.value} Adapter pending; only HTTP/SSE can execute"
        )
    baseline: AgentVersion | None = None
    if payload.baseline_version_id is not None:
        baseline = session.get(AgentVersion, payload.baseline_version_id)
        if baseline is None:
            raise LookupError("baseline version not found")
        if payload.baseline_version_id == payload.candidate_version_id:
            raise ValueError("baseline and candidate must be different versions")
        baseline_target = session.get(EvaluationTarget, baseline.target_id)
        if baseline_target is None:
            raise LookupError("baseline target not found")
        if baseline_target.protocol.value not in RUNNABLE_PROTOCOLS:
            raise ValueError(
                f"{baseline_target.protocol.value} Adapter pending; only HTTP/SSE can execute"
            )
        if baseline.target_id != candidate.target_id and not payload.benchmark_mode:
            raise ValueError(
                "baseline and candidate must belong to the same target; "
                "set benchmark_mode=true for an explicit cross-target comparison"
            )
    case_count = session.scalar(
        select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset.id)
    )
    gate_policy = _resolve_policy(session, payload.gate_policy_id)
    pricing = _resolve_pricing(session, payload.pricing_snapshot_id)
    config = dict(payload.config)
    manifest = {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "version": dataset.version,
            "sha256": dataset.sha256,
        },
        "versions": {
            "baseline": _version_snapshot(baseline),
            "candidate": _version_snapshot(candidate),
        },
        "config_sha256": _sha256(config),
        "gate_policy": _policy_snapshot(gate_policy),
        "pricing_snapshot": _pricing_snapshot(pricing),
        "code_version": _code_version(),
    }
    run = EvalRun(
        dataset_id=dataset.id,
        baseline_version_id=payload.baseline_version_id,
        candidate_version_id=payload.candidate_version_id,
        status=RunStatus.QUEUED,
        gate_policy_id=None if gate_policy is None else gate_policy.id,
        pricing_snapshot_id=None if pricing is None else pricing.id,
        config=config,
        manifest=manifest,
        benchmark_mode=payload.benchmark_mode,
        expected_case_count=int(case_count or 0),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def verify_dataset_integrity(dataset: EvalDataset, cases: list[EvalCase]) -> None:
    case_hashes: list[str] = []
    for case in cases:
        canonical = {
            "id": case.external_id,
            "input": case.input_data,
            "expected": case.expected,
            "tags": case.tags,
        }
        actual = _sha256(canonical)
        if actual != case.sha256:
            raise ValueError(f"dataset integrity mismatch for case {case.external_id}")
        case_hashes.append(actual)
    document = {
        "name": dataset.name,
        "version": dataset.version,
        "split": dataset.split,
        "case_hashes": case_hashes,
    }
    if _sha256(document) != dataset.sha256:
        raise ValueError("dataset integrity mismatch")


def _resolve_policy(session: Session, policy_id: int | None) -> GatePolicy | None:
    if policy_id is not None:
        policy = session.get(GatePolicy, policy_id)
        if policy is None:
            raise LookupError("gate policy not found")
        return policy
    return session.scalar(
        select(GatePolicy).where(GatePolicy.active.is_(True)).order_by(GatePolicy.id.desc())
    )


def _resolve_pricing(session: Session, pricing_id: int | None) -> PricingSnapshot | None:
    if pricing_id is None:
        return None
    pricing = session.get(PricingSnapshot, pricing_id)
    if pricing is None:
        raise LookupError("pricing snapshot not found")
    return pricing


def _version_snapshot(version: AgentVersion | None) -> dict | None:
    if version is None:
        return None
    return {
        "id": version.id,
        "target_id": version.target_id,
        "version": version.version,
        "model": version.model,
        "prompt_version": version.prompt_version,
        "tool_schema_hash": version.tool_schema_hash,
        "metadata": version.metadata_json,
    }


def _policy_snapshot(policy: GatePolicy | None) -> dict | None:
    if policy is None:
        return None
    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "thresholds": policy.thresholds,
    }


def _pricing_snapshot(pricing: PricingSnapshot | None) -> dict | None:
    if pricing is None:
        return None
    return {
        "id": pricing.id,
        "provider": pricing.provider,
        "model": pricing.model,
        "version": pricing.version,
        "currency": pricing.currency,
        "effective_at": pricing.effective_at.isoformat(),
        "prices": pricing.prices,
        "source": pricing.source,
    }


def _sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _code_version() -> str:
    configured = os.getenv("AQH_CODE_VERSION")
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"
