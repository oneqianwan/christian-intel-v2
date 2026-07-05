import json
import os
import re
import sys
import uuid

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import func, or_

from models.database import IntelligenceItem, Investor, KnowledgeEntity, OrganizationProfile, RelationEdge, SessionLocal
from services.llm_client import call_llm

db = SessionLocal()

RELATION_PROMPT = """从以下新闻标题和摘要中提取机构间关系。

标题：{title}
摘要：{summary}
来源：{source}

提取规则：
1. 识别涉及的两个或多个机构名称
2. 判断关系类型：
   - "partnered_with" = 合作/伙伴关系
   - "acquired" = 收购
   - "merged_with" = 合并
   - "collaborated" = 协作/项目合作
   - "affiliated" = 附属/隶属
   - "funded" = 资助/投资（如果投资方是基金会/捐赠方）
3. 如果无法确定具体关系类型，用"associated"
4. 如果没有明确的机构间关系，返回NONE

输出格式（严格JSON）：
{{
    "relations": [
        {{
            "source_name": "机构A名称",
            "target_name": "机构B名称",
            "relation_type": "关系类型",
            "confidence": 0.0-1.0
        }}
    ]
}}

如果无关系，返回：{{"relations": []}}
"""

NOISE_SOURCES = {"ARDA_Denomination", "ARDA", "PewResearch", "JoshuaProject"}
KEYWORDS = ["partner", "partnership", "collaborate", "acquire", "merger", "alliance", "join", "merge", "fund"]


def find_entity_id(name):
    """根据名称查找实体ID。"""
    if not name or len(name) < 3:
        return None, None

    org = (
        db.query(OrganizationProfile)
        .filter(
            or_(
                OrganizationProfile.name.ilike(f"%{name}%"),
                OrganizationProfile.english_name.ilike(f"%{name}%"),
                OrganizationProfile.official_name.ilike(f"%{name}%"),
                OrganizationProfile.short_name.ilike(f"%{name}%"),
            )
        )
        .first()
    )
    if org:
        return org.id, "organization"

    entity = db.query(KnowledgeEntity).filter(KnowledgeEntity.name.ilike(f"%{name}%")).first()
    if entity:
        return entity.id, "knowledge_entity"

    investor = db.query(Investor).filter(Investor.name.ilike(f"%{name}%")).first()
    if investor:
        return str(investor.id), "investor"

    return None, None


def parse_relation_json(response: str):
    if not response:
        return None
    try:
        return json.loads(response)
    except Exception:
        pass

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            return None
    return None


def is_likely_relation_item(item: IntelligenceItem) -> bool:
    text = " ".join([item.title or "", item.content or "", item.entity_name or "", item.source_name or ""]).lower()
    return any(keyword in text for keyword in KEYWORDS)


def main():
    items = []
    for keyword in KEYWORDS:
        hits = db.query(IntelligenceItem).filter(IntelligenceItem.title.ilike(f"%{keyword}%")).all()
        items.extend(hits)

    seen_ids = set()
    unique_items = []
    for item in items:
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        unique_items.append(item)

    filtered_items = [
        item
        for item in unique_items
        if (item.source_name or "") not in NOISE_SOURCES and is_likely_relation_item(item)
    ]

    print(f"待处理新闻: {len(filtered_items)}条")

    extracted = 0
    failed = 0
    skipped = 0

    for item in filtered_items:
        title = item.title or ""
        summary = (item.content or "")[:500]

        if len(title) + len(summary) < 20:
            skipped += 1
            continue

        try:
            prompt = RELATION_PROMPT.format(
                title=title[:200],
                summary=summary,
                source=item.source_name or "Unknown",
            )
            response = call_llm(prompt, max_tokens=400, temperature=0.1)
            result = parse_relation_json(response)

            if not result or "relations" not in result:
                failed += 1
                continue

            relations = result["relations"]
            if not relations:
                skipped += 1
                continue

            for relation in relations:
                source_name = str(relation.get("source_name", "")).strip()
                target_name = str(relation.get("target_name", "")).strip()
                relation_type = str(relation.get("relation_type", "associated")).strip() or "associated"
                confidence = float(relation.get("confidence", 0.5) or 0.5)

                source_id, source_type = find_entity_id(source_name)
                target_id, target_type = find_entity_id(target_name)
                if not source_id or not target_id:
                    continue
                if source_id == target_id:
                    continue

                existing = (
                    db.query(RelationEdge)
                    .filter(
                        RelationEdge.source_id == str(source_id),
                        RelationEdge.target_id == str(target_id),
                        RelationEdge.relation_type == relation_type,
                        RelationEdge.source_item == str(item.id),
                    )
                    .first()
                )
                if existing:
                    continue

                edge = RelationEdge(
                    id=str(uuid.uuid4()),
                    source_id=str(source_id),
                    source_type=source_type,
                    target_id=str(target_id),
                    target_type=target_type,
                    relation_type=relation_type,
                    confidence=min(max(confidence, 0.1), 0.8),
                    source_item=str(item.id),
                    source_type_detail="news",
                    properties_json=json.dumps({"title": title[:100]}, ensure_ascii=False),
                )
                db.add(edge)
                extracted += 1
        except Exception:
            failed += 1
            continue

    db.commit()

    total = db.query(RelationEdge).count()
    by_type = db.query(RelationEdge.relation_type, func.count()).group_by(RelationEdge.relation_type).all()

    print("\n抽取完成:")
    print(f"  成功抽取: {extracted}条")
    print(f"  失败: {failed}条")
    print(f"  跳过: {skipped}条")
    print(f"\nRelationEdge总数: {total}")
    for relation_type, count in by_type:
        print(f"  {relation_type}: {count}")

    db.close()


if __name__ == "__main__":
    main()
