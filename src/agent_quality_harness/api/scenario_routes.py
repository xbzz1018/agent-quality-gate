from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_quality_harness.api.dependencies import (
    SessionDependency,
    current_context,
    current_organization_id,
    require_permission,
)
from agent_quality_harness.api.schemas import (
    Page,
    ScenarioNodeRunRead,
    ScenarioRunCreate,
    ScenarioRunRead,
)
from agent_quality_harness.domain.enums import RunStatus
from agent_quality_harness.domain.models import (
    AgentVersion,
    EvalRun,
    RunEvent,
    ScenarioNodeRun,
    ScenarioRun,
)
from agent_quality_harness.scenario_runtime import create_scenario_run
from agent_quality_harness.scenarios import resolve_scenario_version, scenario_snapshot
from agent_quality_harness.security import audit

router = APIRouter()


@router.get(
    "/scenario-runs",
    response_model=Page[ScenarioRunRead],
    dependencies=[Depends(require_permission("run:read"))],
)
def list_scenario_runs(
    request: Request,
    session: SessionDependency,
    run_status: str | None = None,
    mode: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [ScenarioRun.organization_id == current_organization_id(request)]
    if run_status:
        filters.append(ScenarioRun.status == run_status)
    if mode:
        filters.append(ScenarioRun.mode == mode)
    total = int(session.scalar(select(func.count(ScenarioRun.id)).where(*filters)) or 0)
    rows = list(
        session.scalars(
            select(ScenarioRun)
            .where(*filters)
            .order_by(ScenarioRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(
        items=[_scenario_read(session, row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/scenario-versions/{version_id}/validate",
    dependencies=[Depends(require_permission("target:manage"))],
)
def validate_scenario_version(
    version_id: int,
    request: Request,
    session: SessionDependency,
):
    organization_id = current_organization_id(request)
    from agent_quality_harness.domain.models import EvaluationTarget

    version = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == version_id,
            EvaluationTarget.organization_id == organization_id,
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="scenario version not found")
    try:
        plan, _ = resolve_scenario_version(session, version, organization_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"valid": True, **scenario_snapshot(plan)}


@router.post(
    "/scenario-runs",
    response_model=ScenarioRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("run:execute"))],
)
async def post_scenario_run(
    payload: ScenarioRunCreate,
    request: Request,
    session: SessionDependency,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=200),
    ],
):
    try:
        row, created = create_scenario_run(
            session,
            payload,
            organization_id=current_organization_id(request),
            context=current_context(request),
            idempotency_key=idempotency_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        await request.app.state.scenario_queue.enqueue(row.id)
    audit(
        session,
        action="scenario.run.create",
        outcome="success",
        context=current_context(request),
        resource_type="scenario_run",
        resource_id=row.id,
        details={"mode": row.mode.value, "created": created},
    )
    session.commit()
    return _scenario_read(session, row)


@router.get(
    "/scenario-runs/{run_id}",
    response_model=ScenarioRunRead,
    dependencies=[Depends(require_permission("run:read"))],
)
def get_scenario_run(run_id: int, request: Request, session: SessionDependency):
    row = _organization_run(session, run_id, current_organization_id(request))
    if row is None:
        raise HTTPException(status_code=404, detail="scenario run not found")
    return _scenario_read(session, row)


@router.post(
    "/scenario-runs/{run_id}/cancel",
    response_model=ScenarioRunRead,
    dependencies=[Depends(require_permission("run:execute"))],
)
def cancel_scenario_run(run_id: int, request: Request, session: SessionDependency):
    row = _organization_run(session, run_id, current_organization_id(request))
    if row is None:
        raise HTTPException(status_code=404, detail="scenario run not found")
    if row.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
        row.status = RunStatus.CANCEL_REQUESTED
        session.commit()
    return _scenario_read(session, row)


@router.get(
    "/eval-runs/{run_id}/scenario",
    dependencies=[Depends(require_permission("run:read"))],
)
def get_eval_run_scenario(run_id: int, request: Request, session: SessionDependency):
    run = session.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.organization_id == current_organization_id(request),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="evaluation run not found")
    scenario = run.manifest.get("scenario")
    if not isinstance(scenario, dict):
        raise HTTPException(status_code=404, detail="evaluation run has no scenario")
    events = list(
        session.scalars(
            select(RunEvent)
            .where(
                RunEvent.run_id == run.id,
                RunEvent.event_type.like("scenario.%"),
            )
            .order_by(RunEvent.id)
        )
    )
    return {
        "run_id": run.id,
        "scenario": scenario,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "source": event.source,
                "payload": event.payload,
                "occurred_at": event.occurred_at,
            }
            for event in events
        ],
    }


def _organization_run(
    session: Session, run_id: int, organization_id: int
) -> ScenarioRun | None:
    return session.scalar(
        select(ScenarioRun).where(
            ScenarioRun.id == run_id,
            ScenarioRun.organization_id == organization_id,
        )
    )


def _scenario_read(session: Session, row: ScenarioRun) -> ScenarioRunRead:
    nodes = list(
        session.scalars(
            select(ScenarioNodeRun)
            .where(ScenarioNodeRun.scenario_run_id == row.id)
            .order_by(ScenarioNodeRun.id)
        )
    )
    return ScenarioRunRead(
        **{
            field: getattr(row, field)
            for field in ScenarioRunRead.model_fields
            if field != "nodes"
        },
        nodes=[ScenarioNodeRunRead.model_validate(node) for node in nodes],
    )
