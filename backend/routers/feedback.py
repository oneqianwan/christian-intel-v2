from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.database import UserFeedback, get_db

router = APIRouter()


class FeedbackIn(BaseModel):
    feedback_type: str
    content: Optional[str] = ""
    related_entity: Optional[str] = None
    related_investor: Optional[str] = None


@router.post("/feedback")
def submit_feedback(
    feedback: FeedbackIn,
    db: Session = Depends(get_db),
    session_id: str = Header(default="session-1", alias="x-session-id"),
):
    """提交用户反馈"""
    record = UserFeedback(
        session_id=session_id or "session-1",
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


@router.get("/feedback/stats")
def get_feedback_stats(
    db: Session = Depends(get_db),
):
    """获取反馈统计（用于Learning Loop分析）"""
    total = db.query(UserFeedback).count()
    useful = db.query(UserFeedback).filter(UserFeedback.feedback_type == "match_useful").count()
    not_useful = db.query(UserFeedback).filter(UserFeedback.feedback_type == "match_not_useful").count()

    top_investors = (
        db.query(
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
