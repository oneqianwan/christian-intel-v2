from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from dependencies.auth import get_current_user, require_super_admin
from models.auth import Tenant, TenantMembership, User
from models.database import get_db
from schemas.watch_alert import ApiErrorResponse
from services import tenant_service


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _tenant_selectors(request: Request) -> tuple[str | None, str | None]:
    tenant_public_id = (
        request.headers.get("X-Tenant-ID")
        or request.query_params.get("tenant_id")
        or request.query_params.get("tenant_public_id")
    )
    tenant_slug = request.headers.get("X-Tenant-Slug") or request.query_params.get("tenant_slug")
    return (
        str(tenant_public_id).strip() if tenant_public_id else None,
        str(tenant_slug).strip() if tenant_slug else None,
    )


@dataclass(frozen=True)
class TenantRequestContext:
    user: User
    tenant: Tenant
    membership: TenantMembership | None
    global_role: str
    tenant_role: str | None


def resolve_tenant_request_context(
    *,
    request: Request,
    user: User,
    db: Session,
    fail_closed: bool = True,
) -> TenantRequestContext | None:
    tenant_public_id, tenant_slug = _tenant_selectors(request)
    try:
        tenant = tenant_service.resolve_active_tenant(
            db,
            user=user,
            tenant_public_id=tenant_public_id,
            tenant_slug=tenant_slug,
            fail_closed=fail_closed,
        )
        if tenant is None:
            return None
        membership = tenant_service.resolve_current_membership(
            db,
            user=user,
            tenant=tenant,
            fail_closed=fail_closed,
        )
        return TenantRequestContext(
            user=user,
            tenant=tenant,
            membership=membership,
            global_role=str(getattr(user, "role", "") or "").strip().lower(),
            tenant_role=tenant_service.resolve_tenant_role(user=user, membership=membership),
        )
    except tenant_service.TenantError as exc:
        if not fail_closed:
            return None
        _raise_api_error(int(exc.status_code), exc.error_code, exc.message)
    return None


def get_current_tenant_context(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantRequestContext:
    context = resolve_tenant_request_context(request=request, user=user, db=db, fail_closed=True)
    if context is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "TENANT_REQUIRED", "Tenant required")
    return context


def get_current_tenant(context: TenantRequestContext = Depends(get_current_tenant_context)) -> Tenant:
    return context.tenant


def get_current_membership(context: TenantRequestContext = Depends(get_current_tenant_context)) -> TenantMembership | None:
    return context.membership


def require_tenant_member(context: TenantRequestContext = Depends(get_current_tenant_context)) -> TenantRequestContext:
    if context.membership is None and not tenant_service.is_platform_super_admin(context.user):
        _raise_api_error(status.HTTP_403_FORBIDDEN, "TENANT_MEMBERSHIP_REQUIRED", "Active tenant membership required")
    return context


def require_tenant_role(*allowed_roles: str):
    normalized_allowed = {str(role or "").strip().lower() for role in allowed_roles if str(role or "").strip()}
    if not normalized_allowed:
        raise ValueError("At least one tenant role is required")

    def dependency(context: TenantRequestContext = Depends(get_current_tenant_context)) -> TenantRequestContext:
        if tenant_service.is_platform_super_admin(context.user):
            return context
        if str(context.tenant_role or "").strip().lower() not in normalized_allowed:
            _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")
        return context

    return dependency


def require_tenant_admin(context: TenantRequestContext = Depends(require_tenant_role("tenant_admin"))) -> TenantRequestContext:
    return context


def require_platform_super_admin(user: User = Depends(require_super_admin)) -> User:
    return user
