from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from dependencies.auth import (
    normalize_role_value,
    require_admin,
    require_auth_enabled,
    require_super_admin,
)
from models.auth import User
from models.database import Mission, get_db
from models.schemas import (
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserRoleUpdateRequest,
    AdminUserSessionRevokeResponse,
    AdminUserStatusUpdateRequest,
    ScoreDraftApprovalRequest,
    ScoreDraftApprovalResponse,
)
from schemas.watch_alert import ApiErrorResponse
from services.auth_service import revoke_all_user_sessions
from services import score_draft_service


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_auth_enabled)])

USER_STATUS_VALUES: tuple[str, ...] = ("active", "disabled", "pending")
APPROVAL_REJECTION_REASONS: frozenset[str] = frozenset(
    {
        "not_approved",
        "mission_not_completed",
        "missing_evidence",
        "existing_score_preserved",
        "organization_not_found",
        "invalid_score_range",
        "score_draft_rebuild_failed",
    }
)


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _normalize_status_value(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized not in USER_STATUS_VALUES:
        return None
    return normalized


def _get_mission_or_none(db: Session, *, mission_id: str) -> Mission | None:
    return db.query(Mission).filter(Mission.id == str(mission_id)).first()


def _normalize_score_draft_approval_reason(reason: str | None) -> str:
    normalized = str(reason or "").strip()
    if normalized in APPROVAL_REJECTION_REASONS:
        return normalized
    if normalized in {"ambiguous_organization", "organization_not_found"}:
        return "organization_not_found"
    return "score_draft_rebuild_failed"


def _score_draft_approval_failure(reason: str) -> ScoreDraftApprovalResponse:
    return ScoreDraftApprovalResponse(
        success=False,
        writeback=False,
        reason=_normalize_score_draft_approval_reason(reason),
    )


def _serialize_user(user: User) -> AdminUserResponse:
    return AdminUserResponse(
        public_id=str(user.public_id),
        email=str(user.email),
        display_name=str(user.display_name),
        role=str(user.role),
        status=str(user.status),
        email_verified_at=user.email_verified_at,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _get_user_or_404(db: Session, *, public_id: str) -> User:
    user = (
        db.query(User)
        .filter(User.public_id == str(public_id), User.deleted_at.is_(None))
        .first()
    )
    if user is None:
        _raise_api_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "User not found")
    return user


def _count_active_super_admins(db: Session) -> int:
    count = (
        db.query(User)
        .filter(
            User.deleted_at.is_(None),
            User.role == "super_admin",
            User.status == "active",
        )
        .count()
    )
    return int(count or 0)


def _assert_role_change_allowed(*, db: Session, actor: User, target: User, new_role: str) -> None:
    current_role = normalize_role_value(getattr(target, "role", None))
    normalized_new_role = normalize_role_value(new_role)
    if current_role is None or normalized_new_role is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")

    if str(actor.id) == str(target.id) and normalized_new_role != current_role:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "SELF_DEMOTION_FORBIDDEN", "Cannot change your own role")

    if (
        current_role == "super_admin"
        and normalized_new_role != "super_admin"
        and str(getattr(target, "status", "")).strip().lower() == "active"
        and _count_active_super_admins(db) <= 1
    ):
        _raise_api_error(
            status.HTTP_403_FORBIDDEN,
            "LAST_SUPER_ADMIN_PROTECTED",
            "Cannot change the last active super admin",
        )


def _assert_status_change_allowed(*, db: Session, actor: User, target: User, new_status: str) -> None:
    actor_role = normalize_role_value(getattr(actor, "role", None))
    target_role = normalize_role_value(getattr(target, "role", None))
    current_status = _normalize_status_value(getattr(target, "status", None))
    normalized_new_status = _normalize_status_value(new_status)

    if actor_role is None or target_role is None or current_status is None or normalized_new_status is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")

    if str(actor.id) == str(target.id) and normalized_new_status != current_status:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "SELF_DISABLE_FORBIDDEN", "Cannot change your own status")

    if actor_role == "admin" and target_role not in {"analyst", "viewer"}:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")

    if (
        target_role == "super_admin"
        and current_status == "active"
        and normalized_new_status != "active"
        and _count_active_super_admins(db) <= 1
    ):
        _raise_api_error(
            status.HTTP_403_FORBIDDEN,
            "LAST_SUPER_ADMIN_PROTECTED",
            "Cannot change the last active super admin",
        )


