from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from agent_quality_harness.core.config import Settings
from agent_quality_harness.domain.models import (
    ApiKey,
    AuditLog,
    AuthSession,
    Membership,
    MembershipRole,
    Organization,
    Permission,
    RolePermission,
    ServiceAccount,
    User,
)

PASSWORD_HASHER = PasswordHasher(type=Type.ID)

PERMISSIONS: dict[str, str] = {
    "target:read": "Read targets",
    "target:manage": "Manage targets",
    "dataset:read": "Read datasets",
    "dataset:manage": "Manage datasets",
    "run:read": "Read evaluation runs",
    "run:execute": "Execute and control evaluation runs",
    "gate:read": "Read release gates",
    "gate:manage": "Manage release gate policies",
    "skill:read": "Read Agent Skills and scans",
    "skill:scan": "Execute Agent Skill security scans",
    "skill:manage": "Manage Agent Skill versions and attachments",
    "policy:read": "Read Policy-as-Code bundles and evaluations",
    "policy:manage": "Manage Policy-as-Code bundles",
    "usage:read": "Read usage and cost",
    "trace:read": "Read trace and failure data",
    "member:manage": "Manage organization members",
    "role:manage": "Manage roles and permissions",
    "service_account:manage": "Manage service accounts and API keys",
    "audit:read": "Read audit logs",
    "setting:manage": "Manage organization settings",
    "demo:bootstrap": "Create demo fixtures",
}

SYSTEM_ROLES: dict[str, set[str]] = {
    "Administrator": set(PERMISSIONS),
    "Evaluator": {
        "target:read",
        "dataset:read",
        "run:read",
        "run:execute",
        "gate:read",
        "skill:read",
        "skill:scan",
        "policy:read",
        "usage:read",
        "trace:read",
    },
    "Viewer": {
        "target:read",
        "dataset:read",
        "run:read",
        "gate:read",
        "skill:read",
        "policy:read",
        "usage:read",
        "trace:read",
    },
}


@dataclass(frozen=True, slots=True)
class AuthContext:
    actor_type: str
    actor_id: int
    user_id: int | None
    organization_id: int | None
    platform_admin: bool
    permissions: frozenset[str]


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def create_access_token(user: User, settings: Settings) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_minutes)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "typ": "access",
            "iat": now,
            "exp": expires_at,
            "jti": secrets.token_hex(16),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> int:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("unexpected token type")
    return int(payload["sub"])


def create_refresh_session(
    session: Session,
    user: User,
    settings: Settings,
    *,
    ip_address: str | None,
    user_agent: str | None,
    family_id: str | None = None,
) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(48)
    row = AuthSession(
        user_id=user.id,
        family_id=family_id or secrets.token_hex(16),
        refresh_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_session_days),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(row)
    session.flush()
    return token, row


def rotate_refresh_session(
    session: Session,
    token: str,
    settings: Settings,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[User, str, AuthSession]:
    now = datetime.now(UTC)
    row = session.scalar(select(AuthSession).where(AuthSession.refresh_hash == _token_hash(token)))
    if row is None:
        raise PermissionError("invalid refresh session")
    if row.revoked_at is not None or row.replaced_by_session_id is not None:
        session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == row.family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        session.commit()
        raise PermissionError("refresh session reuse detected")
    if row.expires_at <= now:
        row.revoked_at = now
        session.commit()
        raise PermissionError("refresh session expired")
    user = session.get(User, row.user_id)
    if user is None or not user.active:
        row.revoked_at = now
        session.commit()
        raise PermissionError("user inactive")
    new_token, replacement = create_refresh_session(
        session,
        user,
        settings,
        ip_address=ip_address,
        user_agent=user_agent,
        family_id=row.family_id,
    )
    row.last_used_at = now
    row.revoked_at = now
    row.replaced_by_session_id = replacement.id
    session.flush()
    return user, new_token, replacement


def revoke_refresh_session(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.scalar(select(AuthSession).where(AuthSession.refresh_hash == _token_hash(token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def create_api_key(
    session: Session, service_account: ServiceAccount, name: str
) -> tuple[str, ApiKey]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    plaintext = f"aqh_{prefix}_{secret}"
    row = ApiKey(
        service_account_id=service_account.id,
        name=name,
        prefix=f"aqh_{prefix}",
        key_hash=_token_hash(plaintext),
    )
    session.add(row)
    session.flush()
    return plaintext, row


def authenticate_bearer(session: Session, token: str, settings: Settings) -> AuthContext:
    user_id = decode_access_token(token, settings)
    user = session.get(User, user_id)
    if user is None or not user.active:
        raise PermissionError("user inactive")
    return AuthContext("user", user.id, user.id, None, user.platform_admin, frozenset())


def authenticate_api_key(session: Session, token: str) -> AuthContext:
    now = datetime.now(UTC)
    row = session.scalar(select(ApiKey).where(ApiKey.key_hash == _token_hash(token)))
    if row is None or row.revoked_at is not None:
        raise PermissionError("invalid API key")
    if row.expires_at is not None and row.expires_at <= now:
        raise PermissionError("API key expired")
    account = session.get(ServiceAccount, row.service_account_id)
    if account is None or not account.active:
        raise PermissionError("service account inactive")
    row.last_used_at = now
    session.commit()
    return AuthContext(
        "service_account",
        account.id,
        None,
        account.organization_id,
        False,
        frozenset(PERMISSIONS),
    )


def bind_organization(session: Session, context: AuthContext, organization_id: int) -> AuthContext:
    organization = session.get(Organization, organization_id)
    if organization is None or not organization.active:
        raise LookupError("organization not found")
    if context.actor_type == "service_account":
        if context.organization_id != organization_id:
            raise LookupError("organization not found")
        return context
    if context.platform_admin:
        return AuthContext(
            context.actor_type,
            context.actor_id,
            context.user_id,
            organization_id,
            True,
            frozenset(PERMISSIONS),
        )
    membership = session.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == context.user_id,
            Membership.active.is_(True),
        )
    )
    if membership is None:
        raise LookupError("organization not found")
    permissions = frozenset(
        session.scalars(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .join(MembershipRole, MembershipRole.role_id == RolePermission.role_id)
            .where(MembershipRole.membership_id == membership.id)
        )
    )
    return AuthContext(
        context.actor_type,
        context.actor_id,
        context.user_id,
        organization_id,
        False,
        permissions,
    )


def user_organizations(session: Session, user: User) -> list[dict[str, Any]]:
    if user.platform_admin:
        organizations = session.scalars(
            select(Organization).where(Organization.active.is_(True)).order_by(Organization.name)
        )
    else:
        organizations = session.scalars(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user.id, Membership.active.is_(True))
            .order_by(Organization.name)
        )
    return [
        {"id": row.id, "slug": row.slug, "name": row.name, "active": row.active}
        for row in organizations
    ]


def audit(
    session: Session,
    *,
    action: str,
    outcome: str,
    context: AuthContext | None = None,
    organization_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | int | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    row = AuditLog(
        organization_id=organization_id or (None if context is None else context.organization_id),
        actor_type="anonymous" if context is None else context.actor_type,
        actor_id=None if context is None else context.actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=None if resource_id is None else str(resource_id),
        outcome=outcome,
        details=_redact(details or {}),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(row)
    return row


def _redact(value: Any) -> Any:
    sensitive = {"password", "token", "secret", "api_key", "authorization", "auth_ref"}
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(fragment in key.lower() for fragment in sensitive)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
