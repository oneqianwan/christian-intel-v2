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
    default_tenant_id: Optional[str] = None


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


class SetupPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class SetupPasswordResponse(BaseModel):
    success: bool = True
    login_allowed: bool = True


class PasswordResetRequestPayload(BaseModel):
    email: str = Field(min_length=1, max_length=320)


class PasswordResetRequestResponse(BaseModel):
    success: bool = True
    message: str
    reset_token: Optional[str] = None
    expires_at: Optional[datetime] = None


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class PasswordResetConfirmResponse(BaseModel):
    success: bool = True
    reauthentication_required: bool = True


AdminUserRole = Literal["super_admin", "admin", "analyst", "viewer"]
AdminUserStatus = Literal["active", "disabled", "pending"]


class AdminUserResponse(BaseModel):
    public_id: str
    email: str
    display_name: str
    role: str
    status: str
    default_tenant_id: Optional[str] = None
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


class AdminUserCreateRequest(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    display_name: str = Field(min_length=1, max_length=120)
    role: AdminUserRole
    status: Literal["active", "pending"] = "pending"
    tenant_id: Optional[str] = Field(default=None, min_length=1, max_length=120)


class AdminUserProvisionResponse(BaseModel):
    user: AdminUserResponse
    setup_token: Optional[str] = None
    setup_expires_at: Optional[datetime] = None


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


RecommendationPriority = Literal["high", "medium", "low"]
RecommendationNextAction = Literal["research_more", "contact", "review_manually", "skip"]


class PartnershipRecommendationOrganization(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class PartnershipRecommendationTargetOrg(BaseModel):
    id: str
    name: str
    country: Optional[str] = None
    city: Optional[str] = None
    denomination: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class RecommendationScoreSnapshot(BaseModel):
    people_score: Optional[int] = None
    digital_score: Optional[int] = None
    intel_score: Optional[int] = None


class RecommendationRelationshipSnapshot(BaseModel):
    has_relationship_path: bool = False
    relationship_count: int = 0
    strongest_relationship_type: Optional[str] = None
    relationship_path_summary: List[str]


class RecommendationContactSnapshot(BaseModel):
    has_website: bool = False
    has_email: bool = False
    has_phone: bool = False
    has_social: bool = False
    contact_count: int = 0
    verified_contact_count: int = 0
    missing_source_count: int = 0


class PartnershipRecommendationItem(BaseModel):
    target_org: PartnershipRecommendationTargetOrg
    recommendation_score: int
    priority: RecommendationPriority
    confidence: float
    reason_codes: List[str]
    explanation: str
    score_snapshot: RecommendationScoreSnapshot
    relationship_snapshot: RecommendationRelationshipSnapshot
    contact_snapshot: RecommendationContactSnapshot
    risks: List[str]
    warnings: List[str]
    recommended_next_action: RecommendationNextAction


class PartnershipRecommendationSummary(BaseModel):
    candidate_count: int
    recommended_count: int
    high_priority_count: int
    with_contact_count: int
    with_relationship_path_count: int
    warning_count: int


class PartnershipRecommendationPayload(BaseModel):
    organization: Optional[PartnershipRecommendationOrganization] = None
    summary: PartnershipRecommendationSummary
    recommendations: List[PartnershipRecommendationItem]
    warnings: List[str]
    found: bool = True


ActionPlanRecommendedChannel = Literal["email", "website", "phone", "social", "research_first", "manual_review"]
ActionPlanRiskLevel = Literal["low", "medium", "high"]
ActionPlanStepType = Literal["research", "verify_contact", "review_relationship", "prepare_outreach", "contact", "monitor", "skip"]
ActionPlanStepChannel = Literal["email", "website", "phone", "social", "internal_review", "none"]
ActionPlanContactType = Literal["email", "phone", "website", "social_profile", "none"]
ActionPlanStepPriority = Literal["high", "medium", "low"]


class PartnershipActionPlanOrganization(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class PartnershipActionPlanTargetOrg(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class PartnershipActionPlanSummary(BaseModel):
    plan_available: bool
    step_count: int
    blocked: bool
    block_reasons: List[str]
    recommended_channel: ActionPlanRecommendedChannel
    risk_level: ActionPlanRiskLevel
    confidence: float


class PartnershipActionPlanUsesContact(BaseModel):
    type: ActionPlanContactType = "none"
    value: Optional[str] = None
    source_url: Optional[str] = None
    is_verified: bool = False


class PartnershipActionPlanStep(BaseModel):
    step_number: int
    action_type: ActionPlanStepType
    title: str
    description: str
    channel: ActionPlanStepChannel
    depends_on: List[int]
    required_evidence: List[str]
    uses_contact: PartnershipActionPlanUsesContact
    risk_flags: List[str]
    success_criteria: List[str]
    do_not_proceed_if: List[str]
    priority: ActionPlanStepPriority


class PartnershipActionRecommendationSnapshot(BaseModel):
    target_org_id: Optional[str] = None
    target_org_name: Optional[str] = None
    recommendation_score: int = 0
    priority: RecommendationPriority = "low"
    confidence: float = 0.0
    reason_codes: List[str]
    risks: List[str]
    warnings: List[str]
    recommended_next_action: RecommendationNextAction = "research_more"


class PartnershipActionPlanEvidence(BaseModel):
    score_snapshot: RecommendationScoreSnapshot
    relationship_snapshot: RecommendationRelationshipSnapshot
    contact_snapshot: RecommendationContactSnapshot
    recommendation_snapshot: PartnershipActionRecommendationSnapshot


class PartnershipActionPlanPayload(BaseModel):
    organization: PartnershipActionPlanOrganization
    target_org: Optional[PartnershipActionPlanTargetOrg] = None
    summary: PartnershipActionPlanSummary
    action_plan: List[PartnershipActionPlanStep]
    evidence: PartnershipActionPlanEvidence
    warnings: List[str]


EvidenceBriefDecision = Literal["proceed", "research_more", "manual_review", "do_not_contact"]
EvidenceBriefPriority = Literal["high", "medium", "low"]
EvidenceBriefRiskSeverity = Literal["low", "medium", "high"]


class PartnershipEvidenceBriefOrganization(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    updated_at: Optional[datetime] = None


class PartnershipEvidenceBriefTargetOrg(BaseModel):
    id: str
    name: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None


class PartnershipEvidenceBriefSummary(BaseModel):
    brief_available: bool
    decision: EvidenceBriefDecision
    priority: EvidenceBriefPriority
    confidence: float
    risk_level: EvidenceBriefRiskSeverity
    evidence_count: int
    missing_evidence_count: int
    recommended_channel: Optional[ActionPlanRecommendedChannel] = None


class PartnershipEvidenceDecisionRationale(BaseModel):
    headline: str
    reason_codes: List[str]
    supporting_points: List[str]
    limiting_factors: List[str]


class PartnershipEvidenceScoreSection(BaseModel):
    people_score: Optional[int] = None
    digital_score: Optional[int] = None
    intel_score: Optional[int] = None
    strengths: List[str]
    weaknesses: List[str]
    warnings: List[str]


class PartnershipEvidenceRelationshipSection(BaseModel):
    has_relationship_path: bool = False
    relationship_count: int = 0
    strongest_relationship_type: Optional[str] = None
    relationship_path_summary: List[str]
    warnings: List[str]


class PartnershipEvidenceContactSection(BaseModel):
    has_website: bool = False
    has_email: bool = False
    has_phone: bool = False
    has_social: bool = False
    contact_count: int = 0
    verified_contact_count: int = 0
    missing_source_count: int = 0
    recommended_contact: Optional[PartnershipActionPlanUsesContact] = None
    warnings: List[str]


class PartnershipEvidenceRecommendationSection(BaseModel):
    recommendation_score: Optional[int] = None
    priority: Optional[RecommendationPriority] = None
    confidence: float = 0.0
    reason_codes: List[str]
    risks: List[str]
    warnings: List[str]


class PartnershipEvidenceActionPlanSection(BaseModel):
    plan_available: bool = False
    blocked: bool = False
    step_count: int = 0
    recommended_channel: Optional[ActionPlanRecommendedChannel] = None
    risk_level: Optional[ActionPlanRiskLevel] = None
    first_steps: List[str]
    warnings: List[str]


class PartnershipEvidenceSections(BaseModel):
    score_evidence: PartnershipEvidenceScoreSection
    relationship_evidence: PartnershipEvidenceRelationshipSection
    contact_evidence: PartnershipEvidenceContactSection
    recommendation_evidence: PartnershipEvidenceRecommendationSection
    action_plan_evidence: PartnershipEvidenceActionPlanSection


class PartnershipEvidenceRiskItem(BaseModel):
    risk_code: str
    severity: EvidenceBriefRiskSeverity
    description: str
    mitigation: str


class PartnershipEvidenceAudit(BaseModel):
    generated_by: str
    no_llm: bool = True
    source_modules: List[str]
    missing_modules: List[str]


class PartnershipEvidenceBriefPayload(BaseModel):
    organization: PartnershipEvidenceBriefOrganization
    target_org: Optional[PartnershipEvidenceBriefTargetOrg] = None
    summary: PartnershipEvidenceBriefSummary
    decision_rationale: PartnershipEvidenceDecisionRationale
    evidence_sections: PartnershipEvidenceSections
    risk_register: List[PartnershipEvidenceRiskItem]
    recommended_next_actions: List[str]
    do_not_proceed_if: List[str]
    audit: PartnershipEvidenceAudit
    warnings: List[str]
