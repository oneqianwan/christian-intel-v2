from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from dependencies.auth import require_authenticated_user
from dependencies.tenant_context import TenantRequestContext, resolve_tenant_request_context
from models.auth import User
from models.database import UserFeedback, get_db
from schemas.watch_alert import ApiErrorResponse
from services import tenant_scope, tenant_service

router = APIRouter()


class FeedbackIn(BaseModel):
    feedback_type: str
    content: Optional[str] = ""
    related_entity: Optional[str] = None
    related_investor: Optional[str] = None


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _has_explicit_tenant_selector(request: Request) -> bool:
    return bool(
        request.headers.get("X-Tenant-ID")
        or request.headers.get("X-Tenant-Slug")
        or request.query_params.get("tenant_id")
        or request.query_params.get("tenant_public_id")
        or request.query_params.get("tenant_slug")
    )


def _resolve_feedback_tenant_context(*, request: Request, current_user: User, db: Session) -> TenantRequestContext:
    context = resolve_tenant_request_context(request=request, user=current_user, db=db, fail_closed=True)
    if context is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "TENANT_REQUIRED", "Tenant required")
    return context


def _require_feedback_admin_scope(*, context: TenantRequestContext) -> None:
    if tenant_service.is_platform_super_admin(context.user):
        return
    if str(context.tenant_role or "").strip().lower() != "tenant_admin":
        _raise_api_error(status.HTTP_403_FORBIDDEN, "ROLE_FORBIDDEN", "Insufficient permissions")


def _feedback_query_for_tenant(*, db: Session, tenant_id: str):
    return tenant_scope.filter_by_tenant(db.query(UserFeedback), UserFeedback, tenant_id)


def _serialize_feedback_item(record: UserFeedback) -> dict:
    return {
        "id": int(record.id),
        "feedback_type": str(record.feedback_type),
        "content": str(record.content or ""),
        "related_entity": record.related_entity,
        "related_investor": record.related_investor,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _build_feedback_stats(query) -> dict:
    total = query.count()
    useful = query.filter(UserFeedback.feedback_type == "match_useful").count()
    not_useful = query.filter(UserFeedback.feedback_type == "match_not_useful").count()
    top_investors = (
        query.with_entities(
            UserFeedback.related_investor,
            func.count(UserFeedback.id).label("count"),
        )
        .filter(UserFeedback.feedback_type == "match_useful")
        .group_by(UserFeedback.related_investor)
        .order_by(func.count(UserFeedback.id).desc())
        .limit(5)
        .all()
    )
    return {
        "total_feedback": total,
        "useful_matches": useful,
        "not_useful_matches": not_useful,
        "top_recommended_investors": [
            {"name": name, "useful_count": count}
            for name, count in top_investors
            if name
        ],
    }


@router.post("/feedback")
def submit_feedback(
    feedback: FeedbackIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    """提交用户反馈"""
    tenant_context = _resolve_feedback_tenant_context(request=request, current_user=current_user, db=db)
    session_id = f"user:{current_user.id}"
    record = UserFeedback(
        session_id=session_id,
        tenant_id=tenant_scope.ensure_tenant_id_for_create({}, str(tenant_context.tenant.id)).get("tenant_id"),
        user_id=str(current_user.id),
        feedback_type=feedback.feedback_type,
        content=feedback.content or "",
        related_entity=feedback.related_entity,
        related_investor=feedback.related_investor,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {"status": "recorded", "feedback_id": record.id}


@router.get("/feedback")
def list_feedback(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """列出租户内反馈记录。"""
    tenant_context = _resolve_feedback_tenant_context(request=request, current_user=current_user, db=db)
    _require_feedback_admin_scope(context=tenant_context)
    query = _feedback_query_for_tenant(db=db, tenant_id=str(tenant_context.tenant.id))
    return [_serialize_feedback_item(record) for record in query.order_by(UserFeedback.created_at.desc()).all()]


@router.get("/feedback/stats")
def get_feedback_stats(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """获取反馈统计（用于Learning Loop分析）"""
    if tenant_service.is_platform_super_admin(current_user) and not _has_explicit_tenant_selector(request):
        stats = _build_feedback_stats(db.query(UserFeedback))
        stats["scope"] = "global"
        return stats

    tenant_context = _resolve_feedback_tenant_context(request=request, current_user=current_user, db=db)
    _require_feedback_admin_scope(context=tenant_context)
    stats = _build_feedback_stats(_feedback_query_for_tenant(db=db, tenant_id=str(tenant_context.tenant.id)))
    stats["scope"] = "tenant"
    return stats