def _assert_session_revoke_allowed(*, actor: User, target: User) -> None:
    actor_role = normalize_role_value(getattr(actor, "role", None))
    target_role = normalize_role_value(getattr(target, "role", None))

    if actor_role is None or target_role is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")

    if str(actor.id) == str(target.id):
        _raise_api_error(
            status.HTTP_403_FORBIDDEN,
            "SELF_SESSION_REVOKE_FORBIDDEN",
            "Cannot revoke your own sessions via admin API",
        )

    if actor_role == "admin" and target_role not in {"analyst", "viewer"}:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    role: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    email: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    normalized_role = None
    if role is not None:
        normalized_role = normalize_role_value(role)
        if normalized_role is None:
            _raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_ROLE", "Invalid role")

    normalized_status = None
    if status_value is not None:
        normalized_status = _normalize_status_value(status_value)
        if normalized_status is None:
            _raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_STATUS", "Invalid status")

    query = db.query(User).filter(User.deleted_at.is_(None))
    if normalized_role is not None:
        query = query.filter(User.role == normalized_role)
    if normalized_status is not None:
        query = query.filter(User.status == normalized_status)
    if email is not None and str(email).strip():
        query = query.filter(User.email_normalized.contains(str(email).strip().lower()))

    total = int(query.count())
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    return AdminUserListResponse(
        items=[_serialize_user(user) for user in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(
    user_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, public_id=user_id)
    return _serialize_user(user)


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def update_user_role(
    user_id: str,
    payload: AdminUserRoleUpdateRequest,
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, public_id=user_id)
    _assert_role_change_allowed(db=db, actor=current_user, target=user, new_role=payload.role)

    normalized_new_role = normalize_role_value(payload.role)
    if normalized_new_role is None:
        _raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_ROLE", "Invalid role")

    user.role = normalized_new_role
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.patch("/users/{user_id}/status", response_model=AdminUserResponse)
def update_user_status(
    user_id: str,
    payload: AdminUserStatusUpdateRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, public_id=user_id)
    _assert_status_change_allowed(db=db, actor=current_user, target=user, new_status=payload.status)

    normalized_new_status = _normalize_status_value(payload.status)
    if normalized_new_status is None:
        _raise_api_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "INVALID_STATUS", "Invalid status")

    user.status = normalized_new_status
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.post("/users/{user_id}/sessions/revoke", response_model=AdminUserSessionRevokeResponse)
def revoke_user_sessions(
    user_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, public_id=user_id)
    _assert_session_revoke_allowed(actor=current_user, target=user)

    revoked_count = revoke_all_user_sessions(db, user_id=user.id)
    db.commit()
    return AdminUserSessionRevokeResponse(success=True, revoked_count=int(revoked_count))


@router.post("/score-drafts/{mission_id}/approve", response_model=ScoreDraftApprovalResponse)
def approve_score_draft(
    mission_id: str,
    payload: ScoreDraftApprovalRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    del current_user

    if not payload.approved:
        return _score_draft_approval_failure("not_approved")

    mission = _get_mission_or_none(db, mission_id=mission_id)
    if mission is None:
        return _score_draft_approval_failure("score_draft_rebuild_failed")

    mission_status = str(getattr(mission, "status", "") or "").strip().lower()
    if mission_status not in {"done", "completed"}:
        return _score_draft_approval_failure("mission_not_completed")

    rebuilt_draft = score_draft_service.create_score_draft_from_collection_result(
        mission=mission,
        db=db,
    )
    if not bool(rebuilt_draft.get("score_draft")):
        return _score_draft_approval_failure(str(rebuilt_draft.get("reason") or "score_draft_rebuild_failed"))

    result = score_draft_service.writeback_score_draft(
        mission=mission,
        score_draft=rebuilt_draft,
        approved=True,
        overwrite=bool(payload.overwrite),
        writeback_reason=payload.writeback_reason,
        writeback_source="admin_score_draft_approval_api",
        db=db,
    )
    if not bool(result.get("writeback")):
        return _score_draft_approval_failure(str(result.get("reason") or "score_draft_rebuild_failed"))

    return ScoreDraftApprovalResponse(
        success=True,
        writeback=True,
        mission_id=str(result.get("mission_id") or mission_id),
        organization_name=str(result.get("organization_name") or ""),
        scores_written=result.get("scores_written") if isinstance(result.get("scores_written"), dict) else {},
        writeback_source=str(result.get("writeback_source") or "admin_score_draft_approval_api"),
        writeback_reason=str(result.get("writeback_reason") or payload.writeback_reason),
        data_source=str(result.get("data_source") or "collection_result"),
    )
