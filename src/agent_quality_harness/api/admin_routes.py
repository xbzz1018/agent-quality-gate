from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from agent_quality_harness.administration import add_membership, provision_organization
from agent_quality_harness.domain.models import (
    ApiKey,
    AuditLog,
    AuthSession,
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    ServiceAccount,
    SystemSetting,
    User,
)
from agent_quality_harness.security import (
    AuthContext,
    audit,
    create_api_key,
    hash_password,
    user_organizations,
)

from .dependencies import (
    AuthDependency,
    OrganizationDependency,
    SessionDependency,
    require_permission,
)

router = APIRouter(tags=["administration"])


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,98}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=200)


class OrganizationRead(ApiModel):
    id: int
    slug: str
    name: str
    active: bool
    created_at: datetime


class MemberCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    password: str = Field(min_length=12, max_length=1000)
    role_ids: list[int] = Field(default_factory=list)


class MemberUpdate(BaseModel):
    active: bool | None = None
    role_ids: list[int] | None = None
    new_password: str | None = Field(default=None, min_length=12, max_length=1000)


class MemberRead(BaseModel):
    membership_id: int
    user_id: int
    username: str
    display_name: str
    email: str | None
    active: bool
    role_ids: list[int]
    role_names: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    permission_codes: list[str] | None = None


class RoleRead(ApiModel):
    id: int
    organization_id: int
    name: str
    description: str
    system: bool
    permission_codes: list[str] = Field(default_factory=list)


class PermissionRead(ApiModel):
    id: int
    code: str
    name: str
    description: str


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class ServiceAccountRead(ApiModel):
    id: int
    organization_id: int
    name: str
    description: str
    active: bool
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyRead(ApiModel):
    id: int
    service_account_id: int
    name: str
    prefix: str
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    api_key: str


class AuditRead(ApiModel):
    id: int
    organization_id: int | None
    actor_type: str
    actor_id: int | None
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    details: dict[str, Any]
    created_at: datetime


class SettingPut(BaseModel):
    value: dict[str, Any]


class SettingRead(ApiModel):
    id: int
    organization_id: int | None
    key: str
    value: dict[str, Any]
    updated_at: datetime


class AdminSessionRead(ApiModel):
    id: int
    user_id: int
    username: str
    display_name: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    ip_address: str | None
    user_agent: str | None


def _require_platform_admin(context: AuthDependency) -> AuthContext:
    if not context.platform_admin:
        raise HTTPException(status_code=403, detail="platform administrator required")
    return context


PlatformAdminDependency = Depends(_require_platform_admin)


@router.get("/organizations", response_model=list[OrganizationRead])
def organizations(context: AuthDependency, session: SessionDependency):
    if context.user_id is None:
        raise HTTPException(status_code=403, detail="interactive user required")
    user = session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    allowed = {item["id"] for item in user_organizations(session, user)}
    return list(
        session.scalars(
            select(Organization).where(Organization.id.in_(allowed)).order_by(Organization.name)
        )
    )


@router.post(
    "/organizations",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[PlatformAdminDependency],
)
def post_organization(
    payload: OrganizationCreate,
    request: Request,
    context: AuthDependency,
    session: SessionDependency,
):
    try:
        organization = provision_organization(session, slug=payload.slug, name=payload.name)
        audit(
            session,
            action="organization.create",
            outcome="success",
            context=context,
            organization_id=organization.id,
            resource_type="organization",
            resource_id=organization.id,
            details={"slug": organization.slug, "name": organization.name},
        )
        session.commit()
        session.refresh(organization)
        return organization
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="organization slug already exists") from exc


@router.get(
    "/platform/health",
    dependencies=[PlatformAdminDependency],
)
async def platform_health(
    request: Request,
    session: SessionDependency,
):
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
    return {
        "status": "healthy" if all(value == "ok" for value in components.values()) else "degraded",
        "components": components,
        "organization_count": int(
            session.scalar(select(func.count()).select_from(Organization)) or 0
        ),
        "active_user_count": int(
            session.scalar(select(func.count()).select_from(User).where(User.active.is_(True))) or 0
        ),
    }


@router.get(
    "/members",
    response_model=list[MemberRead],
    dependencies=[Depends(require_permission("member:manage"))],
)
def members(context: OrganizationDependency, session: SessionDependency):
    memberships = list(
        session.scalars(
            select(Membership)
            .where(Membership.organization_id == context.organization_id)
            .order_by(Membership.id)
        )
    )
    result: list[MemberRead] = []
    for membership in memberships:
        user = session.get(User, membership.user_id)
        roles = list(
            session.scalars(
                select(Role)
                .join(MembershipRole, MembershipRole.role_id == Role.id)
                .where(MembershipRole.membership_id == membership.id)
                .order_by(Role.name)
            )
        )
        if user is not None:
            result.append(
                MemberRead(
                    membership_id=membership.id,
                    user_id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                    email=user.email,
                    active=membership.active and user.active,
                    role_ids=[role.id for role in roles],
                    role_names=[role.name for role in roles],
                )
            )
    return result


