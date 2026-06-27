from typing import Any, Dict, List

from sqlalchemy import or_

from models.database import IntelligenceItem, SessionLocal


def query_global_intelligence(
    entities: List[str] | None,
    keywords: List[str] | None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """查询 scope='global' 的全球情报，并转换为统一结果结构。"""
    db = SessionLocal()
    try:
        query = db.query(IntelligenceItem).filter(IntelligenceItem.scope == "global")

        if entities:
            entity_conditions = []
            for entity in entities:
                entity_conditions.append(IntelligenceItem.title.ilike(f"%{entity}%"))
                entity_conditions.append(IntelligenceItem.content.ilike(f"%{entity}%"))
                entity_conditions.append(IntelligenceItem.entity_name.ilike(f"%{entity}%"))
            query = query.filter(or_(*entity_conditions))

        if keywords:
            keyword_conditions = []
            for keyword in keywords:
                keyword_conditions.append(IntelligenceItem.title.ilike(f"%{keyword}%"))
                keyword_conditions.append(IntelligenceItem.content.ilike(f"%{keyword}%"))
                keyword_conditions.append(IntelligenceItem.category.ilike(f"%{keyword}%"))
            query = query.filter(or_(*keyword_conditions))

        results = query.order_by(IntelligenceItem.ingested_at.desc()).limit(limit).all()
        if not results:
            results = (
                db.query(IntelligenceItem)
                .filter(IntelligenceItem.scope == "global")
                .order_by(IntelligenceItem.ingested_at.desc())
                .limit(limit)
                .all()
            )
        return [
            {
                "id": item.id,
                "name": item.entity_name or item.title or "全球情报",
                "type": item.entity_type or "intelligence",
                "country": item.country,
                "category": item.category or "global_intelligence",
                "data": {
                    "title": item.title,
                    "content": item.content,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "updated_at": item.ingested_at.isoformat() if item.ingested_at else None,
                },
                "source_url": item.source_url,
                "source_name": item.source_name,
                "scope": item.scope,
            }
            for item in results
        ]
    finally:
        db.close()
