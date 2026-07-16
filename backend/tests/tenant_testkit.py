from __future__ import annotations

import uuid

from services import tenant_service


def unique_tenant_slug(prefix: str = "tenant") -> str:
    return f"{str(prefix or 'tenant').strip().lower()}-{uuid.uuid4().hex}"


def ensure_default_tenant(runtime):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        tenant = tenant_service.ensure_default_tenant(db)
        db.refresh(tenant)
        return tenant
    finally:
        db.close()


def create_tenant(runtime, *, name: str, slug: str, status: str = "active"):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        tenant = tenant_service.create_tenant(db, name=name, slug=slug, status=status)
        db.refresh(tenant)
        return tenant
    finally:
        db.close()


def create_membership(
    runtime,
    *,
    tenant,
    user,
    role: str,
    status: str = "active",
    created_by_user_id: str | None = None,
):
    database = runtime["database"]
    db = database.SessionLocal()
    try:
        tenant_row = db.query(runtime["auth_models"].Tenant).filter(runtime["auth_models"].Tenant.id == tenant.id).one()
        user_row = db.query(runtime["auth_models"].User).filter(runtime["auth_models"].User.id == user.id).one()
        membership = tenant_service.get_or_create_membership(
            db,
            tenant=tenant_row,
            user=user_row,
            role=role,
            status=status,
            created_by_user_id=created_by_user_id,
        )
        db.commit()
        db.refresh(membership)
        return membership
    finally:
        db.close()
