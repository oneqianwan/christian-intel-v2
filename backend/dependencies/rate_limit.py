from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, Request, status

from schemas.watch_alert import ApiErrorResponse
from services.monitoring_events import record_rate_limit_trip
from services.rate_limiter import RateLimitDecision, get_default_rate_limiter


def get_rate_limiter():
    return get_default_rate_limiter()


def get_client_ip(request: Request) -> str:
    forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        first_ip = str(forwarded.split(",", 1)[0] or "").strip()
        if first_ip:
            return first_ip
    host = getattr(getattr(request, "client", None), "host", None)
    if host:
        normalized = str(host).strip()
        if normalized:
            return normalized
    return "unknown"


def build_rate_limit_key(
    *,
    ip: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    route: str | None = None,
    method: str | None = None,
    resource_id: str | None = None,
    normalized_email: str | None = None,
    payload_hash: str | None = None,
) -> str:
    parts = {
        "ip": str(ip or "").strip() or "unknown",
        "user_id": str(user_id or "").strip() or "anonymous",
        "tenant_id": str(tenant_id or "").strip() or "no-tenant",
        "route": str(route or "").strip() or "unknown-route",
        "method": str(method or "").strip().upper() or "UNKNOWN",
        "resource_id": str(resource_id or "").strip() or "no-resource",
        "normalized_email": str(normalized_email or "").strip().lower() or "anonymous",
        "payload_hash": str(payload_hash or "").strip() or "",
    }
    return "|".join(
        [
            f"ip={parts['ip']}",
            f"user_id={parts['user_id']}",
            f"tenant_id={parts['tenant_id']}",
            f"route={parts['route']}",
            f"method={parts['method']}",
            f"resource_id={parts['resource_id']}",
            f"normalized_email={parts['normalized_email']}",
            f"payload_hash={parts['payload_hash']}",
        ]
    )


def _raise_rate_limit(
    *,
    decision: RateLimitDecision,
    error_code: str,
    message: str,
) -> None:
    record_rate_limit_trip(rule_name=decision.rule_name, error_code=error_code)
    headers = {
        "Retry-After": str(int(decision.retry_after_seconds)),
        "X-RateLimit-Limit": str(int(decision.limit)),
        "X-RateLimit-Remaining": str(int(decision.remaining)),
        "X-RateLimit-Reset": str(int(decision.reset_after_seconds)),
    }
    detail = ApiErrorResponse(error_code=error_code, message=message).model_dump()
    detail["retry_after_seconds"] = int(decision.retry_after_seconds)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers=headers,
    )


def enforce_rate_limit_for_request(
    request: Request,
    *,
    rule_name: str,
    error_code: str = "RATE_LIMITED",
    message: str = "Too many requests",
    user_id: str | None = None,
    tenant_id: str | None = None,
    route: str | None = None,
    method: str | None = None,
    resource_id: str | None = None,
    normalized_email: str | None = None,
    payload_hash: str | None = None,
) -> RateLimitDecision:
    decision = get_rate_limiter().allow(
        key=build_rate_limit_key(
            ip=get_client_ip(request),
            user_id=user_id,
            tenant_id=tenant_id,
            route=route or request.url.path,
            method=method or request.method,
            resource_id=resource_id,
            normalized_email=normalized_email,
            payload_hash=payload_hash,
        ),
        rule_name=rule_name,
    )
    if not decision.allowed:
        _raise_rate_limit(decision=decision, error_code=error_code, message=message)
    return decision


def enforce_rate_limit(
    rule_name: str,
    key_builder: Callable[[Request], dict],
    *,
    error_code: str = "RATE_LIMITED",
    message: str = "Too many requests",
):
    def _dependency(request: Request) -> None:
        payload = key_builder(request) or {}
        enforce_rate_limit_for_request(
            request,
            rule_name=rule_name,
            error_code=error_code,
            message=message,
            user_id=payload.get("user_id"),
            tenant_id=payload.get("tenant_id"),
            route=payload.get("route"),
            method=payload.get("method"),
            resource_id=payload.get("resource_id"),
            normalized_email=payload.get("normalized_email"),
            payload_hash=payload.get("payload_hash"),
        )

    return _dependency
