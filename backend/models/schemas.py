from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str

class ConversationCreate(BaseModel):
    title: str = "新会话"

class ConversationResponse(BaseModel):
    id: str
    title: str
    is_pinned: bool = False
    pinned_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: Optional[str]
    sources: List[Dict]
    delivery_type: str
    status: str
    created_at: datetime
