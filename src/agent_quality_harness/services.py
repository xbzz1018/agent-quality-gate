import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_quality_harness.adapter_factory import validate_contract_profile
from agent_quality_harness.api.schemas import (
    DatasetImport,
    DemoBootstrapRead,
    EvalRunCreate,
    TargetCreate,
    VersionCreate,
)
from agent_quality_harness.domain.enums import RunStatus, TargetKind, TargetProtocol
from agent_quality_harness.domain.models import (
    AgentVersion,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    PolicyBundle,
    PricingSnapshot,
)
from agent_quality_harness.skills import version_skill_snapshot

RUNNABLE_PROTOCOLS = {"http", "sse", "ag_ui", "a2a", "mcp"}

DEMO_TARGET_NAME = "Demo Fixture Agent"
DEMO_DATASET_NAME = "agent-quality-harness-demo-core"
DEMO_POLICY_NAME = "Demo Fixture Release Gate"
DEMO_PRICING_PROVIDER = "demo-fixture"
DEMO_PRICING_MODEL = "deterministic-fake-agent"


def create_target(
    session: Session, payload: TargetCreate, organization_id: int
) -> EvaluationTarget:
    target = EvaluationTarget(organization_id=organization_id, **payload.model_dump())
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def create_version(
    session: Session,
    target_id: int,
    payload: VersionCreate,
    organization_id: int,
) -> AgentVersion:
    target = session.scalar(
        select(EvaluationTarget).where(
            EvaluationTarget.id == target_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if target is None:
        raise LookupError("target not found")
    data = payload.model_dump()
    metadata = data.pop("metadata")
    version = AgentVersion(target_id=target_id, metadata_json=metadata, **data)
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def bootstrap_demo(
    session: Session, *, organization_id: int, dataset_path: Path, agent_endpoint: str
) -> DemoBootstrapRead:
    created: list[str] = []
    target = session.scalar(
        select(EvaluationTarget).where(
            EvaluationTarget.organization_id == organization_id,
            EvaluationTarget.name == DEMO_TARGET_NAME,
        )
    )
    if target is None:
        target = create_target(
            session,
            TargetCreate(
                name=DEMO_TARGET_NAME,
                target_kind=TargetKind.AGENT,
                protocol=TargetProtocol.HTTP,
                endpoint=agent_endpoint,
                capabilities={"demo_fixture": True},
            ),
            organization_id,
        )
        created.append("target")
    elif target.endpoint != agent_endpoint:
        target.endpoint = agent_endpoint
        session.commit()
        session.refresh(target)
        created.append("target_endpoint")

    versions: dict[str, AgentVersion] = {}
    for role in ("baseline", "candidate"):
        version = session.scalar(
            select(AgentVersion).where(
                AgentVersion.target_id == target.id,
                AgentVersion.version == role,
            )
        )
        if version is None:
            version = create_version(
                session,
                target.id,
                VersionCreate(
                    version=role,
                    model=DEMO_PRICING_MODEL,
                    metadata={"demo_fixture": True, "role": role},
                ),
                organization_id,
            )
            created.append(f"version:{role}")
        versions[role] = version

    dataset = session.scalar(
        select(EvalDataset).where(
            EvalDataset.organization_id == organization_id,
            EvalDataset.name == DEMO_DATASET_NAME,
            EvalDataset.version == "v1",
        )
    )
    if dataset is None:
        document = json.loads(dataset_path.read_text(encoding="utf-8"))
        dataset, _ = import_dataset(
            session, DatasetImport.model_validate(document), organization_id
        )
        created.append("dataset")

    policy = session.scalar(
        select(GatePolicy).where(
            GatePolicy.organization_id == organization_id,
            GatePolicy.name == DEMO_POLICY_NAME,
            GatePolicy.version == "v1",
        )
    )
    if policy is None:
        from agent_quality_harness.gates import DEFAULT_THRESHOLDS

        policy = GatePolicy(
            organization_id=organization_id,
            name=DEMO_POLICY_NAME,
            version="v1",
            thresholds=DEFAULT_THRESHOLDS,
            active=True,
        )
        session.add(policy)
        session.commit()
        session.refresh(policy)
        created.append("gate_policy")

    pricing = session.scalar(
        select(PricingSnapshot).where(
            PricingSnapshot.organization_id == organization_id,
            PricingSnapshot.provider == DEMO_PRICING_PROVIDER,
            PricingSnapshot.model == DEMO_PRICING_MODEL,
            PricingSnapshot.version == "v1",
        )
    )
    if pricing is None:
        pricing = PricingSnapshot(
            organization_id=organization_id,
            provider=DEMO_PRICING_PROVIDER,
            model=DEMO_PRICING_MODEL,
            version="v1",
            currency="USD",
            effective_at=datetime(2026, 1, 1, tzinfo=UTC),
            prices={
                "input_tokens": "0.000001",
                "output_tokens": "0.000002",
            },
            source="Demo Fixture synthetic pricing",
        )
        session.add(pricing)
        session.commit()
        session.refresh(pricing)
        created.append("pricing_snapshot")

    return DemoBootstrapRead(
        target_id=target.id,
        baseline_version_id=versions["baseline"].id,
        candidate_version_id=versions["candidate"].id,
        dataset_id=dataset.id,
        gate_policy_id=policy.id,
        pricing_snapshot_id=pricing.id,
        created_resources=created,
    )


def import_dataset(
    session: Session, payload: DatasetImport, organization_id: int
) -> tuple[EvalDataset, int]:
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
        organization_id=organization_id,
        name=payload.name,
        version=payload.version,
        split=payload.split,
        sha256=_sha256(dataset_document),
        provenance=dict(payload.provenance),
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


def create_eval_run(session: Session, payload: EvalRunCreate, organization_id: int) -> EvalRun:
    dataset = session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == payload.dataset_id,
            EvalDataset.organization_id == organization_id,
        )
    )
    if dataset is None:
        raise LookupError("dataset not found")
    candidate = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == payload.candidate_version_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if candidate is None:
        raise LookupError("candidate version not found")
    candidate_target = session.get(EvaluationTarget, candidate.target_id)
    if candidate_target is None:
        raise LookupError("candidate target not found")
    if candidate_target.protocol.value not in RUNNABLE_PROTOCOLS:
        raise ValueError(
            f"{candidate_target.protocol.value} Adapter pending; HTTP/SSE/AG-UI/A2A/MCP can execute"
        )
    validate_contract_profile(candidate_target.protocol, dict(candidate_target.capabilities))
    baseline: AgentVersion | None = None
    if payload.baseline_version_id is not None:
        baseline = session.scalar(
            select(AgentVersion)
            .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
            .where(
                AgentVersion.id == payload.baseline_version_id,
                EvaluationTarget.organization_id == organization_id,
            )
        )
        if baseline is None:
            raise LookupError("baseline version not found")
        if payload.baseline_version_id == payload.candidate_version_id:
            raise ValueError("baseline and candidate must be different versions")
        baseline_target = session.get(EvaluationTarget, baseline.target_id)
        if baseline_target is None:
            raise LookupError("baseline target not found")
        if baseline_target.protocol.value not in RUNNABLE_PROTOCOLS:
            raise ValueError(
                f"{baseline_target.protocol.value} Adapter pending; "
                "HTTP/SSE/AG-UI/A2A/MCP can execute"
            )
        validate_contract_profile(baseline_target.protocol, dict(baseline_target.capabilities))
        if baseline.target_id != candidate.target_id and not payload.benchmark_mode:
            raise ValueError(
                "baseline and candidate must belong to the same target; "
                "set benchmark_mode=true for an explicit cross-target comparison"
            )
    case_count = session.scalar(
        select(func.count(EvalCase.id)).where(EvalCase.dataset_id == dataset.id)
    )
    gate_policy = _resolve_policy(session, payload.gate_policy_id, organization_id)
    pricing = _resolve_pricing(session, payload.pricing_snapshot_id, organization_id)
    config = dict(payload.config)
    manifest = {
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "version": dataset.version,
            "sha256": dataset.sha256,
            "provenance": dataset.provenance,
        },
        "versions": {
            "baseline": _version_snapshot(session, baseline),
            "candidate": _version_snapshot(session, candidate),
        },
        "target": _target_snapshot(candidate_target),
        "config_sha256": _sha256(config),
        "gate_policy": _policy_snapshot(session, gate_policy),
        "pricing_snapshot": _pricing_snapshot(pricing),
        "code_version": _code_version(),
    }
    run = EvalRun(
        organization_id=organization_id,
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


def _resolve_policy(
    session: Session, policy_id: int | None, organization_id: int
) -> GatePolicy | None:
    if policy_id is not None:
        policy = session.scalar(
            select(GatePolicy).where(
                GatePolicy.id == policy_id,
                GatePolicy.organization_id == organization_id,
            )
        )
        if policy is None:
            raise LookupError("gate policy not found")
        return policy
    return session.scalar(
        select(GatePolicy)
        .where(
            GatePolicy.organization_id == organization_id,
            GatePolicy.active.is_(True),
        )
        .order_by(GatePolicy.id.desc())
    )


def _resolve_pricing(
    session: Session, pricing_id: int | None, organization_id: int
) -> PricingSnapshot | None:
    if pricing_id is None:
        return None
    pricing = session.scalar(
        select(PricingSnapshot).where(
            PricingSnapshot.id == pricing_id,
            PricingSnapshot.organization_id == organization_id,
        )
    )
    if pricing is None:
        raise LookupError("pricing snapshot not found")
    return pricing


def _version_snapshot(session: Session, version: AgentVersion | None) -> dict | None:
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
        "skills": version_skill_snapshot(session, version.id),
    }


def _target_snapshot(target: EvaluationTarget) -> dict:
    capabilities = dict(target.capabilities)
    return {
        "id": target.id,
        "kind": target.target_kind.value,
        "protocol": target.protocol.value,
        "contract_profile": capabilities.get("contract_profile", "standard_v1"),
        "capabilities": capabilities,
    }


def _policy_snapshot(session: Session, policy: GatePolicy | None) -> dict | None:
    if policy is None:
        return None
    bundle = (
        None
        if policy.policy_bundle_id is None
        else session.get(PolicyBundle, policy.policy_bundle_id)
    )
    return {
        "id": policy.id,
        "name": policy.name,
        "version": policy.version,
        "thresholds": policy.thresholds,
        "policy_bundle": None
        if bundle is None
        else {
            "id": bundle.id,
            "name": bundle.name,
            "version": bundle.version,
            "sha256": bundle.sha256,
            "package_path": bundle.package_path,
            "entrypoint": bundle.entrypoint,
            "status": bundle.status,
        },
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