@router.post(
    "/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("member:manage"))],
)
def post_member(payload: MemberCreate, context: OrganizationDependency, session: SessionDependency):
    organization = session.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="organization not found")
    role_ids = payload.role_ids
    if not role_ids:
        viewer = session.scalar(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.name == "Viewer",
            )
        )
        role_ids = [] if viewer is None else [viewer.id]
    roles = list(
        session.scalars(
            select(Role).where(Role.organization_id == organization.id, Role.id.in_(role_ids))
        )
    )
    if len(roles) != len(set(role_ids)):
        raise HTTPException(status_code=404, detail="role not found")
    try:
        user = User(
            username=payload.username,
            email=payload.email,
            display_name=payload.display_name,
            password_hash=hash_password(payload.password),
            active=True,
            platform_admin=False,
        )
        session.add(user)
        session.flush()
        membership = add_membership(
            session,
            user=user,
            organization=organization,
            role_names=[role.name for role in roles],
        )
        audit(
            session,
            action="member.create",
            outcome="success",
            context=context,
            resource_type="membership",
            resource_id=membership.id,
            details={"username": user.username, "role_ids": role_ids},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="username or email already exists") from exc
    return MemberRead(
        membership_id=membership.id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        active=True,
        role_ids=role_ids,
        role_names=[role.name for role in roles],
    )


@router.patch(
    "/members/{membership_id}",
    response_model=MemberRead,
    dependencies=[Depends(require_permission("member:manage"))],
)
def patch_member(
    membership_id: int,
    payload: MemberUpdate,
    context: OrganizationDependency,
    session: SessionDependency,
):
    membership = session.scalar(
        select(Membership).where(
            Membership.id == membership_id,
            Membership.organization_id == context.organization_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="membership not found")
    user = session.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.active is not None:
        membership.active = payload.active
    if payload.new_password is not None:
        user.password_hash = hash_password(payload.new_password)
        user.password_changed_at = datetime.now(UTC)
        session.query(AuthSession).filter(AuthSession.user_id == user.id).update(
            {AuthSession.revoked_at: datetime.now(UTC)}
        )
    if payload.role_ids is not None:
        roles = list(
            session.scalars(
                select(Role).where(
                    Role.organization_id == context.organization_id,
                    Role.id.in_(payload.role_ids),
                )
            )
        )
        if len(roles) != len(set(payload.role_ids)):
            raise HTTPException(status_code=404, detail="role not found")
        session.query(MembershipRole).filter(MembershipRole.membership_id == membership.id).delete()
        session.add_all(
            MembershipRole(membership_id=membership.id, role_id=role.id) for role in roles
        )
    else:
        roles = list(
            session.scalars(
                select(Role)
                .join(MembershipRole, MembershipRole.role_id == Role.id)
                .where(MembershipRole.membership_id == membership.id)
            )
        )
    audit(
        session,
        action="member.update",
        outcome="success",
        context=context,
        resource_type="membership",
        resource_id=membership.id,
        details=payload.model_dump(exclude_none=True),
    )
    session.commit()
    return MemberRead(
        membership_id=membership.id,
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        active=membership.active and user.active,
        role_ids=[role.id for role in roles],
        role_names=[role.name for role in roles],
    )


@router.get("/permissions", response_model=list[PermissionRead])
def permissions(_: OrganizationDependency, session: SessionDependency):
    return list(session.scalars(select(Permission).order_by(Permission.code)))


@router.get("/roles", response_model=list[RoleRead])
def roles(context: OrganizationDependency, session: SessionDependency):
    rows = list(
        session.scalars(
            select(Role)
            .where(Role.organization_id == context.organization_id)
            .order_by(Role.system.desc(), Role.name)
        )
    )
    return [_role_read(session, row) for row in rows]


@router.post(
    "/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("role:manage"))],
)
def post_role(payload: RoleCreate, context: OrganizationDependency, session: SessionDependency):
    permissions = list(
        session.scalars(select(Permission).where(Permission.code.in_(payload.permission_codes)))
    )
    if len(permissions) != len(set(payload.permission_codes)):
        raise HTTPException(status_code=422, detail="unknown permission code")
    role = Role(
        organization_id=context.organization_id,
        name=payload.name,
        description=payload.description,
        system=False,
    )
    session.add(role)
    try:
        session.flush()
        session.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permissions
        )
        audit(
            session,
            action="role.create",
            outcome="success",
            context=context,
            resource_type="role",
            resource_id=role.id,
            details={"name": role.name, "permission_codes": payload.permission_codes},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="role name already exists") from exc
    return _role_read(session, role)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleRead,
    dependencies=[Depends(require_permission("role:manage"))],
)
def patch_role(
    role_id: int,
    payload: RoleUpdate,
    context: OrganizationDependency,
    session: SessionDependency,
):
    role = session.scalar(
        select(Role).where(
            Role.id == role_id,
            Role.organization_id == context.organization_id,
        )
    )
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    if role.system:
        raise HTTPException(status_code=422, detail="system roles are immutable")
    if payload.description is not None:
        role.description = payload.description
    if payload.permission_codes is not None:
        permissions = list(
            session.scalars(select(Permission).where(Permission.code.in_(payload.permission_codes)))
        )
        if len(permissions) != len(set(payload.permission_codes)):
            raise HTTPException(status_code=422, detail="unknown permission code")
        session.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
        session.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id)
            for permission in permissions
        )
    audit(
        session,
        action="role.update",
        outcome="success",
        context=context,
        resource_type="role",
        resource_id=role.id,
        details=payload.model_dump(exclude_none=True),
    )
    session.commit()
    return _role_read(session, role)


