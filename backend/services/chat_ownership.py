from __future__ import annotations

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Query, Session

import config
from dependencies.tenant_context import TenantRequestContext, resolve_tenant_request_context
from models.database import Conversation, Message
from schemas.watch_alert import ApiErrorResponse
from services import tenant_scope, tenant_service


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def is_chat_user_ownership_enabled() -> bool:
    if bool(config.settings.public_core_apis_enabled()) and not bool(config.settings.CHAT_USER_OWNERSHIP_ENABLED):
        return False
    return True


def get_owner_user_id(current_user) -> str | None:
    if current_user is None:
        return None
    return str(current_user.id)


def require_owner_user_id(owner_user_id: str | None) -> str | None:
    if not is_chat_user_ownership_enabled():
        return None
    normalized = str(owner_user_id or "").strip()
    if not normalized:
        _raise_api_error(status.HTTP_401_UNAUTHORIZED, "AUTH_REQUIRED", "Authentication required")
    return normalized


def apply_conversation_owner_scope(query: Query, *, owner_user_id: str | None):
    if not is_chat_user_ownership_enabled():
        return query
    normalized_owner_user_id = require_owner_user_id(owner_user_id)
    return query.filter(Conversation.owner_user_id == normalized_owner_user_id)


def _bootstrap_legacy_default_tenant_membership(*, db: Session, current_user, request: Request) -> None:
    if current_user is None or tenant_service.is_platform_super_admin(current_user):
        return
    default_tenant_id = str(getattr(current_user, "default_tenant_id", "") or "").strip()
    if not default_tenant_id:
        tenant_service.ensure_user_default_tenant_membership(db, user=current_user)
        db.flush()
        return

    tenant_public_id = (
        request.headers.get("X-Tenant-ID")
        or request.query_params.get("tenant_id")
        or request.query_params.get("tenant_public_id")
    )
    tenant_slug = request.headers.get("X-Tenant-Slug") or request.query_params.get("tenant_slug")
    if str(tenant_public_id or "").strip() or str(tenant_slug or "").strip():
        return

    membership = tenant_service.get_membership_for_user(
        db,
        user_id=str(current_user.id),
        tenant_id=default_tenant_id,
    )
    if membership is not None:
        return

    default_tenant = tenant_service.ensure_default_tenant(db)
    if str(default_tenant_id) != str(default_tenant.id):
        return

    tenant_service.get_or_create_membership(
        db,
        tenant=default_tenant,
        user=current_user,
        role=tenant_service.map_user_role_to_membership_role(getattr(current_user, "role", None)),
        status="active" if str(getattr(current_user, "status", "") or "").strip().lower() == "active" else "pending",
        created_by_user_id=None,
    )
    db.flush()


def resolve_chat_tenant_context(
    *,
    request: Request,
    db: Session,
    current_user,
) -> TenantRequestContext | None:
    if not is_chat_user_ownership_enabled():
        return None
    require_owner_user_id(get_owner_user_id(current_user))
    _bootstrap_legacy_default_tenant_membership(db=db, current_user=current_user, request=request)
    if current_user is not None:
        db.flush()
        db.refresh(current_user)
    return resolve_tenant_request_context(request=request, user=current_user, db=db, fail_closed=True)


def apply_conversation_access_scope(
    query: Query,
    *,
    owner_user_id: str | None,
    current_user,
    current_tenant,
):
    if not is_chat_user_ownership_enabled() or current_tenant is None:
        return apply_conversation_owner_scope(query, owner_user_id=owner_user_id)
    current_tenant_id = tenant_scope.ensure_tenant_id_for_create({}, current_tenant).get("tenant_id")
    query = tenant_scope.filter_by_tenant(query, Conversation, current_tenant_id)
    is_super_admin = (
        bool(current_user)
        if isinstance(current_user, bool)
        else tenant_service.is_platform_super_admin(current_user)
    )
    if is_super_admin:
        return query
    normalized_owner_user_id = require_owner_user_id(owner_user_id)
    return query.filter(Conversation.owner_user_id == normalized_owner_user_id)


def get_conversation_or_404(
    db: Session,
    conversation_id: str,
    *,
    owner_user_id: str | None,
    current_user=None,
    current_tenant=None,
) -> Conversation:
    query = db.query(Conversation).filter(Conversation.id == conversation_id)
    conversation = apply_conversation_access_scope(
        query,
        owner_user_id=owner_user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    ).first()
    if conversation is None:
        _raise_api_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation not found")
    if current_tenant is not None:
        try:
            tenant_scope.require_record_tenant(conversation, current_tenant)
        except tenant_scope.TenantScopeError as exc:
            _raise_api_error(exc.status_code, exc.error_code, exc.message)
    return conversation


def list_messages_for_conversation(
    db: Session,
    conversation_id: str,
    *,
    owner_user_id: str | None,
    current_user=None,
    current_tenant=None,
):
    conversation = get_conversation_or_404(
        db,
        conversation_id,
        owner_user_id=owner_user_id,
        current_user=current_user,
        current_tenant=current_tenant,
    )
    query = db.query(Message).filter(Message.conversation_id == conversation_id)
    if current_tenant is not None and is_chat_user_ownership_enabled():
        current_tenant_id = tenant_scope.ensure_tenant_id_for_create({}, current_tenant).get("tenant_id")
        query = tenant_scope.filter_by_tenant(query, Message, current_tenant_id)
    return conversation, query.order_by(Message.created_at.asc()).all()
