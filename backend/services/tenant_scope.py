from __future__ import annotations

from dataclasses import dataclass

from models.auth import Tenant, TenantMembership, User
from services import tenant_service


@dataclass(frozen=True)
class TenantScopeError(Exception):
    status_code: int
    error_code: str
    message: str


def _require_model_tenant_field(model) -> None:
    if not hasattr(model, "tenant_id"):
        raise TenantScopeError(400, "TENANT_SCOPE_UNSUPPORTED_MODEL", "Model does not support tenant scope")


def _normalize_current_tenant_id(current_tenant: Tenant | str | None) -> str:
    if current_tenant is None:
        raise TenantScopeError(403, "TENANT_REQUIRED", "Tenant required")
    if isinstance(current_tenant, str):
        normalized = str(current_tenant).strip()
        if not normalized:
            raise TenantScopeError(403, "TENANT_REQUIRED", "Tenant required")
        return normalized
    if not tenant_service.is_tenant_active(current_tenant):
        raise TenantScopeError(403, "TENANT_DISABLED", "Tenant is disabled")
    return str(current_tenant.id)


def assert_same_tenant(record_tenant_id: str | None, current_tenant: Tenant | str | None) -> bool:
    current_tenant_id = _normalize_current_tenant_id(current_tenant)
    if str(record_tenant_id or "").strip() != current_tenant_id:
        raise TenantScopeError(403, "TENANT_SCOPE_FORBIDDEN", "Cross-tenant access forbidden")
    return True


def filter_by_tenant(query, model, tenant_id: str):
    _require_model_tenant_field(model)
    return query.filter(getattr(model, "tenant_id") == str(tenant_id))


def ensure_tenant_id_for_create(payload: dict, current_tenant: Tenant | str | None) -> dict:
    current_tenant_id = _normalize_current_tenant_id(current_tenant)
    data = dict(payload or {})
    tenant_id = str(data.get("tenant_id") or "").strip()
    if tenant_id and tenant_id != current_tenant_id:
        raise TenantScopeError(403, "TENANT_SCOPE_FORBIDDEN", "Cross-tenant create forbidden")
    data["tenant_id"] = current_tenant_id
    return data


def require_record_tenant(record, current_tenant: Tenant | str | None) -> bool:
    if not hasattr(record, "tenant_id"):
        raise TenantScopeError(400, "TENANT_SCOPE_UNSUPPORTED_MODEL", "Model does not support tenant scope")
    return assert_same_tenant(getattr(record, "tenant_id", None), current_tenant)


def build_tenant_scope_metadata(
    current_user: User,
    current_tenant: Tenant,
    membership: TenantMembership | None,
) -> dict[str, str | None]:
    if current_tenant is None or not tenant_service.is_tenant_active(current_tenant):
        raise TenantScopeError(403, "TENANT_DISABLED", "Tenant is disabled")
    return {
        "user_id": str(getattr(current_user, "id", "") or ""),
        "user_public_id": str(getattr(current_user, "public_id", "") or ""),
        "tenant_id": str(getattr(current_tenant, "id", "") or ""),
        "tenant_public_id": str(getattr(current_tenant, "public_id", "") or ""),
        "tenant_slug": str(getattr(current_tenant, "slug", "") or ""),
        "global_role": tenant_service.normalize_user_role(getattr(current_user, "role", None)),
        "tenant_role": tenant_service.resolve_tenant_role(user=current_user, membership=membership),
    }