@router.get("/service-accounts", response_model=list[ServiceAccountRead])
def service_accounts(context: OrganizationDependency, session: SessionDependency):
    return list(
        session.scalars(
            select(ServiceAccount)
            .where(ServiceAccount.organization_id == context.organization_id)
            .order_by(ServiceAccount.id.desc())
        )
    )


@router.post(
    "/service-accounts",
    response_model=ServiceAccountRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("service_account:manage"))],
)
def post_service_account(
    payload: ServiceAccountCreate,
    context: OrganizationDependency,
    session: SessionDependency,
):
    row = ServiceAccount(
        organization_id=context.organization_id,
        name=payload.name,
        description=payload.description,
        active=True,
    )
    session.add(row)
    try:
        session.flush()
        audit(
            session,
            action="service_account.create",
            outcome="success",
            context=context,
            resource_type="service_account",
            resource_id=row.id,
            details={"name": row.name},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="service account name already exists") from exc
    session.refresh(row)
    return row


@router.get("/service-accounts/{account_id}/api-keys", response_model=list[ApiKeyRead])
def api_keys(account_id: int, context: OrganizationDependency, session: SessionDependency):
    account = _service_account(session, context, account_id)
    return list(
        session.scalars(
            select(ApiKey).where(ApiKey.service_account_id == account.id).order_by(ApiKey.id.desc())
        )
    )


