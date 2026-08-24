import asyncio
import copy
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_quality_harness.domain.enums import RunStatus, VersionRole
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    GateResult,
    PricingSnapshot,
    RunEvent,
    UsageMeasurement,
)
from agent_quality_harness.gates import DEFAULT_THRESHOLDS, aggregate_metrics
from agent_quality_harness.security import audit
from agent_quality_harness.services import (
    bootstrap_demo,
    create_eval_run,
    create_target,
    create_version,
    import_dataset,
)

from .dependencies import (
    SessionDependency,
    current_context,
    current_organization_id,
    require_permission,
)
from .schemas import (
    CaseResultRead,
    DatasetCaseRead,
    DatasetDetail,
    DatasetImport,
    DatasetRead,
    DemoBootstrapCreate,
    DemoBootstrapRead,
    EvalRunCreate,
    EvalRunRead,
    GatePolicyCreate,
    GatePolicyRead,
    GateResultRead,
    Page,
    PricingSnapshotCreate,
    PricingSnapshotRead,
    ReplayCreate,
    RunEventRead,
    TargetCreate,
    TargetRead,
    VersionCreate,
    VersionRead,
)

router = APIRouter()


@router.post(
    "/targets",
    response_model=TargetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("target:manage"))],
)
def post_target(payload: TargetCreate, request: Request, session: SessionDependency):
    try:
        organization_id = current_organization_id(request)
        target = create_target(session, payload, organization_id)
        audit(
            session,
            action="target.create",
            outcome="success",
            context=current_context(request),
            resource_type="target",
            resource_id=target.id,
            details={"name": target.name, "protocol": target.protocol.value},
        )
        session.commit()
        return target
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="target name already exists") from exc


