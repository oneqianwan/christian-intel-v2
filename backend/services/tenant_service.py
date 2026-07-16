from __future__ import annotations

import re
import uuid

from dataclasses import dataclass
from datetime import datetime

import config
from models.auth import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_PUBLIC_ID,
    Tenant,
    TenantMembership,
    User,
)

TENANT_STATUS_VALUES = frozenset({"active", "disabled", "archived"})
TENANT_MEMBERSHIP_ROLE_VALUES = frozenset({"tenant_admin", "analyst", "viewer"})
TENANT_MEMBERSHIP_STATUS_VALUES = frozenset({"active", "disabled", "pending"})


@dataclass
class TenantError(Exception):
    status_code: int
    error_code: str
    message: str


def _utcnow() -> datetime:
    return datetime.utcnow()


def normalize_tenant_slug(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    if not normalized:
        raise TenantError(422, "INVALID_TENANT_SLUG", "Invalid tenant slug")
    return normalized


def normalize_tenant_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in TENANT_STATUS_VALUES:
        raise TenantError(422, "INVALID_TENANT_STATUS", "Invalid tenant status")
    return normalized


def normalize_membership_role(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in TENANT_MEMBERSHIP_ROLE_VALUES:
        raise TenantError(422, "INVALID_TENANT_ROLE", "Invalid tenant membership role")
    return normalized


def normalize_membership_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in TENANT_MEMBERSHIP_STATUS_VALUES:
        raise TenantError(422, "INVALID_TENANT_MEMBERSHIP_STATUS", "Invalid tenant membership status")
    return normalized


def default_tenant_slug() -> str:
    return normalize_tenant_slug(getattr(config.settings, "TENANT_DEFAULT_SLUG", "default"))


def default_tenant_name() -> str:
    value = str(getattr(config.settings, "TENANT_DEFAULT_NAME", "Platform Default") or "").strip()
    return value or "Platform Default"


def map_user_role_to_membership_role(user_role: str | None) -> str:
    normalized = str(user_role or "").strip().lower()
    if normalized in {"admin", "super_admin"}:
        return "tenant_admin"
    if normalized == "analyst":
        return "analyst"
    return "viewer"


def get_tenant_by_public_id(db, *, tenant_public_id: str) -> Tenant | None:
    return (
        db.query(Tenant)
        .filter(
            Tenant.public_id == str(tenant_public_id),
            Tenant.deleted_at.is_(None),
        )
        .first()
    )


def get_tenant_by_slug(db, *, slug: str) -> Tenant | None:
    normalized_slug = normalize_tenant_slug(slug)
    return (
        db.query(Tenant)
        .filter(
            Tenant.slug == normalized_slug,
            Tenant.deleted_at.is_(None),
        )
        .first()
    )


def ensure_default_tenant(db) -> Tenant:
    tenant = (
        db.query(Tenant)
        .filter(
            Tenant.id == DEFAULT_TENANT_ID,
            Tenant.deleted_at.is_(None),
        )
        .first()
    )
    if tenant is not None:
        changed = False
        if tenant.public_id != DEFAULT_TENANT_PUBLIC_ID:
            tenant.public_id = DEFAULT_TENANT_PUBLIC_ID
            changed = True
        normalized_slug = default_tenant_slug()
        if tenant.slug != normalized_slug:
            tenant.slug = normalized_slug
            changed = True
        normalized_name = default_tenant_name()
        if tenant.name != normalized_name:
            tenant.name = normalized_name
            changed = True
        if tenant.status != "active":
            tenant.status = "active"
            changed = True
        if changed:
            tenant.updated_at = _utcnow()
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        return tenant

    tenant = (
        db.query(Tenant)
        .filter(
            Tenant.slug == default_tenant_slug(),
            Tenant.deleted_at.is_(None),
        )
        .first()
    )
    if tenant is not None:
        if tenant.id != DEFAULT_TENANT_ID:
            tenant.id = DEFAULT_TENANT_ID
        if tenant.public_id != DEFAULT_TENANT_PUBLIC_ID:
            tenant.public_id = DEFAULT_TENANT_PUBLIC_ID
        tenant.status = "active"
        tenant.updated_at = _utcnow()
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return tenant

    tenant = Tenant(
        id=DEFAULT_TENANT_ID,
        public_id=DEFAULT_TENANT_PUBLIC_ID,
        name=default_tenant_name(),
        slug=default_tenant_slug(),
        status="active",
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def create_tenant(
    db,
    *,
    name: str,
    slug: str,
    status: str = "active",
) -> Tenant:
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise TenantError(422, "INVALID_TENANT_NAME", "Tenant name required")
    normalized_slug = normalize_tenant_slug(slug)
    normalized_status = normalize_tenant_status(status)
    existing = get_tenant_by_slug(db, slug=normalized_slug)
    if existing is not None:
        raise TenantError(409, "TENANT_SLUG_ALREADY_EXISTS", "Tenant slug already exists")

    tenant = Tenant(
        id=str(uuid.uuid4()),
        public_id=str(uuid.uuid4()),
        name=normalized_name,
        slug=normalized_slug,
        status=normalized_status,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def get_or_create_membership(
    db,
    *,
    tenant: Tenant,
    user: User,
    role: str,
    status: str = "active",
    created_by_user_id: str | None = None,
) -> TenantMembership:
    normalized_role = normalize_membership_role(role)
    normalized_status = normalize_membership_status(status)
    membership = (
        db.query(TenantMembership)
        .filter(
            TenantMembership.tenant_id == str(tenant.id),
            TenantMembership.user_id == str(user.id),
            TenantMembership.deleted_at.is_(None),
        )
        .order_by(TenantMembership.created_at.asc())
        .first()
    )
    if membership is not None:
        membership.role = normalized_role
        membership.status = normalized_status
        membership.created_by_user_id = str(created_by_user_id) if created_by_user_id else membership.created_by_user_id
        membership.updated_at = _utcnow()
        db.add(membership)
        db.flush()
        return membership

    membership = TenantMembership(
        id=str(uuid.uuid4()),
        public_id=str(uuid.uuid4()),
        tenant_id=str(tenant.id),
        user_id=str(user.id),
        role=normalized_role,
        status=normalized_status,
        created_by_user_id=str(created_by_user_id) if created_by_user_id else None,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(membership)
    db.flush()
    return membership


def soft_delete_membership(db, *, membership: TenantMembership) -> TenantMembership:
    membership.deleted_at = _utcnow()
    membership.updated_at = _utcnow()
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def resolve_tenant_for_user_creation(
    db,
    *,
    actor: User,
    tenant_public_id: str | None,
) -> Tenant:
    default_tenant = ensure_default_tenant(db)
    if not str(tenant_public_id or "").strip():
        return default_tenant

    tenant = get_tenant_by_public_id(db, tenant_public_id=str(tenant_public_id).strip())
    if tenant is None:
        raise TenantError(404, "TENANT_NOT_FOUND", "Tenant not found")

    actor_role = str(getattr(actor, "role", "") or "").strip().lower()
    if actor_role == "super_admin":
        return tenant

    if str(getattr(actor, "default_tenant_id", "") or "") != str(tenant.id):
        raise TenantError(403, "ROLE_FORBIDDEN", "Insufficient permissions")
    return tenant


def ensure_user_default_tenant_membership(
    db,
    *,
    user: User,
    created_by_user_id: str | None = None,
) -> TenantMembership:
    tenant = ensure_default_tenant(db)
    if not getattr(user, "default_tenant_id", None):
        user.default_tenant_id = str(tenant.id)
        db.add(user)
        db.flush()
    return get_or_create_membership(
        db,
        tenant=tenant,
        user=user,
        role=map_user_role_to_membership_role(getattr(user, "role", None)),
        status="active" if str(getattr(user, "status", "") or "").strip().lower() == "active" else "pending",
        created_by_user_id=created_by_user_id,
    )


def ensure_default_tenant_foundation(db) -> dict[str, int | str]:
    tenant = ensure_default_tenant(db)
    backfilled_users = (
        db.query(User)
        .filter(User.default_tenant_id.is_(None))
        .update({"default_tenant_id": str(tenant.id)}, synchronize_session=False)
    )
    db.flush()

    membership_count = 0
    users = db.query(User).all()
    for user in users:
        active_membership = (
            db.query(TenantMembership)
            .filter(
                TenantMembership.tenant_id == str(user.default_tenant_id or tenant.id),
                TenantMembership.user_id == str(user.id),
                TenantMembership.deleted_at.is_(None),
                TenantMembership.status == "active",
            )
            .first()
        )
        if active_membership is not None:
            continue
        get_or_create_membership(
            db,
            tenant=tenant if str(user.default_tenant_id or "") == str(tenant.id) else db.query(Tenant).filter(Tenant.id == user.default_tenant_id).first() or tenant,
            user=user,
            role=map_user_role_to_membership_role(getattr(user, "role", None)),
            status="active" if str(getattr(user, "status", "") or "").strip().lower() == "active" else "pending",
            created_by_user_id=None,
        )
        membership_count += 1

    db.commit()
    return {
        "default_tenant_id": str(tenant.id),
        "backfilled_users": int(backfilled_users or 0),
        "backfilled_memberships": int(membership_count),
    }


def assert_user_default_tenant_active(db, *, user: User) -> Tenant | None:
    tenant_id = str(getattr(user, "default_tenant_id", "") or "").strip()
    if not tenant_id:
        raise TenantError(403, "TENANT_REQUIRED", "Tenant required")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.deleted_at.is_(None)).first()
    if tenant is None:
        raise TenantError(403, "TENANT_NOT_FOUND", "Tenant not found")
    if str(tenant.status or "").strip().lower() != "active":
        raise TenantError(403, "TENANT_DISABLED", "Tenant is disabled")
    return tenant
