from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agent_quality_harness.domain.models import (
    AgentVersionSkill,
    EvalRun,
    PolicyBundle,
    PolicyEvaluation,
    SkillPackage,
    SkillScan,
    SkillVersion,
)
from agent_quality_harness.policy import (
    OpaClient,
    canonical_policy_sha256,
    validate_package_namespace,
)
from agent_quality_harness.security import audit
from agent_quality_harness.skills import (
    SkillValidationError,
    attach_skill_version,
    create_skill_scan,
    import_skill,
    skill_regression,
)

from .dependencies import (
    SessionDependency,
    current_context,
    current_organization_id,
    require_permission,
)
from .schemas import (
    AgentVersionSkillRead,
    Page,
    PolicyBundleCreate,
    PolicyBundleRead,
    PolicyEvaluationRead,
    SkillImport,
    SkillImportRead,
    SkillPackageRead,
    SkillScanRead,
    SkillVersionRead,
)

router = APIRouter()


@router.post(
    "/policy-bundles",
    response_model=PolicyBundleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("policy:manage"))],
)
def post_policy_bundle(
    payload: PolicyBundleCreate, request: Request, session: SessionDependency
):
    organization_id = current_organization_id(request)
    errors: list[dict] = []
    try:
        validate_package_namespace(payload.rego, payload.package_path, organization_id)
    except ValueError as exc:
        errors.append({"code": "invalid_namespace", "message": str(exc)})
    digest = canonical_policy_sha256(
        rego=payload.rego,
        data=payload.data,
        package_path=payload.package_path,
        entrypoint=payload.entrypoint,
    )
    if not errors:
        settings = request.app.state.settings
        client = OpaClient(
            settings.opa_url,
            timeout_seconds=settings.opa_timeout_seconds,
        )
        errors.extend(
            client.validate(policy_id=f"org-{organization_id}-{digest[:16]}", rego=payload.rego)
        )
    bundle = PolicyBundle(
        organization_id=organization_id,
        sha256=digest,
        status="invalid" if errors else "validated",
        validation_errors=errors,
        **payload.model_dump(),
    )
    session.add(bundle)
    try:
        session.flush()
        audit(
            session,
            action="policy_bundle.create",
            outcome="success" if not errors else "invalid",
            context=current_context(request),
            resource_type="policy_bundle",
            resource_id=bundle.id,
            details={
                "name": bundle.name,
                "version": bundle.version,
                "sha256": bundle.sha256,
                "status": bundle.status,
                "validation_errors": bundle.validation_errors,
            },
        )
        session.commit()
        session.refresh(bundle)
        return bundle
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="policy bundle already exists") from exc


