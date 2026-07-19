from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from dependencies.rate_limit import enforce_rate_limit_for_request
from models.database import IntelligenceItem, Source, get_db

router = APIRouter()


@router.get("/search")
def search_intelligence(request: Request, q: str, country: str | None = None, db: Session = Depends(get_db)):
    """搜索情报。"""
    enforce_rate_limit_for_request(request, rule_name="public_high_cost")
    query = (
        db.query(IntelligenceItem, Source.country.label("source_country"))
        .join(Source, IntelligenceItem.source_id == Source.id)
        .filter(
            or_(
                IntelligenceItem.title.ilike(f"%{q}%"),
                IntelligenceItem.content.ilike(f"%{q}%"),
            )
        )
    )

    if country:
        query = query.filter(Source.country == country)

    rows = query.order_by(IntelligenceItem.ingested_at.desc()).limit(20).all()

    return {
        "query": q,
        "count": len(rows),
        "results": [
            {
                "id": item.id,
                "title": item.title,
                "source": item.source_name,
                "country": source_country,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
            for item, source_country in rows
        ],
    }
