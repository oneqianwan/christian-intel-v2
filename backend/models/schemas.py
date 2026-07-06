from pydantic import BaseModel, Field
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


class LoginRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class AuthUserResponse(BaseModel):
    public_id: str
    email: str
    display_name: str
    role: str
    status: str


class LoginResponse(BaseModel):
    user: AuthUserResponse


class LogoutResponse(BaseModel):
    success: bool = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class ChangePasswordResponse(BaseModel):
    success: bool = True
    reauthentication_required: bool = True


class LogoutAllResponse(BaseModel):
    success: bool = True
    revoked_count: int