@router.get(
    "/policy-bundles",
    response_model=Page[PolicyBundleRead],
    dependencies=[Depends(require_permission("policy:read"))],
)
def list_policy_bundles(
    request: Request,
    session: SessionDependency,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [PolicyBundle.organization_id == current_organization_id(request)]
    if search:
        filters.append(PolicyBundle.name.ilike(f"%{search}%"))
    total = int(session.scalar(select(func.count()).select_from(PolicyBundle).where(*filters)) or 0)
    items = list(
        session.scalars(
            select(PolicyBundle)
            .where(*filters)
            .order_by(PolicyBundle.created_at.desc(), PolicyBundle.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/policy-bundles/{bundle_id}",
    response_model=PolicyBundleRead,
    dependencies=[Depends(require_permission("policy:read"))],
)
def get_policy_bundle(bundle_id: int, request: Request, session: SessionDependency):
    bundle = session.scalar(
        select(PolicyBundle).where(
            PolicyBundle.id == bundle_id,
            PolicyBundle.organization_id == current_organization_id(request),
        )
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="policy bundle not found")
    return bundle


@router.get(
    "/eval-runs/{run_id}/policy-evaluation",
    response_model=PolicyEvaluationRead,
    dependencies=[Depends(require_permission("policy:read"))],
)
def get_policy_evaluation(run_id: int, request: Request, session: SessionDependency):
    evaluation = session.scalar(
        select(PolicyEvaluation)
        .join(EvalRun, EvalRun.id == PolicyEvaluation.run_id)
        .where(
            PolicyEvaluation.run_id == run_id,
            EvalRun.organization_id == current_organization_id(request),
        )
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="policy evaluation not found")
    return evaluation


@router.post(
    "/skills/import",
    response_model=SkillImportRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("skill:manage"))],
)
def post_skill_import(payload: SkillImport, request: Request, session: SessionDependency):
    try:
        package, version = import_skill(
            session,
            organization_id=current_organization_id(request),
            name=payload.name,
            version=payload.version,
            description=payload.description,
            source_ref=payload.source_ref,
            manifest=payload.manifest,
            files=[item.model_dump() for item in payload.files],
        )
        audit(
            session,
            action="skill.import",
            outcome="success",
            context=current_context(request),
            resource_type="skill_version",
            resource_id=version.id,
            details={
                "package": package.name,
                "version": version.version,
                "sha256": version.sha256,
                "file_count": len(version.files),
            },
        )
        session.commit()
        session.refresh(package)
        session.refresh(version)
        return SkillImportRead(package=package, version=version)
    except (SkillValidationError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/skills",
    response_model=Page[SkillPackageRead],
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_skills(
    request: Request,
    session: SessionDependency,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [SkillPackage.organization_id == current_organization_id(request)]
    if search:
        filters.append(SkillPackage.name.ilike(f"%{search}%"))
    total = int(session.scalar(select(func.count()).select_from(SkillPackage).where(*filters)) or 0)
    items = list(
        session.scalars(
            select(SkillPackage)
            .where(*filters)
            .order_by(SkillPackage.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/skills/{skill_id}",
    response_model=SkillPackageRead,
    dependencies=[Depends(require_permission("skill:read"))],
)
def get_skill(skill_id: int, request: Request, session: SessionDependency):
    package = _tenant_package(session, skill_id, current_organization_id(request))
    if package is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return package


@router.get(
    "/skills/{skill_id}/versions",
    response_model=list[SkillVersionRead],
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_skill_versions(skill_id: int, request: Request, session: SessionDependency):
    package = _tenant_package(session, skill_id, current_organization_id(request))
    if package is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return list(
        session.scalars(
            select(SkillVersion)
            .where(SkillVersion.package_id == package.id)
            .order_by(SkillVersion.frozen_at.desc(), SkillVersion.id.desc())
        )
    )


@router.post(
    "/skill-versions/{skill_version_id}/scan",
    response_model=SkillScanRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("skill:scan"))],
)
def post_skill_scan(skill_version_id: int, request: Request, session: SessionDependency):
    version = _tenant_skill_version(
        session, skill_version_id, current_organization_id(request)
    )
    if version is None:
        raise HTTPException(status_code=404, detail="skill version not found")
    scan = create_skill_scan(session, version)
    audit(
        session,
        action="skill.scan",
        outcome="success",
        context=current_context(request),
        resource_type="skill_scan",
        resource_id=scan.id,
        details={
            "skill_version_id": version.id,
            "scanner_version": scan.scanner_version,
            "status": scan.status,
            "summary": scan.summary,
        },
    )
    session.commit()
    session.refresh(scan)
    return scan


@router.get(
    "/skill-versions/{skill_version_id}/scans",
    response_model=list[SkillScanRead],
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_skill_scans(skill_version_id: int, request: Request, session: SessionDependency):
    version = _tenant_skill_version(
        session, skill_version_id, current_organization_id(request)
    )
    if version is None:
        raise HTTPException(status_code=404, detail="skill version not found")
    return list(
        session.scalars(
            select(SkillScan)
            .where(SkillScan.skill_version_id == version.id)
            .order_by(SkillScan.created_at.desc(), SkillScan.id.desc())
        )
    )


@router.put(
    "/versions/{version_id}/skills/{skill_version_id}",
    response_model=AgentVersionSkillRead,
    dependencies=[Depends(require_permission("skill:manage"))],
)
def put_version_skill(
    version_id: int,
    skill_version_id: int,
    request: Request,
    session: SessionDependency,
):
    try:
        attachment = attach_skill_version(
            session,
            organization_id=current_organization_id(request),
            agent_version_id=version_id,
            skill_version_id=skill_version_id,
        )
        audit(
            session,
            action="agent_version.skill.attach",
            outcome="success",
            context=current_context(request),
            resource_type="agent_version",
            resource_id=version_id,
            details={"skill_version_id": skill_version_id},
        )
        session.commit()
        session.refresh(attachment)
        return attachment
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SkillValidationError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/versions/{version_id}/skills",
    response_model=list[AgentVersionSkillRead],
    dependencies=[Depends(require_permission("skill:read"))],
)
def list_version_skills(version_id: int, request: Request, session: SessionDependency):
    organization_id = current_organization_id(request)
    rows = session.scalars(
        select(AgentVersionSkill)
        .join(SkillVersion, SkillVersion.id == AgentVersionSkill.skill_version_id)
        .join(SkillPackage, SkillPackage.id == SkillVersion.package_id)
        .where(
            AgentVersionSkill.agent_version_id == version_id,
            SkillPackage.organization_id == organization_id,
        )
        .order_by(AgentVersionSkill.skill_version_id)
    )
    return list(rows)


@router.get(
    "/eval-runs/{run_id}/skill-regression",
    dependencies=[Depends(require_permission("skill:read"))],
)
def get_skill_regression(run_id: int, request: Request, session: SessionDependency):
    run = session.scalar(
        select(EvalRun).where(
            EvalRun.id == run_id,
            EvalRun.organization_id == current_organization_id(request),
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="eval run not found")
    return skill_regression(session, run)


def _tenant_package(session, skill_id: int, organization_id: int):
    return session.scalar(
        select(SkillPackage).where(
            SkillPackage.id == skill_id,
            SkillPackage.organization_id == organization_id,
        )
    )


def _tenant_skill_version(session, skill_version_id: int, organization_id: int):
    return session.scalar(
        select(SkillVersion)
        .join(SkillPackage, SkillPackage.id == SkillVersion.package_id)
        .where(
            SkillVersion.id == skill_version_id,
            SkillPackage.organization_id == organization_id,
        )
    )
