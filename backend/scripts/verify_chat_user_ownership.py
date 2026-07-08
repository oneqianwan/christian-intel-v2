from __future__ import annotations

import re

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    config_text = _read("config.py")
    model_text = _read("models/database.py")
    chat_router_text = _read("routers/chat.py")
    conversations_router_text = _read("routers/conversations.py")
    dependency_text = _read("dependencies/chat_auth.py")
    ownership_service_text = _read("services/chat_ownership.py")
    brain_text = _read("services/brain.py")
    migration_cli_text = _read("scripts/migrate_legacy_chat_owner.py")

    _assert('"CHAT_USER_OWNERSHIP_ENABLED": False' in config_text, "CHAT_USER_OWNERSHIP_ENABLED must default to false")
    _assert(
        re.search(r"owner_user_id\s*=\s*Column\(String,\s*ForeignKey\(\"users\.id\"", model_text) is not None,
        "Conversation model must define owner_user_id foreign key",
    )
    _assert(
        "ix_conversations_owner_user_id_updated_at" in model_text,
        "Conversation model must define owner lookup index",
    )
    _assert(
        "ix_messages_conversation_id_created_at" in model_text,
        "Message model must define conversation history index",
    )
    _assert(
        "resolve_user_for_request" in dependency_text,
        "Chat auth dependency must reuse formal auth dependency",
    )
    _assert(
        "Depends(get_chat_current_user)" in chat_router_text,
        "Chat simple and stream must use chat auth dependency",
    )
    _assert(
        "Depends(get_chat_current_user)" in conversations_router_text,
        "Conversation routes must use chat auth dependency",
    )
    _assert(
        "get_conversation_or_404" in chat_router_text and "get_conversation_or_404" in conversations_router_text,
        "Chat and conversation routes must enforce owned conversation lookup",
    )
    _assert(
        "Conversation.owner_user_id == normalized_owner_user_id" in ownership_service_text,
        "Conversation queries must filter by owner_user_id in new mode",
    )
    _assert(
        "owner_user_id=get_owner_user_id(current_user)" in conversations_router_text,
        "Conversation creation must write owner_user_id from current user",
    )
    _assert(
        "owner_user_id=owner_user_id" in chat_router_text,
        "Chat routes must pass trusted owner_user_id through helper layer",
    )
    _assert("x-session-id" not in dependency_text, "New mode must not use x-session-id as auth")
    _assert("user_id" not in _read("models/schemas.py").split("class ChatRequest", 1)[1].split("class ConversationCreate", 1)[0], "ChatRequest must not accept user_id")
    _assert("owner_user_id" not in _read("models/schemas.py").split("class ChatRequest", 1)[1].split("class ConversationCreate", 1)[0], "ChatRequest must not accept owner_user_id")
    _assert("public_id" not in _read("models/schemas.py").split("class ChatRequest", 1)[1].split("class ConversationCreate", 1)[0], "ChatRequest must not accept public_id")
    _assert(
        "if not profile_row and not bool(getattr(config.settings, \"CHAT_USER_OWNERSHIP_ENABLED\", False)):" in brain_text,
        "Brain profile lookup must disable global fallback in ownership mode",
    )
    _assert('mode = "apply" if args.apply else "dry-run"' in migration_cli_text, "Migration CLI must default to dry-run")
    _assert("--password" not in migration_cli_text, "Migration CLI must not accept password")
    _assert("AuthSession" in migration_cli_text, "Migration CLI must verify AuthSession is unchanged")
    _assert("session-1" not in migration_cli_text, "Chat ownership code must not introduce default session ids")
    _assert("StreamingResponse" in chat_router_text and "_prepare_chat_request(chat_request, db" in chat_router_text, "SSE auth/ownership must happen before stream response is created")

    print("CHAT_USER_OWNERSHIP_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