@router.post(
    "/service-accounts/{account_id}/api-keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("service_account:manage"))],
)
def post_api_key(
    account_id: int,
    payload: ApiKeyCreate,
    context: OrganizationDependency,
    session: SessionDependency,
):
    account = _service_account(session, context, account_id)
    plaintext, row = create_api_key(session, account, payload.name)
    audit(
        session,
        action="api_key.create",
        outcome="success",
        context=context,
        resource_type="api_key",
        resource_id=row.id,
        details={"name": row.name, "prefix": row.prefix},
    )
    session.commit()
    session.refresh(row)
    return ApiKeyCreated(
        **ApiKeyRead.model_validate(row).model_dump(),
        api_key=plaintext,
    )


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("service_account:manage"))],
)
def revoke_api_key(key_id: int, context: OrganizationDependency, session: SessionDependency):
    row = session.scalar(
        select(ApiKey)
        .join(ServiceAccount, ServiceAccount.id == ApiKey.service_account_id)
        .where(ApiKey.id == key_id, ServiceAccount.organization_id == context.organization_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    audit(
        session,
        action="api_key.revoke",
        outcome="success",
        context=context,
        resource_type="api_key",
        resource_id=row.id,
        details={"prefix": row.prefix},
    )
    session.commit()


@router.get(
    "/audit-logs",
    response_model=list[AuditRead],
    dependencies=[Depends(require_permission("audit:read"))],
)
def audit_logs(
    context: OrganizationDependency,
    session: SessionDependency,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    statement = select(AuditLog).where(AuditLog.organization_id == context.organization_id)
    if action:
        statement = statement.where(AuditLog.action == action)
    return list(session.scalars(statement.order_by(AuditLog.id.desc()).limit(limit)))


@router.get("/settings", response_model=list[SettingRead])
def settings(context: OrganizationDependency, session: SessionDependency):
    return list(
        session.scalars(
            select(SystemSetting)
            .where(SystemSetting.organization_id == context.organization_id)
            .order_by(SystemSetting.key)
        )
    )


@router.get(
    "/admin/sessions",
    response_model=list[AdminSessionRead],
    dependencies=[Depends(require_permission("member:manage"))],
)
def admin_sessions(context: OrganizationDependency, session: SessionDependency):
    rows = list(
        session.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == context.organization_id)
            .order_by(AuthSession.id.desc())
            .limit(200)
        )
    )
    return [
        AdminSessionRead(
            id=auth_session.id,
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            created_at=auth_session.created_at,
            expires_at=auth_session.expires_at,
            last_used_at=auth_session.last_used_at,
            revoked_at=auth_session.revoked_at,
            ip_address=auth_session.ip_address,
            user_agent=auth_session.user_agent,
        )
        for auth_session, user in rows
    ]


@router.delete(
    "/admin/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("member:manage"))],
)
def revoke_admin_session(
    session_id: int,
    context: OrganizationDependency,
    session: SessionDependency,
):
    row = session.scalar(
        select(AuthSession)
        .join(User, User.id == AuthSession.user_id)
        .join(Membership, Membership.user_id == User.id)
        .where(
            AuthSession.id == session_id,
            Membership.organization_id == context.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    audit(
        session,
        action="auth.session.admin_revoke",
        outcome="success",
        context=context,
        resource_type="auth_session",
        resource_id=row.id,
    )
    session.commit()


ALLOWED_SETTING_KEYS = {
    "security.session_limit",
    "evaluation.default_gate_policy_id",
    "evaluation.default_pricing_snapshot_id",
    "retention.days",
    "timezone",
}

PLATFORM_SETTING_KEYS = {
    "security.access_token_minutes",
    "security.refresh_session_days",
    "retention.default_days",
    "timezone.default",
}


@router.put(
    "/settings/{key}",
    response_model=SettingRead,
    dependencies=[Depends(require_permission("setting:manage"))],
)
def put_setting(
    key: str,
    payload: SettingPut,
    context: OrganizationDependency,
    session: SessionDependency,
):
    if key not in ALLOWED_SETTING_KEYS:
        raise HTTPException(status_code=422, detail="setting key is not allowed")
    row = session.scalar(
        select(SystemSetting).where(
            SystemSetting.organization_id == context.organization_id,
            SystemSetting.key == key,
        )
    )
    if row is None:
        row = SystemSetting(organization_id=context.organization_id, key=key, value=payload.value)
        session.add(row)
    else:
        row.value = payload.value
    row.updated_by_user_id = context.user_id
    session.flush()
    audit(
        session,
        action="setting.update",
        outcome="success",
        context=context,
        resource_type="system_setting",
        resource_id=row.id,
        details={"key": key},
    )
    session.commit()
    session.refresh(row)
    return row


@router.get(
    "/platform/settings",
    response_model=list[SettingRead],
    dependencies=[PlatformAdminDependency],
)
def platform_settings(session: SessionDependency):
    return list(
        session.scalars(
            select(SystemSetting)
            .where(SystemSetting.organization_id.is_(None))
            .order_by(SystemSetting.key)
        )
    )


@router.put(
    "/platform/settings/{key}",
    response_model=SettingRead,
    dependencies=[PlatformAdminDependency],
)
def put_platform_setting(
    key: str,
    payload: SettingPut,
    context: AuthDependency,
    session: SessionDependency,
):
    if key not in PLATFORM_SETTING_KEYS:
        raise HTTPException(status_code=422, detail="platform setting key is not allowed")
    row = session.scalar(
        select(SystemSetting).where(
            SystemSetting.organization_id.is_(None),
            SystemSetting.key == key,
        )
    )
    if row is None:
        row = SystemSetting(organization_id=None, key=key, value=payload.value)
        session.add(row)
    else:
        row.value = payload.value
    row.updated_by_user_id = context.user_id
    session.flush()
    audit(
        session,
        action="platform_setting.update",
        outcome="success",
        context=context,
        resource_type="system_setting",
        resource_id=row.id,
        details={"key": key},
    )
    session.commit()
    session.refresh(row)
    return row


def _role_read(session, role: Role) -> RoleRead:
    codes = list(
        session.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role.id)
            .order_by(Permission.code)
        )
    )
    return RoleRead(
        id=role.id,
        organization_id=role.organization_id,
        name=role.name,
        description=role.description,
        system=role.system,
        permission_codes=codes,
    )


def _service_account(session, context: AuthContext, account_id: int) -> ServiceAccount:
    row = session.scalar(
        select(ServiceAccount).where(
            ServiceAccount.id == account_id,
            ServiceAccount.organization_id == context.organization_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="service account not found")
    return row