@router.get("/targets", response_model=Page[TargetRead])
def list_targets(
    request: Request,
    session: SessionDependency,
    search: str | None = None,
    protocol: str | None = None,
    enabled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    organization_id = current_organization_id(request)
    filters = [EvaluationTarget.organization_id == organization_id]
    if search:
        filters.append(EvaluationTarget.name.ilike(f"%{search}%"))
    if protocol:
        filters.append(EvaluationTarget.protocol == protocol)
    if enabled is not None:
        filters.append(EvaluationTarget.enabled == enabled)
    total = int(
        session.scalar(select(func.count()).select_from(EvaluationTarget).where(*filters)) or 0
    )
    items = list(
        session.scalars(
            select(EvaluationTarget)
            .where(*filters)
            .order_by(EvaluationTarget.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/targets/{target_id}", response_model=TargetRead)
def get_target(target_id: int, request: Request, session: SessionDependency):
    target = session.scalar(
        select(EvaluationTarget).where(
            EvaluationTarget.id == target_id,
            EvaluationTarget.organization_id == current_organization_id(request),
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return target


@router.get("/targets/{target_id}/versions", response_model=list[VersionRead])
def list_versions(target_id: int, request: Request, session: SessionDependency):
    organization_id = current_organization_id(request)
    target = session.scalar(
        select(EvaluationTarget).where(
            EvaluationTarget.id == target_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")
    return list(
        session.scalars(
            select(AgentVersion)
            .where(AgentVersion.target_id == target_id)
            .order_by(AgentVersion.created_at.desc())
        )
    )


@router.post(
    "/targets/{target_id}/versions",
    response_model=VersionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("target:manage"))],
)
def post_version(
    target_id: int, payload: VersionCreate, request: Request, session: SessionDependency
):
    try:
        version = create_version(
            session,
            target_id,
            payload,
            current_organization_id(request),
        )
        audit(
            session,
            action="target.version.create",
            outcome="success",
            context=current_context(request),
            resource_type="agent_version",
            resource_id=version.id,
            details={"target_id": target_id, "version": version.version},
        )
        session.commit()
        return version
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="version already exists") from exc


@router.post(
    "/demo/bootstrap",
    response_model=DemoBootstrapRead,
    dependencies=[Depends(require_permission("demo:bootstrap"))],
)
def post_demo_bootstrap(
    payload: DemoBootstrapCreate,
    request: Request,
    session: SessionDependency,
):
    settings = request.app.state.settings
    if settings.environment.lower() == "production":
        raise HTTPException(status_code=404, detail="not found")
    try:
        result = bootstrap_demo(
            session,
            organization_id=current_organization_id(request),
            dataset_path=settings.demo_dataset_path,
            agent_endpoint=payload.agent_endpoint or settings.demo_agent_endpoint,
        )
        audit(
            session,
            action="demo.bootstrap",
            outcome="success",
            context=current_context(request),
            resource_type="organization",
            resource_id=current_organization_id(request),
            details={"created_resources": result.created_resources},
        )
        session.commit()
        return result
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"demo bootstrap failed: {exc}") from exc


@router.post(
    "/datasets/import",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("dataset:manage"))],
)
def post_dataset(payload: DatasetImport, request: Request, session: SessionDependency):
    try:
        dataset, case_count = import_dataset(session, payload, current_organization_id(request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="dataset version already exists") from exc
    audit(
        session,
        action="dataset.import",
        outcome="success",
        context=current_context(request),
        resource_type="dataset",
        resource_id=dataset.id,
        details={"name": dataset.name, "version": dataset.version, "case_count": case_count},
    )
    session.commit()
    return DatasetRead(
        id=dataset.id,
        organization_id=dataset.organization_id,
        name=dataset.name,
        version=dataset.version,
        split=dataset.split,
        sha256=dataset.sha256,
        frozen_at=dataset.frozen_at,
        case_count=case_count,
    )


@router.get("/datasets", response_model=Page[DatasetRead])
def list_datasets(
    request: Request,
    session: SessionDependency,
    search: str | None = None,
    version: str | None = None,
    tag: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    organization_id = current_organization_id(request)
    filters = [EvalDataset.organization_id == organization_id]
    if search:
        filters.append(EvalDataset.name.ilike(f"%{search}%"))
    if version:
        filters.append(EvalDataset.version == version)
    if tag:
        filters.append(EvalDataset.cases.any(EvalCase.tags.contains([tag])))
    total = int(session.scalar(select(func.count()).select_from(EvalDataset).where(*filters)) or 0)
    datasets = list(
        session.scalars(
            select(EvalDataset)
            .where(*filters)
            .order_by(EvalDataset.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = [
        DatasetRead(
            id=item.id,
            organization_id=item.organization_id,
            name=item.name,
            version=item.version,
            split=item.split,
            sha256=item.sha256,
            frozen_at=item.frozen_at,
            case_count=int(
                session.scalar(
                    select(func.count(EvalCase.id)).where(EvalCase.dataset_id == item.id)
                )
                or 0
            ),
        )
        for item in datasets
    ]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: int, request: Request, session: SessionDependency):
    dataset = session.scalar(
        select(EvalDataset).where(
            EvalDataset.id == dataset_id,
            EvalDataset.organization_id == current_organization_id(request),
        )
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    cases = list(
        session.scalars(
            select(EvalCase).where(EvalCase.dataset_id == dataset_id).order_by(EvalCase.ordinal)
        )
    )
    return DatasetDetail(
        id=dataset.id,
        organization_id=dataset.organization_id,
        name=dataset.name,
        version=dataset.version,
        split=dataset.split,
        sha256=dataset.sha256,
        frozen_at=dataset.frozen_at,
        case_count=len(cases),
        cases=[DatasetCaseRead.model_validate(case) for case in cases],
    )


@router.post(
    "/eval-runs",
    response_model=EvalRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("run:execute"))],
)
async def post_eval_run(payload: EvalRunCreate, request: Request, session: SessionDependency):
    try:
        run = create_eval_run(session, payload, current_organization_id(request))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        await request.app.state.run_queue.enqueue(run.id)
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.failure_reason = "redis enqueue failed"
        session.commit()
        raise HTTPException(status_code=503, detail="run persisted but enqueue failed") from exc
    audit(
        session,
        action="run.execute",
        outcome="success",
        context=current_context(request),
        resource_type="eval_run",
        resource_id=run.id,
        details={
            "dataset_id": run.dataset_id,
            "baseline_version_id": run.baseline_version_id,
            "candidate_version_id": run.candidate_version_id,
        },
    )
    session.commit()
    return run


@router.get("/eval-runs/{run_id}", response_model=EvalRunRead)
def get_eval_run(run_id: int, request: Request, session: SessionDependency):
    run = _tenant_run(session, run_id, current_organization_id(request))
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return run


@router.get("/eval-runs", response_model=Page[EvalRunRead])
def list_eval_runs(
    request: Request,
    session: SessionDependency,
    status_filter: Annotated[RunStatus | None, Query(alias="status")] = None,
    target_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [EvalRun.organization_id == current_organization_id(request)]
    if status_filter:
        filters.append(EvalRun.status == status_filter)
    if created_from:
        filters.append(EvalRun.created_at >= created_from)
    if created_to:
        filters.append(EvalRun.created_at <= created_to)
    statement = select(EvalRun).where(*filters)
    count_statement = select(func.count()).select_from(EvalRun).where(*filters)
    if target_id is not None:
        statement = statement.join(
            AgentVersion, AgentVersion.id == EvalRun.candidate_version_id
        ).where(AgentVersion.target_id == target_id)
        count_statement = count_statement.join(
            AgentVersion, AgentVersion.id == EvalRun.candidate_version_id
        ).where(AgentVersion.target_id == target_id)
    total = int(session.scalar(count_statement) or 0)
    items = list(
        session.scalars(
            statement.order_by(EvalRun.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/eval-runs/{run_id}/results", response_model=list[CaseResultRead])
def list_run_results(run_id: int, request: Request, session: SessionDependency):
    if _tenant_run(session, run_id, current_organization_id(request)) is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    rows = list(
        session.scalars(
            select(CaseResult)
            .where(CaseResult.run_id == run_id)
            .order_by(CaseResult.case_id, CaseResult.version_role)
        )
    )
    return [
        _case_result_read(session, row, request.app.state.settings.jaeger_base_url) for row in rows
    ]


@router.get("/case-results/{result_id}", response_model=CaseResultRead)
def get_case_result(result_id: int, request: Request, session: SessionDependency):
    row = session.scalar(
        select(CaseResult)
        .join(EvalRun, EvalRun.id == CaseResult.run_id)
        .where(
            CaseResult.id == result_id,
            EvalRun.organization_id == current_organization_id(request),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="case result not found")
    return _case_result_read(session, row, request.app.state.settings.jaeger_base_url)


@router.get("/eval-runs/{run_id}/events")
async def get_run_events(
    run_id: int,
    request: Request,
    session: SessionDependency,
    after_id: int = 0,
    follow: bool = False,
):
    if _tenant_run(session, run_id, current_organization_id(request)) is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    wants_sse = follow or "text/event-stream" in request.headers.get("accept", "")
    if not wants_sse:
        events = list(
            session.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.id > after_id)
                .order_by(RunEvent.id)
            )
        )
        return [RunEventRead.model_validate(event).model_dump(mode="json") for event in events]
    return StreamingResponse(
        _event_stream(request, request.app.state.database, run_id, after_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/eval-runs/{run_id}/cancel",
    response_model=EvalRunRead,
    dependencies=[Depends(require_permission("run:execute"))],
)
def cancel_eval_run(run_id: int, request: Request, session: SessionDependency):
    run = _tenant_run(session, run_id, current_organization_id(request))
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    if run.status is RunStatus.QUEUED:
        run.status = RunStatus.CANCELLED
        run.finished_at = max(datetime.now(UTC), run.created_at)
    elif run.status is RunStatus.RUNNING:
        run.status = RunStatus.CANCEL_REQUESTED
    else:
        return run
    session.add(
        RunEvent(
            run_id=run.id,
            event_type="run.cancel_requested",
            source="api",
            payload={"status": run.status.value},
            redacted=True,
        )
    )
    audit(
        session,
        action="run.cancel",
        outcome="success",
        context=current_context(request),
        resource_type="eval_run",
        resource_id=run.id,
        details={"status": run.status.value},
    )
    session.commit()
    session.refresh(run)
    return run


@router.post(
    "/eval-runs/{run_id}/replay",
    response_model=EvalRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("run:execute"))],
)
async def replay_eval_run(
    run_id: int,
    payload: ReplayCreate,
    request: Request,
    session: SessionDependency,
):
    original = _tenant_run(session, run_id, current_organization_id(request))
    if original is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    failed_ids = list(
        session.scalars(
            select(EvalCase.external_id)
            .join(CaseResult, CaseResult.case_id == EvalCase.id)
            .where(
                CaseResult.run_id == run_id,
                CaseResult.version_role == VersionRole.CANDIDATE,
                CaseResult.failure_type.is_not(None),
            )
            .order_by(EvalCase.ordinal)
        )
    )
    selected = payload.case_ids if payload.case_ids is not None else failed_ids
    if not selected:
        raise HTTPException(status_code=422, detail="no failed candidate cases to replay")
    available = set(
        session.scalars(
            select(EvalCase.external_id).where(EvalCase.dataset_id == original.dataset_id)
        )
    )
    unknown = sorted(set(selected) - available)
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_case_ids": unknown})
    manifest = copy.deepcopy(original.manifest)
    manifest["replay"] = {"of_run_id": original.id, "case_ids": selected}
    config = copy.deepcopy(original.config)
    config["selected_case_ids"] = selected
    replay = EvalRun(
        organization_id=original.organization_id,
        dataset_id=original.dataset_id,
        baseline_version_id=original.baseline_version_id,
        candidate_version_id=original.candidate_version_id,
        replay_of_run_id=original.id,
        gate_policy_id=original.gate_policy_id,
        pricing_snapshot_id=original.pricing_snapshot_id,
        status=RunStatus.QUEUED,
        config=config,
        manifest=manifest,
        benchmark_mode=original.benchmark_mode,
        expected_case_count=len(selected),
    )
    session.add(replay)
    session.commit()
    session.refresh(replay)
    await request.app.state.run_queue.enqueue(replay.id)
    audit(
        session,
        action="run.replay",
        outcome="success",
        context=current_context(request),
        resource_type="eval_run",
        resource_id=replay.id,
        details={"replay_of_run_id": original.id, "case_ids": selected},
    )
    session.commit()
    return replay


@router.get("/eval-runs/{run_id}/comparison")
def get_run_comparison(run_id: int, request: Request, session: SessionDependency):
    run = _tenant_run(session, run_id, current_organization_id(request))
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    metrics = {
        role.value: aggregate_metrics(_metric_rows(session, run_id, role))
        for role in (VersionRole.BASELINE, VersionRole.CANDIDATE)
    }
    return {"run_id": run_id, **metrics}


@router.get("/eval-runs/{run_id}/gate", response_model=GateResultRead)
def get_run_gate(run_id: int, request: Request, session: SessionDependency):
    result = session.scalar(
        select(GateResult)
        .join(EvalRun, EvalRun.id == GateResult.run_id)
        .where(
            GateResult.run_id == run_id,
            EvalRun.organization_id == current_organization_id(request),
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="gate result not found")
    return result


@router.post(
    "/gate-policies",
    response_model=GatePolicyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("gate:manage"))],
)
def post_gate_policy(payload: GatePolicyCreate, request: Request, session: SessionDependency):
    policy = GatePolicy(
        organization_id=current_organization_id(request),
        name=payload.name,
        version=payload.version,
        thresholds=DEFAULT_THRESHOLDS | payload.thresholds,
        active=payload.active,
    )
    session.add(policy)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="gate policy version exists") from exc
    session.refresh(policy)
    audit(
        session,
        action="gate_policy.create",
        outcome="success",
        context=current_context(request),
        resource_type="gate_policy",
        resource_id=policy.id,
        details={"name": policy.name, "version": policy.version},
    )
    session.commit()
    return policy


@router.get("/gate-policies", response_model=list[GatePolicyRead])
def list_gate_policies(request: Request, session: SessionDependency):
    return list(
        session.scalars(
            select(GatePolicy)
            .where(GatePolicy.organization_id == current_organization_id(request))
            .order_by(GatePolicy.id.desc())
        )
    )


@router.post(
    "/pricing-snapshots",
    response_model=PricingSnapshotRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("gate:manage"))],
)
def post_pricing_snapshot(
    payload: PricingSnapshotCreate, request: Request, session: SessionDependency
):
    data = payload.model_dump(mode="python")
    data["prices"] = payload.model_dump(mode="json")["prices"]
    snapshot = PricingSnapshot(organization_id=current_organization_id(request), **data)
    session.add(snapshot)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="pricing snapshot version exists") from exc
    session.refresh(snapshot)
    audit(
        session,
        action="pricing_snapshot.create",
        outcome="success",
        context=current_context(request),
        resource_type="pricing_snapshot",
        resource_id=snapshot.id,
        details={
            "provider": snapshot.provider,
            "model": snapshot.model,
            "version": snapshot.version,
        },
    )
    session.commit()
    return snapshot


@router.get("/pricing-snapshots", response_model=list[PricingSnapshotRead])
def list_pricing_snapshots(request: Request, session: SessionDependency):
    return list(
        session.scalars(
            select(PricingSnapshot)
            .where(PricingSnapshot.organization_id == current_organization_id(request))
            .order_by(PricingSnapshot.id.desc())
        )
    )


def _case_result_read(session: Session, row: CaseResult, jaeger_base_url: str) -> dict:
    usage = session.scalar(
        select(UsageMeasurement).where(UsageMeasurement.case_result_id == row.id)
    )
    return {
        "id": row.id,
        "run_id": row.run_id,
        "case_id": row.case_id,
        "version_role": row.version_role,
        "attempt": row.attempt,
        "output": row.output,
        "final_action": row.final_action,
        "trace_id": row.trace_id,
        "trace_url": (
            None if row.trace_id is None else f"{jaeger_base_url.rstrip('/')}/trace/{row.trace_id}"
        ),
        "scores": row.scores,
        "failure_type": row.failure_type,
        "latency_ms": row.latency_ms,
        "usage": usage,
    }


def _metric_rows(session: Session, run_id: int, role: VersionRole) -> list[dict]:
    rows = session.execute(
        select(CaseResult, UsageMeasurement)
        .outerjoin(UsageMeasurement, UsageMeasurement.case_result_id == CaseResult.id)
        .where(CaseResult.run_id == run_id, CaseResult.version_role == role)
    )
    return [
        {
            "scores": result.scores,
            "latency_ms": result.latency_ms,
            "model_cost": None if usage is None else usage.model_cost,
            "external_tool_cost": None if usage is None else usage.external_tool_cost,
        }
        for result, usage in rows
    ]


def _tenant_run(session: Session, run_id: int, organization_id: int) -> EvalRun | None:
    return session.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.organization_id == organization_id,
        )
    )


async def _event_stream(
    request: Request, database, run_id: int, after_id: int
) -> AsyncIterator[str]:
    cursor = after_id
    while not await request.is_disconnected():
        with database.session() as session:
            events = list(
                session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > cursor)
                    .order_by(RunEvent.id)
                )
            )
            run_status = session.scalar(select(EvalRun.status).where(EvalRun.id == run_id))
        for event in events:
            cursor = event.id
            data = RunEventRead.model_validate(event).model_dump(mode="json")
            yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(data)}\n\n"
        if run_status in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}:
            break
        await asyncio.sleep(0.5)
