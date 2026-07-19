"""
chat.py v3 — LLM中枢入口
"""

import asyncio
import contextvars
import json
import os
import re
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session

from dependencies.chat_auth import get_chat_current_user
from dependencies.rate_limit import enforce_rate_limit_for_request
from models.auth import User
from models.database import Conversation, Message, RequestTrace, emit_db_runtime_debug, get_db
from models.schemas import ChatRequest
from services.brain import Brain, think
from services import tenant_scope, tenant_service
from services.chat_ownership import (
    get_conversation_or_404,
    get_owner_user_id,
    is_chat_user_ownership_enabled,
    list_messages_for_conversation,
    resolve_chat_tenant_context,
)
from services.trace_center import debug_answer_event, set_trace_print
from services.welcome_trace import emit_welcome_trace, lookup_welcome_reply_uuid

router = APIRouter()
TRACE_DB_WRITE_ENABLED = os.getenv("TRACE_DB_WRITE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _safe_trace_serializer(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            return repr(value)
    if isinstance(value, bytearray):
        return repr(value)
    if isinstance(value, BaseException):
        return str(value)
    return repr(value)


def _safe_trace_key(key) -> str:
    normalized = _safe_trace_serializer(key)
    if normalized is None:
        return "None"
    return str(normalized)


def _safe_trace_normalize(value):
    if isinstance(value, dict):
        return {
            _safe_trace_key(key): _safe_trace_normalize(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_safe_trace_normalize(item) for item in value]
    return _safe_trace_serializer(value)


def _safe_json_dumps(payload) -> str:
    return json.dumps(
        _safe_trace_normalize(payload),
        ensure_ascii=False,
    )


def _chat_stream_trace(event: str, **data):
    print(
        "CHAT_STREAM_TRACE "
        + _safe_json_dumps(
            {
                "event": event,
                **data,
            }
        )
    )


def _chat_stream_lifecycle_trace(event: str, *, conversation_id: str, generator_id: str, started_at: float, **payload):
    print(
        "CHAT_STREAM_LIFECYCLE "
        + _safe_json_dumps(
            {
                "event": event,
                "conversation_id": conversation_id,
                "generator_id": generator_id,
                "thread_id": threading.get_ident(),
                "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 3),
                **payload,
            }
        )
    )


def _db_persist_trace(event: str, db: Session, *, sql: str = "", exc: Exception | None = None, **extra):
    emit_db_runtime_debug(
        event,
        DB_CONNECTION=repr(getattr(db, "bind", None)),
        session_id=id(db),
        SQL=sql,
        FULL_EXCEPTION=(traceback.format_exc() if exc is not None else ""),
        **extra,
    )


def _db_commit_with_trace(db: Session, *, sql: str, location: str, **extra):
    _db_persist_trace("COMMIT_REQUEST", db, sql=sql, location=location, **extra)
    try:
        db.commit()
        _db_persist_trace("COMMIT_OK", db, sql=sql, location=location, **extra)
    except Exception as exc:
        _db_persist_trace("COMMIT_FAIL", db, sql=sql, exc=exc, location=location, **extra)
        try:
            _db_persist_trace("ROLLBACK_REQUEST", db, sql=sql, location=location, **extra)
            db.rollback()
            _db_persist_trace("ROLLBACK_OK", db, sql=sql, location=location, **extra)
        except Exception as rollback_exc:
            _db_persist_trace("ROLLBACK_FAIL", db, sql=sql, exc=rollback_exc, location=location, **extra)
        raise


def _rollback_quietly(db: Session, *, label: str, sql: str = "", exc: Exception | None = None, **extra):
    try:
        _db_persist_trace(label, db, sql=sql, exc=exc, **extra)
        db.rollback()
    except Exception as rollback_exc:
        _db_persist_trace(f"{label}_ROLLBACK_FAIL", db, sql=sql, exc=rollback_exc, **extra)


def _ensure_conversation(
    db: Session,
    conversation_id: str,
    title_seed: str,
    *,
    owner_user_id: str | None = None,
    current_user: User | None = None,
    current_tenant=None,
) -> Conversation:
    select_sql = "SELECT * FROM conversations WHERE id = :conversation_id LIMIT 1"
    try:
        _db_persist_trace(
            "SELECT conversation",
            db,
            sql=select_sql,
            conversation_id=conversation_id,
        )
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if is_chat_user_ownership_enabled() and conversation is not None:
            conversation = get_conversation_or_404(
                db,
                conversation_id,
                owner_user_id=owner_user_id,
                current_user=current_user,
                current_tenant=current_tenant,
            )
    except Exception as exc:
        _db_persist_trace("SELECT conversation FAIL", db, sql=select_sql, exc=exc, conversation_id=conversation_id)
        raise
    if conversation:
        conversation.updated_at = datetime.utcnow()
        update_sql = "UPDATE conversations SET updated_at = :updated_at WHERE id = :conversation_id"
        try:
            _db_commit_with_trace(
                db,
                sql=update_sql,
                location="chat.py:_ensure_conversation:update_existing",
                conversation_id=conversation_id,
            )
        except Exception as exc:
            _rollback_quietly(
                db,
                label="CONVERSATION_UPDATE_ROLLBACK",
                sql=update_sql,
                exc=exc,
                conversation_id=conversation_id,
            )
            print(
                "CONVERSATION_SAVE_FAILED "
                + _safe_json_dumps(
                    {
                        "conversation_id": conversation_id,
                        "error": str(exc),
                        "mode": "update_existing",
                    }
                )
            )
        return conversation

    insert_sql = "INSERT INTO conversations (id, title, is_pinned, pinned_at, created_at, updated_at) VALUES (:id, :title, :is_pinned, :pinned_at, :created_at, :updated_at)"
    try:
        conversation = Conversation(
            id=conversation_id,
            title=(title_seed or "新会话")[:30],
            tenant_id=(
                tenant_scope.ensure_tenant_id_for_create({}, current_tenant).get("tenant_id")
                if current_tenant is not None and is_chat_user_ownership_enabled()
                else None
            ),
            owner_user_id=owner_user_id,
        )
        _db_persist_trace(
            "INSERT conversation",
            db,
            sql=insert_sql,
            conversation_id=conversation_id,
            title=(title_seed or "新会话")[:30],
        )
        db.add(conversation)
    except Exception as exc:
        _db_persist_trace("INSERT conversation PREPARE FAIL", db, sql=insert_sql, exc=exc, conversation_id=conversation_id)
        raise
    try:
        _db_commit_with_trace(
            db,
            sql=insert_sql,
            location="chat.py:_ensure_conversation:insert",
            conversation_id=conversation_id,
        )
    except Exception as exc:
        _rollback_quietly(
            db,
            label="CONVERSATION_INSERT_ROLLBACK",
            sql=insert_sql,
            exc=exc,
            conversation_id=conversation_id,
        )
        print(
            "CONVERSATION_SAVE_FAILED "
            + _safe_json_dumps(
                {
                    "conversation_id": conversation_id,
                    "error": str(exc),
                    "mode": "insert",
                }
            )
        )
    return conversation


def _load_history(
    db: Session,
    conversation_id: str,
    limit: int = 20,
    *,
    owner_user_id: str | None = None,
    current_user: User | None = None,
    current_tenant=None,
) -> list[dict]:
    if is_chat_user_ownership_enabled():
        _, messages = list_messages_for_conversation(
            db,
            conversation_id,
            owner_user_id=owner_user_id,
            current_user=current_user,
            current_tenant=current_tenant,
        )
        messages = messages[:limit]
    else:
        messages = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(limit)
            .all()
        )
    return [{"role": msg.role, "content": msg.content or ""} for msg in messages]


def _infer_delivery(reply: str) -> tuple[str, str]:
    content = (reply or "").strip()
    lowered = content.lower()

    if "暂时无法连接分析引擎" in content:
        return "error", "error"
    if "[insufficient data]" in lowered:
        return "no_data", "no_data"
    if "我还不知道你是谁" in content or "你可以直接告诉我" in content:
        return "clarify", "clarify"
    if "公开联系信息" in content or ("联系信息" in content and any(token in content for token in ["邮箱", "电话", "官网"])):
        return "success", "contact_brief"
    if "记住了" in content or "知道。你是" in content:
        return "success", "text"
    return "success", "intelligence_brief"


def _sanitize_reply_for_delivery(reply: str) -> str:
    cleaned = (reply or "").strip()
    if not cleaned:
        return ""

    cleaned = cleaned.replace("[[EXECUTIVE_REPORT]]", "")
    cleaned = re.sub(r"\[\[GRAPH_DATA\]\][\s\S]*?\[\[/GRAPH_DATA\]\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[SOURCE:[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\[CONFIDENCE:[^\]]*\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("[INSUFFICIENT DATA]", "当前情报不足：")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _build_next_actions(delivery_type: str, status: str) -> list[str]:
    if status == "error":
        return ["稍后重试", "检查模型配置", "改用简单问题测试"]
    if delivery_type == "clarify":
        return ["补充国家名", "补充机构名", "告诉我你的身份信息"]
    if delivery_type == "contact_brief":
        return ["继续查负责人背景", "补充公开邮箱", "为机构做定向采集"]
    if status == "no_data":
        return ["让我后台补采", "补充时间范围", "补充更具体的机构名"]
    return ["继续追问细节", "改问联系人信息", "指定时间范围重查"]


def _log_trace(db: Session, request_id: str, event_type: str, event_data: dict, *, tenant_id: str | None = None):
    print(
        "REQUEST_TRACE_STDOUT "
        + _safe_json_dumps(
            {
                "request_id": request_id,
                "event_type": event_type,
                "event_data": event_data,
                "tenant_id": tenant_id,
                "trace_db_write_enabled": TRACE_DB_WRITE_ENABLED,
            }
        )
    )

    if not TRACE_DB_WRITE_ENABLED:
        return

    try:
        _db_persist_trace(
            "INSERT request_trace",
            db,
            sql="INSERT INTO request_traces (id, tenant_id, request_id, event_type, event_data) VALUES (:id, :tenant_id, :request_id, :event_type, :event_data)",
            request_id=request_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
        db.add(
            RequestTrace(
                id=str(uuid.uuid4()),
                tenant_id=str(tenant_id or "").strip() or None,
                request_id=request_id,
                event_type=event_type,
                event_data=event_data,
            )
        )
        _db_commit_with_trace(
            db,
            sql="INSERT INTO request_traces (id, tenant_id, request_id, event_type, event_data) VALUES (:id, :tenant_id, :request_id, :event_type, :event_data)",
            location="chat.py:_log_trace",
            request_id=request_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
    except Exception as exc:
        _db_persist_trace(
            "REQUEST_TRACE_FAIL",
            db,
            sql="INSERT INTO request_traces (id, tenant_id, request_id, event_type, event_data) VALUES (:id, :tenant_id, :request_id, :event_type, :event_data)",
            exc=exc,
            request_id=request_id,
            tenant_id=tenant_id,
            event_type=event_type,
        )
        print(
            "REQUEST_TRACE_DB_SKIPPED_AFTER_ERROR "
            + _safe_json_dumps(
                {
                    "request_id": request_id,
                    "event_type": event_type,
                    "tenant_id": tenant_id,
                    "error": str(exc),
                }
            )
        )


def _prepare_chat_request(
    request: ChatRequest,
    db: Session,
    *,
    persist_db: bool = True,
    owner_user_id: str | None = None,
    current_user: User | None = None,
    current_tenant=None,
) -> dict:
    request_id = str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    user_msg_id = str(uuid.uuid4())
    _db_persist_trace(
        "_prepare_chat_request:enter",
        db,
        sql="",
        request_id=request_id,
        conversation_id=conversation_id,
    )

    _log_trace(
        db,
        request_id,
        "request_received",
        {"message": request.message, "conversation_id": conversation_id, "engine": "brain_v3"},
        tenant_id=str(current_tenant or "").strip() or None,
    )

    if not persist_db:
        if is_chat_user_ownership_enabled() and request.conversation_id:
            _load_history(
                db,
                conversation_id,
                limit=20,
                owner_user_id=owner_user_id,
                current_user=current_user,
                current_tenant=current_tenant,
            )
        print(
            "STREAM_DB_PERSIST_DISABLED "
            + _safe_json_dumps(
                {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "reason": "stream_path_memory_fallback",
                }
            )
        )
        return {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "history": [],
        }

    try:
        conversation = _ensure_conversation(
            db,
            conversation_id,
            request.message,
            owner_user_id=owner_user_id,
            current_user=current_user,
            current_tenant=current_tenant,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _rollback_quietly(
            db,
            label="CONVERSATION_SAVE_ROLLBACK",
            sql="",
            exc=exc,
            conversation_id=conversation_id,
        )
        print(
            "CONVERSATION_SAVE_FAILED "
            + _safe_json_dumps(
                {
                    "conversation_id": conversation_id,
                    "error": str(exc),
                    "mode": "prepare_wrapper",
                }
            )
        )
        raise

    try:
        history = _load_history(
            db,
            conversation_id,
            limit=20,
            owner_user_id=owner_user_id,
            current_user=current_user,
            current_tenant=current_tenant,
        )
    except HTTPException:
        raise
    except Exception as exc:
        _rollback_quietly(
            db,
            label="HISTORY_LOAD_ROLLBACK",
            sql="SELECT role, content FROM messages WHERE conversation_id = :conversation_id ORDER BY created_at ASC LIMIT :limit",
            exc=exc,
            conversation_id=conversation_id,
        )
        print(
            "HISTORY_LOAD_FAILED "
            + _safe_json_dumps(
                {
                    "conversation_id": conversation_id,
                    "error": str(exc),
                }
            )
        )
        raise

    message_sql = "INSERT INTO messages (id, conversation_id, role, content, entities_mentioned) VALUES (:id, :conversation_id, :role, :content, :entities_mentioned)"
    try:
        message_tenant_payload = (
            tenant_scope.ensure_tenant_id_for_create(
                {"tenant_id": getattr(conversation, "tenant_id", None)},
                current_tenant,
            )
            if current_tenant is not None and is_chat_user_ownership_enabled()
            else {}
        )
        db.add(
            Message(
                id=user_msg_id,
                tenant_id=message_tenant_payload.get("tenant_id"),
                conversation_id=conversation_id,
                role="user",
                content=request.message,
                entities_mentioned=[],
            )
        )
        _db_persist_trace(
            "INSERT user_message",
            db,
            sql=message_sql,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_msg_id,
        )
        _db_commit_with_trace(
            db,
            sql=message_sql,
            location="chat.py:_prepare_chat_request:insert_user_message",
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_msg_id,
        )
        print("Message Saved=True")
    except Exception as exc:
        _rollback_quietly(
            db,
            label="MESSAGE_SAVE_ROLLBACK",
            sql=message_sql,
            exc=exc,
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=user_msg_id,
        )
        print(
            "MESSAGE_SAVE_FAILED "
            + _safe_json_dumps(
                {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "message_id": user_msg_id,
                    "error": str(exc),
                    "role": "user",
                }
            )
        )
        raise

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "history": history,
    }


def _finalize_delivery(
    db: Session,
    request_id: str,
    conversation_id: str,
    reply: str,
    sources: list | None = None,
    *,
    persist_db: bool = True,
    owner_user_id: str | None = None,
    current_user: User | None = None,
    current_tenant=None,
):
    assistant_msg_id = str(uuid.uuid4())
    status, delivery_type = _infer_delivery(reply)
    final_reply = "" if reply is None else str(reply)
    welcome_reply_uuid = lookup_welcome_reply_uuid(conversation_id, final_reply)
    normalized_sources = sources or []
    delivery = {
        "status": status,
        "content": final_reply,
        "welcome_reply_uuid": welcome_reply_uuid,
        "sources": normalized_sources,
        "delivery_type": delivery_type,
        "execution_summary": {
            "engine": "brain_v3",
            "conversation_id": conversation_id,
        },
        "next_actions": _build_next_actions(delivery_type, status),
    }
    emit_welcome_trace(
        "STORE_UUID",
        welcome_reply_uuid,
        conversation_id=conversation_id,
        extra={"location": "chat.py:_finalize_delivery"},
    )

    if not persist_db:
        print(
            "STREAM_DB_FINALIZE_DISABLED "
            + _safe_json_dumps(
                {
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_msg_id,
                }
            )
        )
    else:
        try:
            conversation = (
                get_conversation_or_404(
                    db,
                    conversation_id,
                    owner_user_id=owner_user_id,
                    current_user=current_user,
                    current_tenant=current_tenant,
                )
                if is_chat_user_ownership_enabled()
                else db.query(Conversation).filter(Conversation.id == conversation_id).first()
            )
            assistant_message_tenant_payload = (
                tenant_scope.ensure_tenant_id_for_create(
                    {"tenant_id": getattr(conversation, "tenant_id", None)},
                    current_tenant,
                )
                if current_tenant is not None and is_chat_user_ownership_enabled()
                else {}
            )
            db.add(
                Message(
                    id=assistant_msg_id,
                    tenant_id=assistant_message_tenant_payload.get("tenant_id"),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=final_reply,
                    sources=normalized_sources,
                    delivery_type=delivery_type,
                    status="completed" if status != "error" else "failed",
                )
            )
            conversation.updated_at = datetime.utcnow()
            db.commit()
        except Exception as exc:
            _rollback_quietly(
                db,
                label="FINALIZE_DELIVERY_ROLLBACK",
                sql="INSERT INTO messages/UPDATE conversations",
                exc=exc,
                request_id=request_id,
                conversation_id=conversation_id,
                assistant_message_id=assistant_msg_id,
            )
            print(
                "MESSAGE_SAVE_FAILED "
                + _safe_json_dumps(
                    {
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "message_id": assistant_msg_id,
                        "error": str(exc),
                        "role": "assistant",
                    }
                )
            )

    _log_trace(
        db,
        request_id,
        "delivery_emitted",
        {
            "conversation_id": conversation_id,
            "delivery_type": delivery_type,
            "status": status,
            "engine": "brain_v3",
        },
        tenant_id=str(current_tenant or "").strip() or None,
    )

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "assistant_msg_id": assistant_msg_id,
        "delivery": delivery,
    }


def _process_chat_request(request: ChatRequest, db: Session) -> dict:
    prepared = _prepare_chat_request(request, db, persist_db=False)
    result = think(request.message, prepared["conversation_id"], prepared["history"])
    reply = result.get("answer", "") if isinstance(result, dict) else str(result or "")
    sources = result.get("evidence", []) if isinstance(result, dict) else []
    return _finalize_delivery(
        db=db,
        request_id=prepared["request_id"],
        conversation_id=prepared["conversation_id"],
        reply=reply,
        sources=sources,
    )


@router.post("/chat/stream")
async def chat_stream(
    chat_request: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    try:
        owner_user_id = get_owner_user_id(current_user)
        current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
        tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
        current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
        enforce_rate_limit_for_request(
            request,
            rule_name="chat_stream",
            user_id=str(owner_user_id or "anonymous"),
            tenant_id=str(current_tenant_id or "no-tenant"),
            route="/api/chat/stream",
            method="POST",
        )
        generator_id = f"chat-stream-{uuid.uuid4()}"
        persist_db = is_chat_user_ownership_enabled()
        prepared = _prepare_chat_request(
            chat_request,
            db,
            persist_db=persist_db,
            owner_user_id=owner_user_id,
            current_user=current_user_is_super_admin,
            current_tenant=current_tenant_id,
        )
        try:
            from main import BACKEND_INSTANCE_UUID, BACKEND_PORT
        except Exception:
            BACKEND_INSTANCE_UUID = "UNKNOWN"
            BACKEND_PORT = os.environ.get("PORT", "8000")
        print(f"BACKEND_INSTANCE_UUID={BACKEND_INSTANCE_UUID}")
        print(f"PID={os.getpid()}")
        print(f"PORT={BACKEND_PORT}")
        return StreamingResponse(
            _stream_chat_response(
                chat_request,
                request,
                db,
                prepared=prepared,
                owner_user_id=owner_user_id,
                current_user=current_user_is_super_admin,
                current_tenant=current_tenant_id,
                persist_db=persist_db,
                generator_id=generator_id,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as exc:
        print(f"ExceptionType={type(exc).__name__}")
        print(f"Exception={exc}")
        print(f"Traceback={traceback.format_exc()}")
        raise


async def _stream_chat_response(
    request: ChatRequest,
    raw_request: Request,
    db: Session,
    *,
    prepared: dict,
    owner_user_id: str | None,
    current_user: User | None,
    current_tenant,
    persist_db: bool,
    generator_id: str,
):
    request_id = prepared["request_id"]
    conversation_id = prepared["conversation_id"]
    history = prepared["history"]
    brain = Brain()
    full_content = ""
    errored = False
    evidence = []
    chunk_count = 0
    stream_started = time.perf_counter()
    last_token = ""

    try:
        set_trace_print(enabled=True, request_id=request_id)
        ctx = contextvars.copy_context()

        async def event(payload: dict):
            return f"data: {_safe_json_dumps(payload)}\n\n"

        assistant_message_id = str(uuid.uuid4())
        start_chunk = await event({"type": "start", "message_id": assistant_message_id, "delivery_type": "text"})
        yield start_chunk

        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker():
            try:
                for chunk in brain.think_stream(request.message, conversation_id, history):
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put({"type": "error", "message": str(exc)}), loop)
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        thread = threading.Thread(target=lambda: ctx.run(worker), daemon=True)
        thread.start()

        while True:
            if await raw_request.is_disconnected():
                break
            chunk = await queue.get()
            if chunk is None:
                break
            chunk_type = chunk.get("type") if isinstance(chunk, dict) else None
            if chunk_type == "thinking":
                thinking_chunk = await event({"type": "thinking", "message_id": assistant_message_id})
                yield thinking_chunk
            elif chunk_type == "tool_call":
                tool_chunk = await event(
                    {
                        "type": "tool_call",
                        "message_id": assistant_message_id,
                        "name": chunk.get("name", ""),
                    }
                )
                yield tool_chunk
            elif chunk_type == "evidence":
                payload = chunk.get("evidence") or []
                if isinstance(payload, list):
                    evidence = payload
            elif chunk_type == "token":
                token = chunk.get("content", "")
                full_content += token
                chunk_count += 1
                last_token = str(token or "")
                content_chunk = await event(
                    {
                        "type": "content",
                        "message_id": assistant_message_id,
                        "content": token,
                    }
                )
                yield content_chunk
            elif chunk_type == "error":
                errored = True
                error_chunk = await event({"type": "error", "message": chunk.get("message", "请求失败")})
                yield error_chunk
            elif chunk_type == "done":
                payload = chunk.get("evidence") or []
                if isinstance(payload, list):
                    evidence = payload
                break

        if not errored:
            emit_welcome_trace(
                "ROUTER_UUID",
                lookup_welcome_reply_uuid(conversation_id, full_content),
                conversation_id=conversation_id,
                extra={"location": "chat.py:_stream_chat_response:before_finalize"},
            )
            finalized = _finalize_delivery(
                db=db,
                request_id=request_id,
                conversation_id=conversation_id,
                reply=full_content,
                sources=evidence,
                persist_db=persist_db,
                owner_user_id=owner_user_id,
                current_user=current_user,
                current_tenant=current_tenant,
            )
            finalized["assistant_msg_id"] = assistant_message_id
            welcome_reply_uuid = finalized["delivery"].get("welcome_reply_uuid")
            emit_welcome_trace(
                "SEND_UUID",
                welcome_reply_uuid,
                conversation_id=conversation_id,
                extra={"location": "chat.py:_stream_chat_response:done_event"},
            )
            done_chunk = await event(
                {
                    "type": "done",
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "message_id": assistant_message_id,
                    "full_content": full_content,
                    "welcome_reply_uuid": welcome_reply_uuid,
                    "delivery": finalized["delivery"],
                }
            )
            yield done_chunk
        done_marker = "data: [DONE]\n\n"
        yield done_marker
    except GeneratorExit:
        raise
    except asyncio.CancelledError:
        return
    except Exception as exc:
        print(
            "CHAT_STREAM_ERROR "
            + _safe_json_dumps(
                {
                    "conversation_id": str(locals().get("conversation_id", "") or ""),
                    "generator_id": generator_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "elapsed_ms": round((time.perf_counter() - stream_started) * 1000, 3),
                }
            )
        )
        exception_chunk = f"data: {_safe_json_dumps({'type': 'error', 'message': str(exc)})}\n\n"
        yield exception_chunk
    finally:
        set_trace_print(enabled=False, request_id="")


@router.post("/chat/simple")
def chat_simple(
    request: ChatRequest,
    raw_request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    owner_user_id = get_owner_user_id(current_user)
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    tenant_context = resolve_chat_tenant_context(request=raw_request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    enforce_rate_limit_for_request(
        raw_request,
        rule_name="chat_simple",
        user_id=str(owner_user_id or "anonymous"),
        tenant_id=str(current_tenant_id or "no-tenant"),
        route="/api/chat/simple",
        method="POST",
    )
    prepared = _prepare_chat_request(
        request,
        db,
        owner_user_id=owner_user_id,
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )
    request_id = prepared["request_id"]
    try:
        set_trace_print(enabled=True, request_id=request_id)
        result = think(request.message, prepared["conversation_id"], prepared["history"])
        reply = result.get("answer", "") if isinstance(result, dict) else str(result or "")
        sources = result.get("evidence", []) if isinstance(result, dict) else []
        payload = _finalize_delivery(
            db=db,
            request_id=request_id,
            conversation_id=prepared["conversation_id"],
            reply=reply,
            sources=sources,
            owner_user_id=owner_user_id,
            current_user=current_user_is_super_admin,
            current_tenant=current_tenant_id,
        )
        return {
            "reply": payload["delivery"]["content"],
            "delivery": payload["delivery"],
            "conversation_id": payload["conversation_id"],
        }
    finally:
        set_trace_print(enabled=False, request_id="")
