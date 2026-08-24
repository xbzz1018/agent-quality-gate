from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from agent_quality_harness.domain.models import AuthSession, User
from agent_quality_harness.security import (
    audit,
    bind_organization,
    create_access_token,
    create_refresh_session,
    revoke_refresh_session,
    rotate_refresh_session,
    user_organizations,
    verify_password,
)

from .dependencies import AuthDependency, SessionDependency

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)


class OrganizationSummary(BaseModel):
    id: int
    slug: str
    name: str
    active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    organizations: list[OrganizationSummary]


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None
    display_name: str
    platform_admin: bool
    organizations: list[OrganizationSummary]
    permissions: list[str]


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    ip_address: str | None
    user_agent: str | None


def _client_context(request: Request) -> tuple[str | None, str | None]:
    ip_address = None if request.client is None else request.client.host
    return ip_address, request.headers.get("user-agent")


def _set_refresh_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.refresh_cookie_name,
        token,
        max_age=settings.refresh_session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="strict",
        path=f"{settings.api_prefix}/auth",
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, response: Response, session: SessionDependency):
    user = session.scalar(select(User).where(User.username == payload.username))
    ip_address, user_agent = _client_context(request)
    if user is None or not user.active or not verify_password(user.password_hash, payload.password):
        audit(
            session,
            action="auth.login",
            outcome="failure",
            details={"username": payload.username},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.commit()
        raise HTTPException(status_code=401, detail="invalid username or password")
    access_token, expires_at = create_access_token(user, request.app.state.settings)
    refresh_token, _ = create_refresh_session(
        session,
        user,
        request.app.state.settings,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    user.last_login_at = datetime.now(UTC)
    audit(
        session,
        action="auth.login",
        outcome="success",
        context=None,
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.commit()
    _set_refresh_cookie(response, request, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        organizations=user_organizations(session, user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, session: SessionDependency):
    settings = request.app.state.settings
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="refresh session required")
    ip_address, user_agent = _client_context(request)
    try:
        user, refresh_token, _ = rotate_refresh_session(
            session,
            token,
            settings,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    access_token, expires_at = create_access_token(user, settings)
    audit(
        session,
        action="auth.refresh",
        outcome="success",
        resource_type="user",
        resource_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.commit()
    _set_refresh_cookie(response, request, refresh_token)
    return TokenResponse(
        access_token=access_token,
        expires_at=expires_at,
        organizations=user_organizations(session, user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: SessionDependency):
    settings = request.app.state.settings
    revoke_refresh_session(session, request.cookies.get(settings.refresh_cookie_name))
    audit(session, action="auth.logout", outcome="success")
    session.commit()
    response.delete_cookie(settings.refresh_cookie_name, path=f"{settings.api_prefix}/auth")


@router.get("/me", response_model=MeResponse)
def me(request: Request, context: AuthDependency, session: SessionDependency):
    if context.user_id is None:
        raise HTTPException(status_code=403, detail="interactive user required")
    user = session.get(User, context.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user not found")
    permissions: list[str] = []
    organization_header = request.headers.get("x-organization-id")
    if organization_header:
        try:
            bound = bind_organization(session, context, int(organization_header))
            permissions = sorted(bound.permissions)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="organization not found") from exc
    return MeResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        platform_admin=user.platform_admin,
        organizations=user_organizations(session, user),
        permissions=permissions,
    )


@router.get("/sessions", response_model=list[SessionRead])
def sessions(context: AuthDependency, session: SessionDependency):
    if context.user_id is None:
        raise HTTPException(status_code=403, detail="interactive user required")
    return list(
        session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == context.user_id)
            .order_by(AuthSession.id.desc())
            .limit(100)
        )
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: int, context: AuthDependency, session: SessionDependency):
    if context.user_id is None:
        raise HTTPException(status_code=403, detail="interactive user required")
    row = session.scalar(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == context.user_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    audit(
        session,
        action="auth.session.revoke",
        outcome="success",
        context=context,
        resource_type="auth_session",
        resource_id=row.id,
    )
    session.commit()
