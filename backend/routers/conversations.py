import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dependencies.chat_auth import get_chat_current_user
from models.auth import User
from models.database import get_db, Conversation, Message, RequestTrace
from models.schemas import ConversationCreate, ConversationResponse, MessageResponse
from services import tenant_service
from services import tenant_scope
from services.chat_ownership import (
    apply_conversation_access_scope,
    get_conversation_or_404,
    get_owner_user_id,
    list_messages_for_conversation,
    resolve_chat_tenant_context,
)
from typing import List

router = APIRouter()


class ConversationUpdate(BaseModel):
    title: str


class PinRequest(BaseModel):
    pinned: bool

@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(
    req: ConversationCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    # 确保 title 是有效且长度受控的 UTF-8 字符串
    title = req.title or "新会话"
    if len(title) > 50:
        title = title[:50]
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    tenant_payload = (
        tenant_scope.ensure_tenant_id_for_create({}, current_tenant_id)
        if current_tenant_id is not None
        else {}
    )
    conv = Conversation(
        id=str(uuid.uuid4()),
        title=title,
        tenant_id=tenant_payload.get("tenant_id"),
        owner_user_id=get_owner_user_id(current_user),
    )
    db.add(conv); db.commit(); db.refresh(conv)
    return conv

@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    query = apply_conversation_access_scope(
        db.query(Conversation),
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )
    return query.order_by(
        Conversation.is_pinned.desc(),
        Conversation.pinned_at.desc().nullslast(),
        Conversation.updated_at.desc(),
    ).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    return get_conversation_or_404(
        db,
        conversation_id,
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )


@router.put("/conversations/{conversation_id}", response_model=ConversationResponse)
def update_conversation(
    conversation_id: str,
    req: ConversationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    """编辑会话标题"""
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    conv = get_conversation_or_404(
        db,
        conversation_id,
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )

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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    """置顶/取消置顶会话"""
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    conv = get_conversation_or_404(
        db,
        conversation_id,
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )

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
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    """
    删除会话
    级联删除：messages + request_traces
    保留不动：intelligence_items + user_preferences + bookmarks
    """
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    conv = get_conversation_or_404(
        db,
        conversation_id,
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )

    message_query = db.query(Message).filter(Message.conversation_id == conversation_id)
    if current_tenant_id is not None:
        message_query = tenant_scope.filter_by_tenant(message_query, Message, current_tenant_id)
    message_count = message_query.delete()

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
def get_messages(
    id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_chat_current_user),
):
    tenant_context = resolve_chat_tenant_context(request=request, db=db, current_user=current_user)
    current_tenant_id = str(tenant_context.tenant.id) if tenant_context is not None else None
    current_user_is_super_admin = tenant_service.is_platform_super_admin(current_user) if current_user is not None else False
    _, messages = list_messages_for_conversation(
        db,
        id,
        owner_user_id=get_owner_user_id(current_user),
        current_user=current_user_is_super_admin,
        current_tenant=current_tenant_id,
    )
    return messages
