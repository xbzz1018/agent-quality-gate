import asyncio
import copy
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_quality_harness.domain.enums import RunStatus, VersionRole
from agent_quality_harness.domain.models import (
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
from agent_quality_harness.services import (
    create_eval_run,
    create_target,
    create_version,
    import_dataset,
)

from .schemas import (
    CaseResultRead,
    DatasetCaseRead,
    DatasetDetail,
    DatasetImport,
    DatasetRead,
    EvalRunCreate,
    EvalRunRead,
    GatePolicyCreate,
    GatePolicyRead,
    GateResultRead,
    PricingSnapshotCreate,
    PricingSnapshotRead,
    Readiness,
    ReplayCreate,
    RunEventRead,
    TargetCreate,
    TargetRead,
    VersionCreate,
    VersionRead,
)

router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", response_model=Readiness)
async def ready(request: Request) -> Readiness:
    components: dict[str, str] = {}
    try:
        request.app.state.database.ping()
        components["postgresql"] = "ok"
    except Exception:
        components["postgresql"] = "unavailable"
    try:
        await request.app.state.run_queue.ping()
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "unavailable"
    if all(value == "ok" for value in components.values()):
        return Readiness(status="ready", components=components)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=Readiness(status="not_ready", components=components).model_dump(),
    )


@router.post("/targets", response_model=TargetRead, status_code=status.HTTP_201_CREATED)
def post_target(payload: TargetCreate, session: SessionDependency):
    try:
        return create_target(session, payload)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="target name already exists") from exc


@router.get("/targets", response_model=list[TargetRead])
def list_targets(session: SessionDependency):
    return list(session.scalars(select(EvaluationTarget).order_by(EvaluationTarget.name)))


@router.post(
    "/targets/{target_id}/versions",
    response_model=VersionRead,
    status_code=status.HTTP_201_CREATED,
)
def post_version(target_id: int, payload: VersionCreate, session: SessionDependency):
    try:
        return create_version(session, target_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="version already exists") from exc


@router.post("/datasets/import", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def post_dataset(payload: DatasetImport, session: SessionDependency):
    try:
        dataset, case_count = import_dataset(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="dataset version already exists") from exc
    return DatasetRead(
        id=dataset.id,
        name=dataset.name,
        version=dataset.version,
        split=dataset.split,
        sha256=dataset.sha256,
        frozen_at=dataset.frozen_at,
        case_count=case_count,
    )


@router.get("/datasets", response_model=list[DatasetRead])
def list_datasets(session: SessionDependency):
    datasets = list(session.scalars(select(EvalDataset).order_by(EvalDataset.id.desc())))
    return [
        DatasetRead(
            id=item.id,
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


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: int, session: SessionDependency):
    dataset = session.get(EvalDataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    cases = list(
        session.scalars(
            select(EvalCase).where(EvalCase.dataset_id == dataset_id).order_by(EvalCase.ordinal)
        )
    )
    return DatasetDetail(
        id=dataset.id,
        name=dataset.name,
        version=dataset.version,
        split=dataset.split,
        sha256=dataset.sha256,
        frozen_at=dataset.frozen_at,
        case_count=len(cases),
        cases=[DatasetCaseRead.model_validate(case) for case in cases],
    )


@router.post("/eval-runs", response_model=EvalRunRead, status_code=status.HTTP_202_ACCEPTED)
async def post_eval_run(payload: EvalRunCreate, request: Request, session: SessionDependency):
    try:
        run = create_eval_run(session, payload)
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
    return run


@router.get("/eval-runs/{run_id}", response_model=EvalRunRead)
def get_eval_run(run_id: int, session: SessionDependency):
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return run


@router.get("/eval-runs", response_model=list[EvalRunRead])
def list_eval_runs(session: SessionDependency, limit: int = 100):
    return list(session.scalars(select(EvalRun).order_by(EvalRun.id.desc()).limit(min(limit, 500))))


@router.get("/eval-runs/{run_id}/results", response_model=list[CaseResultRead])
def list_run_results(run_id: int, request: Request, session: SessionDependency):
    if session.get(EvalRun, run_id) is None:
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
    row = session.get(CaseResult, result_id)
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
    if session.get(EvalRun, run_id) is None:
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


@router.post("/eval-runs/{run_id}/cancel", response_model=EvalRunRead)
def cancel_eval_run(run_id: int, session: SessionDependency):
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    if run.status is RunStatus.QUEUED:
        run.status = RunStatus.CANCELLED
        run.finished_at = datetime.now(UTC)
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
    session.commit()
    session.refresh(run)
    return run


@router.post(
    "/eval-runs/{run_id}/replay",
    response_model=EvalRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def replay_eval_run(
    run_id: int,
    payload: ReplayCreate,
    request: Request,
    session: SessionDependency,
):
    original = session.get(EvalRun, run_id)
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
    return replay


@router.get("/eval-runs/{run_id}/comparison")
def get_run_comparison(run_id: int, session: SessionDependency):
    run = session.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    metrics = {
        role.value: aggregate_metrics(_metric_rows(session, run_id, role))
        for role in (VersionRole.BASELINE, VersionRole.CANDIDATE)
    }
    return {"run_id": run_id, **metrics}


@router.get("/eval-runs/{run_id}/gate", response_model=GateResultRead)
def get_run_gate(run_id: int, session: SessionDependency):
    result = session.scalar(select(GateResult).where(GateResult.run_id == run_id))
    if result is None:
        raise HTTPException(status_code=404, detail="gate result not found")
    return result


@router.post(
    "/gate-policies",
    response_model=GatePolicyRead,
    status_code=status.HTTP_201_CREATED,
)
def post_gate_policy(payload: GatePolicyCreate, session: SessionDependency):
    policy = GatePolicy(
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
    return policy


@router.get("/gate-policies", response_model=list[GatePolicyRead])
def list_gate_policies(session: SessionDependency):
    return list(session.scalars(select(GatePolicy).order_by(GatePolicy.id.desc())))


@router.post(
    "/pricing-snapshots",
    response_model=PricingSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def post_pricing_snapshot(payload: PricingSnapshotCreate, session: SessionDependency):
    data = payload.model_dump(mode="python")
    data["prices"] = payload.model_dump(mode="json")["prices"]
    snapshot = PricingSnapshot(**data)
    session.add(snapshot)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="pricing snapshot version exists") from exc
    session.refresh(snapshot)
    return snapshot


@router.get("/pricing-snapshots", response_model=list[PricingSnapshotRead])
def list_pricing_snapshots(session: SessionDependency):
    return list(session.scalars(select(PricingSnapshot).order_by(PricingSnapshot.id.desc())))


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
