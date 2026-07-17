import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from dependencies.tenant_context import TenantRequestContext, resolve_tenant_request_context
from dependencies.auth import require_authenticated_user
from models.auth import User
from models.database import Bookmark, IntelligenceItem, get_db
from schemas.watch_alert import ApiErrorResponse
from services import tenant_scope

router = APIRouter()


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


def _get_tenant_context(*, request: Request, current_user: User, db: Session) -> TenantRequestContext:
    context = resolve_tenant_request_context(request=request, user=current_user, db=db, fail_closed=True)
    if context is None:
        _raise_api_error(status.HTTP_403_FORBIDDEN, "TENANT_REQUIRED", "Tenant required")
    return context


def _get_bookmark_or_404(*, db: Session, bookmark_id: str, current_tenant_id: str) -> Bookmark:
    query = tenant_scope.filter_by_tenant(db.query(Bookmark), Bookmark, current_tenant_id)
    bookmark = query.filter(Bookmark.id == bookmark_id).first()
    if bookmark is None:
        _raise_api_error(status.HTTP_404_NOT_FOUND, "BOOKMARK_NOT_FOUND", "Bookmark not found")
    try:
        tenant_scope.require_record_tenant(bookmark, current_tenant_id)
    except tenant_scope.TenantScopeError as exc:
        _raise_api_error(exc.status_code, exc.error_code, exc.message)
    return bookmark


@router.post("/bookmarks")
def create_bookmark(
    request: Request,
    item_id: str,
    note: str = "",
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """收藏情报条目。"""
    tenant_context = _get_tenant_context(request=request, current_user=current_user, db=db)
    current_tenant_id = str(tenant_context.tenant.id)
    item = db.query(IntelligenceItem).filter(IntelligenceItem.id == item_id).first()
    if not item:
        return {"status": "not_found", "message": "intelligence item not found"}

    existing = (
        tenant_scope.filter_by_tenant(db.query(Bookmark), Bookmark, current_tenant_id)
        .filter(Bookmark.intelligence_item_id == item_id)
        .first()
    )
    if existing:
        existing.note = note
        db.commit()
        return {"status": "exists", "bookmark_id": existing.id}

    bookmark = Bookmark(
        id=str(uuid.uuid4()),
        tenant_id=tenant_scope.ensure_tenant_id_for_create({}, current_tenant_id).get("tenant_id"),
        user_id=str(current_user.id),
        intelligence_item_id=item_id,
        note=note,
    )
    db.add(bookmark)
    db.commit()
    return {"status": "created", "bookmark_id": bookmark.id}


@router.get("/bookmarks")
def list_bookmarks(
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """列出收藏的情报。"""
    tenant_context = _get_tenant_context(request=request, current_user=current_user, db=db)
    current_tenant_id = str(tenant_context.tenant.id)
    bookmarks = (
        tenant_scope.filter_by_tenant(db.query(Bookmark), Bookmark, current_tenant_id)
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    result = []
    for b in bookmarks:
        item = db.query(IntelligenceItem).filter(IntelligenceItem.id == b.intelligence_item_id).first()
        if item:
            result.append(
                {
                    "bookmark_id": b.id,
                    "item_id": item.id,
                    "title": item.title,
                    "note": b.note,
                    "created_at": b.created_at.isoformat(),
                }
            )
    return result


@router.get("/bookmarks/{bookmark_id}")
def get_bookmark(
    bookmark_id: str,
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """读取单个收藏。"""
    tenant_context = _get_tenant_context(request=request, current_user=current_user, db=db)
    bookmark = _get_bookmark_or_404(db=db, bookmark_id=bookmark_id, current_tenant_id=str(tenant_context.tenant.id))
    item = db.query(IntelligenceItem).filter(IntelligenceItem.id == bookmark.intelligence_item_id).first()
    return {
        "bookmark_id": bookmark.id,
        "item_id": bookmark.intelligence_item_id,
        "title": getattr(item, "title", None),
        "note": bookmark.note,
        "created_at": bookmark.created_at.isoformat(),
    }


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(
    bookmark_id: str,
    request: Request,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """取消收藏。"""
    tenant_context = _get_tenant_context(request=request, current_user=current_user, db=db)
    bookmark = _get_bookmark_or_404(db=db, bookmark_id=bookmark_id, current_tenant_id=str(tenant_context.tenant.id))
    db.delete(bookmark)
    db.commit()
    return {"status": "deleted"}
