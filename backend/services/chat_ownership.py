from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Query, Session

import config
from models.database import Conversation
from schemas.watch_alert import ApiErrorResponse


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


def get_conversation_or_404(
    db: Session,
    conversation_id: str,
    *,
    owner_user_id: str | None,
) -> Conversation:
    query = db.query(Conversation).filter(Conversation.id == conversation_id)
    conversation = apply_conversation_owner_scope(query, owner_user_id=owner_user_id).first()
    if conversation is None:
        _raise_api_error(status.HTTP_404_NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation not found")
    return conversation
