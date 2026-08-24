from collections.abc import Callable, Iterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from agent_quality_harness.security import (
    AuthContext,
    authenticate_api_key,
    authenticate_bearer,
    bind_organization,
)


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def require_authenticated(request: Request, session: SessionDependency) -> AuthContext:
    authorization = request.headers.get("authorization", "")
    api_key = request.headers.get("x-api-key")
    try:
        if api_key:
            context = authenticate_api_key(session, api_key)
        elif authorization.lower().startswith("bearer "):
            context = authenticate_bearer(
                session,
                authorization.split(" ", 1)[1],
                request.app.state.settings,
            )
        else:
            raise PermissionError("authentication required")
    except (PermissionError, ValueError, jwt.PyJWTError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    request.state.auth_context = context
    return context


AuthDependency = Annotated[AuthContext, Depends(require_authenticated)]


def require_organization(
    request: Request,
    session: SessionDependency,
    context: AuthDependency,
) -> AuthContext:
    header = request.headers.get("x-organization-id")
    organization_id = context.organization_id
    if header is not None:
        try:
            requested = int(header)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid X-Organization-ID") from exc
        if organization_id is not None and requested != organization_id:
            raise HTTPException(status_code=404, detail="organization not found")
        organization_id = requested
    if organization_id is None:
        raise HTTPException(status_code=400, detail="X-Organization-ID is required")
    try:
        bound = bind_organization(session, context, organization_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="organization not found") from exc
    request.state.auth_context = bound
    return bound


OrganizationDependency = Annotated[AuthContext, Depends(require_organization)]


def require_permission(code: str) -> Callable[..., AuthContext]:
    def dependency(context: OrganizationDependency) -> AuthContext:
        if not context.platform_admin and code not in context.permissions:
            raise HTTPException(status_code=403, detail=f"missing permission: {code}")
        return context

    return dependency


def current_context(request: Request) -> AuthContext:
    return request.state.auth_context


def current_organization_id(request: Request) -> int:
    context = current_context(request)
    if context.organization_id is None:
        raise RuntimeError("organization context is not bound")
    return context.organization_id
