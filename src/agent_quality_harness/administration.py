from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_quality_harness.domain.models import (
    Membership,
    MembershipRole,
    Organization,
    Permission,
    Role,
    RolePermission,
    User,
)
from agent_quality_harness.security import PERMISSIONS, SYSTEM_ROLES, hash_password


def provision_organization(session: Session, *, slug: str, name: str) -> Organization:
    organization = Organization(slug=slug, name=name, active=True)
    session.add(organization)
    session.flush()
    permission_by_code = ensure_permission_catalog(session)
    for role_name, codes in SYSTEM_ROLES.items():
        role = Role(
            organization_id=organization.id,
            name=role_name,
            description=f"Built-in {role_name.lower()} role",
            system=True,
        )
        session.add(role)
        session.flush()
        session.add_all(
            RolePermission(role_id=role.id, permission_id=permission_by_code[code].id)
            for code in sorted(codes)
        )
    return organization


def ensure_permission_catalog(session: Session) -> dict[str, Permission]:
    existing = {row.code: row for row in session.scalars(select(Permission))}
    for code, name in PERMISSIONS.items():
        if code not in existing:
            row = Permission(code=code, name=name, description="")
            session.add(row)
            session.flush()
            existing[code] = row
    return existing


def add_membership(
    session: Session,
    *,
    user: User,
    organization: Organization,
    role_names: list[str],
) -> Membership:
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        active=True,
    )
    session.add(membership)
    session.flush()
    roles = list(
        session.scalars(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.name.in_(role_names),
            )
        )
    )
    if len(roles) != len(set(role_names)):
        raise LookupError("role not found")
    session.add_all(MembershipRole(membership_id=membership.id, role_id=role.id) for role in roles)
    return membership


def bootstrap_platform_admin(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    email: str | None,
) -> User:
    if session.scalar(select(User).where(User.username == username)) is not None:
        raise ValueError("username already exists")
    organization = session.scalar(select(Organization).where(Organization.slug == "default"))
    if organization is None:
        organization = provision_organization(
            session,
            slug="default",
            name="Default Organization",
        )
    else:
        ensure_permission_catalog(session)
        administrator = session.scalar(
            select(Role).where(
                Role.organization_id == organization.id,
                Role.name == "Administrator",
            )
        )
        if administrator is None:
            permission_by_code = ensure_permission_catalog(session)
            administrator = Role(
                organization_id=organization.id,
                name="Administrator",
                description="Built-in administrator role",
                system=True,
            )
            session.add(administrator)
            session.flush()
            session.add_all(
                RolePermission(role_id=administrator.id, permission_id=row.id)
                for row in permission_by_code.values()
            )
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        active=True,
        platform_admin=True,
    )
    session.add(user)
    session.flush()
    add_membership(
        session,
        user=user,
        organization=organization,
        role_names=["Administrator"],
    )
    session.commit()
    session.refresh(user)
    return user
