import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from dependencies.auth import require_authenticated_user
from models.auth import User
from models.database import Bookmark, IntelligenceItem, get_db

router = APIRouter()


def _resolve_bookmark_user_id(current_user: User) -> str:
    return str(current_user.id)


@router.post("/bookmarks")
def create_bookmark(
    item_id: str,
    note: str = "",
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """收藏情报条目。"""
    bookmark_user_id = _resolve_bookmark_user_id(current_user)
    item = db.query(IntelligenceItem).filter(IntelligenceItem.id == item_id).first()
    if not item:
        return {"status": "not_found", "message": "intelligence item not found"}

    existing = (
        db.query(Bookmark)
        .filter(Bookmark.intelligence_item_id == item_id, Bookmark.user_id == bookmark_user_id)
        .first()
    )
    if existing:
        existing.note = note
        db.commit()
        return {"status": "exists", "bookmark_id": existing.id}

    bookmark = Bookmark(
        id=str(uuid.uuid4()),
        user_id=bookmark_user_id,
        intelligence_item_id=item_id,
        note=note,
    )
    db.add(bookmark)
    db.commit()
    return {"status": "created", "bookmark_id": bookmark.id}


@router.get("/bookmarks")
def list_bookmarks(
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """列出收藏的情报。"""
    bookmark_user_id = _resolve_bookmark_user_id(current_user)
    bookmarks = (
        db.query(Bookmark)
        .filter(Bookmark.user_id == bookmark_user_id)
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


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(
    bookmark_id: str,
    current_user: User = Depends(require_authenticated_user),
    db: Session = Depends(get_db),
):
    """取消收藏。"""
    bookmark_user_id = _resolve_bookmark_user_id(current_user)
    deleted = db.query(Bookmark).filter(Bookmark.id == bookmark_id, Bookmark.user_id == bookmark_user_id).delete()
    db.commit()
    return {"status": "deleted" if deleted else "not_found"}
