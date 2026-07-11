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


class GraphWarning(BaseModel):
    code: str
    message: str
    edge_id: Optional[str] = None
    org_id: Optional[str] = None
    organization_name: Optional[str] = None


class GraphCenterNode(BaseModel):
    id: str
    graph_id: str
    type: str
    name: str
    region: Optional[str] = None
    denomination: Optional[str] = None
    people_score: Optional[int] = None
    digital_score: Optional[int] = None
    intel_score: Optional[int] = None


class GraphNode(BaseModel):
    id: str
    entity_id: str
    type: str
    label: str
    name: str
    region: Optional[str] = None
    denomination: Optional[str] = None
    people_score: Optional[int] = None
    digital_score: Optional[int] = None
    intel_score: Optional[int] = None
    confidence: float = 0.0
    source_count: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str
    direction: str
    strength: Optional[float] = None
    confidence: float = 0.0
    is_verified: bool = False
    evidence_url: Optional[str] = None
    evidence_source: Optional[str] = None
    evidence_date: Optional[str] = None
    reason: str
    missing_evidence: bool = False


class GraphSummary(BaseModel):
    node_count: int
    edge_count: int
    verified_edge_count: int
    unverified_edge_count: int
    missing_evidence_count: int


class OrganizationGraphPayload(BaseModel):
    center: Optional[GraphCenterNode] = None
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    summary: GraphSummary
    warnings: List[GraphWarning]
    found: bool = True
    depth: int = 1
    limit: int = 50
    include_unverified: bool = False


class OrganizationRelationsResponse(BaseModel):
    total: int
    relations: List[Dict[str, Any]]
    graph: OrganizationGraphPayload


ContactVerificationStatus = Literal["unverified", "verified", "likely"]
ContactUsage = Literal["research", "outreach_candidate"]


class OrganizationContactOrganization(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    organization_confidence: Optional[float] = None
    updated_at: Optional[datetime] = None


class OrganizationContactItem(BaseModel):
    id: str
    type: str
    label: str
    value: str
    normalized_value: str
    platform: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    confidence: Optional[float] = None
    verification_status: ContactVerificationStatus = "unverified"
    is_verified: bool = False
    usage: ContactUsage
    warnings: List[str]


class OrganizationContactSummary(BaseModel):
    contact_count: int
    email_count: int
    phone_count: int
    social_count: int
    website_count: int
    verified_count: int
    missing_source_count: int
    outreach_candidate_count: int


class OrganizationContactPayload(BaseModel):
    organization: Optional[OrganizationContactOrganization] = None
    contacts: List[OrganizationContactItem]
    summary: OrganizationContactSummary
    warnings: List[str]
    found: bool = True
