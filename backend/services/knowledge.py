from sqlalchemy.orm import Session
from models.database import KnowledgeEntity
from typing import List, Dict, Any

def query_knowledge(db: Session, query: str, country: str = None) -> List[Dict[str, Any]]:
    results = db.query(KnowledgeEntity).filter(
        KnowledgeEntity.name.ilike(f"%{query}%")
    ).limit(10).all()
    
    if not results and country:
        results = db.query(KnowledgeEntity).filter(
            KnowledgeEntity.country.ilike(f"%{country}%")
        ).limit(10).all()
    
    return [
        {
            "id": r.id, "name": r.name, "type": r.entity_type,
            "country": r.country, "category": r.category,
            "data": r.data, "source_url": r.source_url,
            "source_name": r.source_name,
        }
        for r in results
    ]