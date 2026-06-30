"""
chat.py v3 — LLM中枢入口
"""

import asyncio
import json
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from models.database import Conversation, Message, RequestTrace, get_db
from models.schemas import ChatRequest
from services.brain import Brain, think

router = APIRouter()


def _ensure_conversation(db: Session, conversation_id: str, title_seed: str) -> Conversation:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conversation:
        conversation.updated_at = datetime.utcnow()
        db.commit()
        return conversation

    conversation = Conversation(id=conversation_id, title=(title_seed or "新会话")[:30])
    db.add(conversation)
    db.commit()
    return conversation


def _load_history(db: Session, conversation_id: str, limit: int = 20) -> list[dict]:
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


def _log_trace(db: Session, request_id: str, event_type: str, event_data: dict):
    try:
        db.add(
            RequestTrace(
                id=str(uuid.uuid4()),
                request_id=request_id,
                event_type=event_type,
                event_data=event_data,
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def _prepare_chat_request(request: ChatRequest, db: Session) -> dict:
    request_id = str(uuid.uuid4())
    conversation_id = request.conversation_id or str(uuid.uuid4())
    user_msg_id = str(uuid.uuid4())

    _log_trace(
        db,
        request_id,
        "request_received",
        {"message": request.message, "conversation_id": conversation_id, "engine": "brain_v3"},
    )

    _ensure_conversation(db, conversation_id, request.message)
    history = _load_history(db, conversation_id, limit=20)

    db.add(
        Message(
            id=user_msg_id,
            conversation_id=conversation_id,
            role="user",
            content=request.message,
            entities_mentioned=[],
        )
    )
    db.commit()

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
):
    assistant_msg_id = str(uuid.uuid4())
    status, delivery_type = _infer_delivery(reply)
    cleaned_reply = _sanitize_reply_for_delivery(reply)
    delivery = {
        "status": status,
        "content": cleaned_reply,
        "sources": [],
        "delivery_type": delivery_type,
        "execution_summary": {
            "engine": "brain_v3",
            "conversation_id": conversation_id,
        },
        "next_actions": _build_next_actions(delivery_type, status),
    }

    db.add(
        Message(
            id=assistant_msg_id,
            conversation_id=conversation_id,
            role="assistant",
            content=cleaned_reply,
            sources=[],
            delivery_type=delivery_type,
            status="completed" if status != "error" else "failed",
        )
    )
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conversation:
        conversation.updated_at = datetime.utcnow()
    db.commit()

    _log_trace(
        db,
        request_id,
        "delivery_emitted",
        {"delivery_type": delivery_type, "status": status, "engine": "brain_v3"},
    )

    return {
        "request_id": request_id,
        "conversation_id": conversation_id,
        "assistant_msg_id": assistant_msg_id,
        "delivery": delivery,
    }


def _process_chat_request(request: ChatRequest, db: Session) -> dict:
    prepared = _prepare_chat_request(request, db)
    reply = think(request.message, prepared["conversation_id"], prepared["history"])
    return _finalize_delivery(
        db=db,
        request_id=prepared["request_id"],
        conversation_id=prepared["conversation_id"],
        reply=reply,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    return StreamingResponse(
        _stream_chat_response(request, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_chat_response(request: ChatRequest, db: Session):
    prepared = _prepare_chat_request(request, db)
    request_id = prepared["request_id"]
    conversation_id = prepared["conversation_id"]
    history = prepared["history"]
    brain = Brain()
    full_content = ""
    errored = False

    try:
        async def event(payload: dict):
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        assistant_message_id = str(uuid.uuid4())
        yield await event({"type": "start", "message_id": assistant_message_id, "delivery_type": "text"})

        for chunk in brain.think_stream(request.message, conversation_id, history):
            chunk_type = chunk.get("type")
            if chunk_type == "thinking":
                yield await event({"type": "thinking", "message_id": assistant_message_id})
            elif chunk_type == "tool_call":
                yield await event(
                    {
                        "type": "tool_call",
                        "message_id": assistant_message_id,
                        "name": chunk.get("name", ""),
                    }
                )
            elif chunk_type == "token":
                token = chunk.get("content", "")
                full_content += token
                yield await event(
                    {
                        "type": "content",
                        "message_id": assistant_message_id,
                        "content": token,
                    }
                )
            elif chunk_type == "error":
                errored = True
                yield await event({"type": "error", "message": chunk.get("message", "请求失败")})
            elif chunk_type == "done":
                break

        if not errored:
            finalized = _finalize_delivery(
                db=db,
                request_id=request_id,
                conversation_id=conversation_id,
                reply=full_content,
            )
            finalized["assistant_msg_id"] = assistant_message_id
            yield await event(
                {
                    "type": "done",
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "message_id": assistant_message_id,
                    "full_content": full_content,
                    "delivery": finalized["delivery"],
                }
            )
        yield "data: [DONE]\n\n"
    except asyncio.CancelledError:
        return
    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"


@router.post("/chat/simple")
def chat_simple(request: ChatRequest, db: Session = Depends(get_db)):
    payload = _process_chat_request(request, db)
    return {
        "reply": payload["delivery"]["content"],
        "delivery": payload["delivery"],
        "conversation_id": payload["conversation_id"],
    }
