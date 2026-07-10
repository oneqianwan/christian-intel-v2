from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
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


AdminUserRole = Literal["super_admin", "admin", "analyst", "viewer"]
AdminUserStatus = Literal["active", "disabled", "pending"]


class AdminUserResponse(BaseModel):
    public_id: str
    email: str
    display_name: str
    role: str
    status: str
    email_verified_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    items: List[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminUserRoleUpdateRequest(BaseModel):
    role: AdminUserRole


class AdminUserStatusUpdateRequest(BaseModel):
    status: AdminUserStatus


class AdminUserSessionRevokeResponse(BaseModel):
    success: bool = True
    revoked_count: int


ScoreDraftApprovalFailureReason = Literal[
    "not_approved",
    "mission_not_completed",
    "missing_evidence",
    "existing_score_preserved",
    "organization_not_found",
    "invalid_score_range",
    "score_draft_rebuild_failed",
]


class ScoreDraftApprovalRequest(BaseModel):
    approved: bool = False
    writeback_reason: str = Field(min_length=1, max_length=255)
    overwrite: bool = False


class ScoreDraftApprovalResponse(BaseModel):
    success: bool
    writeback: bool
    mission_id: Optional[str] = None
    organization_name: Optional[str] = None
    scores_written: Optional[Dict[str, int]] = None
    writeback_source: Optional[str] = None
    writeback_reason: Optional[str] = None
    data_source: Optional[str] = None
    reason: Optional[ScoreDraftApprovalFailureReason] = None
