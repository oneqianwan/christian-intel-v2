import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from models.database import get_db, Conversation, Message, RequestTrace
from models.schemas import ConversationCreate, ConversationResponse, MessageResponse
from typing import List

router = APIRouter()


class ConversationUpdate(BaseModel):
    title: str


class PinRequest(BaseModel):
    pinned: bool

@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(req: ConversationCreate, db: Session = Depends(get_db)):
    # 确保 title 是有效且长度受控的 UTF-8 字符串
    title = req.title or "新会话"
    if len(title) > 50:
        title = title[:50]
    conv = Conversation(id=str(uuid.uuid4()), title=title)
    db.add(conv); db.commit(); db.refresh(conv)
    return conv

@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(db: Session = Depends(get_db)):
    return db.query(Conversation).order_by(
        Conversation.is_pinned.desc(),
        Conversation.pinned_at.desc().nullslast(),
        Conversation.updated_at.desc(),
    ).all()


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    db: Session = Depends(get_db),
):
    """编辑会话标题"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    title = (req.title or "").strip() or "新会话"
    conv.title = title[:50]
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return conv


@router.put("/conversations/{conversation_id}/pin")
def pin_conversation(
    conversation_id: str,
    req: PinRequest,
    db: Session = Depends(get_db),
):
    """置顶/取消置顶会话"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    conv.is_pinned = req.pinned
    conv.pinned_at = datetime.utcnow() if req.pinned else None
    conv.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conv)
    return {
        "id": conv.id,
        "title": conv.title,
        "is_pinned": conv.is_pinned,
        "pinned_at": conv.pinned_at.isoformat() if conv.pinned_at else None,
    }


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
):
    """
    删除会话
    级联删除：messages + request_traces
    保留不动：intelligence_items + user_preferences + bookmarks
    """
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    message_count = db.query(Message).filter(Message.conversation_id == conversation_id).delete()

    # 当前 request_traces 通过 request_id 关联，没有稳定的 conversation 外键。
    # 仅清理 event_data 中显式记录了 conversation_id 的 trace，避免误删其他请求日志。
    traces = db.query(RequestTrace).all()
    deleted_trace_count = 0
    for trace in traces:
        event_data = trace.event_data or {}
        if isinstance(event_data, dict) and event_data.get("conversation_id") == conversation_id:
            db.delete(trace)
            deleted_trace_count += 1

    db.delete(conv)
    db.commit()

    return {
        "deleted": True,
        "conversation_id": conversation_id,
        "messages_deleted": message_count,
        "request_traces_deleted": deleted_trace_count,
        "intelligence_items_deleted": 0,
        "user_preferences_deleted": 0,
    }

@router.get("/conversations/{id}/messages", response_model=List[MessageResponse])
def get_messages(id: str, db: Session = Depends(get_db)):
    return db.query(Message).filter(Message.conversation_id == id).order_by(Message.created_at).all()
