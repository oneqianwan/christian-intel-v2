from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from dependencies.auth import require_authenticated_user
from dependencies.tenant_context import TenantRequestContext, resolve_tenant_request_context
from models.auth import User
from models.database import RequestTrace, get_db
from schemas.watch_alert import ApiErrorResponse
from services import tenant_scope, tenant_service

router = APIRouter()

_SENSITIVE_KEY_MARKERS = ("password", "token", "session", "secret", "request_body", "authorization")
_SENSITIVE_VALUE_MARKERS = ("password", "token", "session", "secret")


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _has_explicit_tenant_selector(request: Request) -> bool:
    return any(
        str(value or "").strip()
        for value in (
            request.headers.get("X-Tenant-ID"),
            request.headers.get("X-Tenant-Slug"),
            request.query_params.get("tenant_id"),
            request.query_params.get("tenant_public_id"),
            request.query_params.get("tenant_slug"),
        )
    )


def _redact_trace_payload(value: Any):
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip().lower()
            if any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
                continue
            sanitized[key] = _redact_trace_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_redact_trace_payload(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS):
            return "[REDACTED]"
    return value


def _safe_event_dict(trace: RequestTrace) -> dict[str, Any]:
    event_data = trace.event_data if isinstance(trace.event_data, dict) else {}
    return _redact_trace_payload(event_data)


def _resolve_diagnostics_tenant_context(
    *,
    request: Request,
    current_user: User,
    db: Session,
) -> TenantRequestContext | None:
    is_super_admin = tenant_service.is_platform_super_admin(current_user)
    if is_super_admin and not _has_explicit_tenant_selector(request):
        return None
    context = resolve_tenant_request_context(request=request, user=current_user, db=db, fail_closed=True)
    if context is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "TENANT_REQUIRED", "Tenant required")
    return context


@router.get("/diagnostics/request/{request_id}")
def get_request_diagnostics(
    request_id: str,
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    context = _resolve_diagnostics_tenant_context(request=request, current_user=current_user, db=db)
    trace_query = db.query(RequestTrace).filter(RequestTrace.request_id == request_id)
    if context is None:
        if not tenant_service.is_platform_super_admin(current_user):
            _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")
        trace_query = trace_query.filter(RequestTrace.tenant_id.is_(None))
    else:
        trace_query = tenant_scope.filter_by_tenant(trace_query, RequestTrace, str(context.tenant.id))
    traces = trace_query.order_by(RequestTrace.created_at).all()

    if not traces:
        return {"request_id": request_id, "found": False, "message": "未找到该请求的追踪记录"}

    return {
        "request_id": request_id,
        "found": True,
        "trace_count": len(traces),
        "total_duration_ms": _calc_duration(traces),
        "events": [
            {
                "seq": i + 1,
                "time": t.created_at.isoformat(),
                "type": t.event_type,
                "data": _safe_event_dict(t),
            }
            for i, t in enumerate(traces)
        ],
        "summary": {
            "route": next((_safe_event_dict(t) for t in traces if t.event_type == "route_decided"), None),
            "knowledge_hits": next(
                (_safe_event_dict(t).get("results_count", 0) for t in traces if t.event_type == "knowledge_queried"),
                0,
            ),
            "delivery_status": next(
                (_safe_event_dict(t).get("status") for t in traces if t.event_type == "delivery_emitted"),
                None,
            ),
        },
    }


def _calc_duration(traces):
    if len(traces) < 2:
        return 0
    first = traces[0].created_at
    last = traces[-1].created_at
    return int((last - first).total_seconds() * 1000)
