import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from models.database import IntelligenceItem

ENTITY_SEARCH_ALIASES = {
    "菲律宾": {
        "Victory": "Victory Philippines",
        "CCF": "Christ's Commission Fellowship",
    }
}

FAITH_KEYWORDS = [
    "church",
    "churches",
    "christian",
    "christ",
    "evangelical",
    "fellowship",
    "ministry",
    "ministries",
    "pastor",
    "gospel",
    "bible",
    "philippines",
    "pcec",
]


def resolve_entity_keyword(entity: str, country: str | None = None) -> str:
    if country and country in ENTITY_SEARCH_ALIASES:
        return ENTITY_SEARCH_ALIASES[country].get(entity, entity)
    return entity


def extract_entities(query: str) -> List[str]:
    """从查询中提取要对比的实体名称"""
    quoted = re.findall(r'"([^"]+)"', query)
    if quoted:
        return quoted

    english_terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]*", query)
    if len(english_terms) >= 2:
        return english_terms[:2]

    words = (
        query.replace("和", " ")
        .replace("与", " ")
        .replace("vs", " ")
        .replace("VS", " ")
        .replace("versus", " ")
        .replace("对比", " ")
        .replace("比较", " ")
        .replace("趋势", " ")
        .replace("变化", " ")
        .replace("增长", " ")
        .replace("发展", " ")
        .replace("动态", " ")
    )
    words = re.sub(r"近\S*(天|周|月)", " ", words)
    candidates = [word.strip() for word in words.split() if len(word.strip()) > 2]
    return candidates[:2]


def _build_field_filters(keyword: str):
    keyword_like = f"%{keyword}%"
    return or_(
        IntelligenceItem.title.ilike(keyword_like),
        IntelligenceItem.source_name.ilike(keyword_like),
        IntelligenceItem.entity_name.ilike(keyword_like),
        IntelligenceItem.content.ilike(keyword_like),
    )


def _build_faith_context_filters():
    return or_(*[
        or_(
            IntelligenceItem.title.ilike(f"%{token}%"),
            IntelligenceItem.source_name.ilike(f"%{token}%"),
            IntelligenceItem.entity_name.ilike(f"%{token}%"),
            IntelligenceItem.content.ilike(f"%{token}%"),
        )
        for token in FAITH_KEYWORDS
    ])


def _serialize_items(items: list[IntelligenceItem]) -> list[dict]:
    return [
        {
            "title": item.title,
            "source": item.source_name,
            "url": item.source_url,
            "date": item.ingested_at.isoformat() if item.ingested_at else None,
        }
        for item in items
    ]


def compare_entities(db: Session, entities: List[str], days: int = 30, country: str | None = None) -> Dict[str, Any]:
    """对比多个实体的近期情报"""
    since = datetime.utcnow() - timedelta(days=days)

    entity_results: Dict[str, List[Dict[str, Any]]] = {}
    for entity in entities:
        resolved_entity = resolve_entity_keyword(entity, country)
        base_filters = [_build_field_filters(resolved_entity)]
        if resolved_entity != entity:
            base_filters.append(
                and_(
                    _build_field_filters(entity),
                    _build_faith_context_filters(),
                )
            )

        query = db.query(IntelligenceItem).filter(
            or_(*base_filters),
            IntelligenceItem.ingested_at >= since,
            ~IntelligenceItem.title.ilike("Comment on %"),
            or_(
                IntelligenceItem.source_url.is_(None),
                ~IntelligenceItem.source_url.ilike("%#comment-%"),
            ),
        )

        if country:
            query = query.filter(
                or_(
                    IntelligenceItem.country == country,
                    IntelligenceItem.country.is_(None),
                )
            )

        items = query.order_by(IntelligenceItem.ingested_at.desc()).limit(10).all()
        entity_results[entity] = _serialize_items(items)

    summary_parts = [f"## 实体对比分析：{' vs '.join(entities)}\n\n"]
    summary_parts.append(f"时间范围：近{days}天\n\n")

    for entity, items in entity_results.items():
        summary_parts.append(f"### {entity}")
        summary_parts.append(f"相关情报数：{len(items)}")
        if items:
            for item in items[:3]:
                if item["url"]:
                    summary_parts.append(f"- [{item['title']}]({item['url']})")
                else:
                    summary_parts.append(f"- {item['title']}")
        else:
            summary_parts.append("- 暂无相关情报")
        summary_parts.append("")

    total_items = sum(len(items) for items in entity_results.values())
    if total_items == 0:
        summary_parts.append("**结论**：当前时间范围内未找到相关情报，建议扩展时间范围或检查实体名称。")
    else:
        most_active = max(entity_results.items(), key=lambda item: len(item[1]))
        summary_parts.append(f"**结论**：{most_active[0]} 在近期情报中出现频率最高（{len(most_active[1])}条）。")

    return {
        "content": "\n".join(summary_parts),
        "entities": entities,
        "entity_results": entity_results,
        "total_items": total_items,
    }
