"""
从新闻内容提取机构合作关系 — Phase 3 Day 2
LLM批量处理已有 intelligence_items，提取“A与B合作”等关系
"""

import json
import os
import re
import sys
from typing import Any, Dict, List

from sqlalchemy import text

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from models.database import SessionLocal

try:
    from backend.services.llm_client import call_llm
except ImportError:
    from services.llm_client import call_llm


RELATION_PROMPT = """你是一个基督教行业关系提取专家。

请从以下新闻内容中提取所有提到的机构之间的合作关系。

新闻标题: {title}
新闻内容:
{content}

请提取以下类型的关系：
1. 合作关系（partner/collaborate/join/launch together）
2. 投资关系（invest/funding/raise/grant）
3. 隶属关系（affiliate/member of/part of）
4. 活动关系（host conference together/speak at）

要求：
- 只提取明确的、有具体机构名的关系
- 如果提到 "Victory Philippines" 和 "Every Nation" 合作，输出两者关系
- 不要猜测，不确定的不要输出
- 每个关系包含：from（机构A）、to（机构B）、type（关系类型）、evidence（原文证据）

输出格式（严格JSON数组）：
[
  {{"from": "Victory Philippines", "to": "Every Nation", "type": "cooperation", "evidence": "Victory Philippines partners with Every Nation to..."}},
  {{"from": "FaithTech Startup", "to": "Greylock", "type": "funding", "evidence": "raised $2M from Greylock"}}
]

如果没有找到明确的关系，输出空数组 []。
只输出JSON，不要其他文字。
"""


def _clean_json_text(response: str) -> str:
    if not response:
        return ""
    cleaned = response.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^```\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _normalize_relation_type(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "cooperation": "cooperation",
        "collaboration": "cooperation",
        "partnership": "cooperation",
        "partner": "cooperation",
        "funding": "funding",
        "investment": "funding",
        "invest": "funding",
        "grant": "funding",
        "affiliation": "affiliation",
        "affiliate": "affiliation",
        "membership": "affiliation",
        "member": "affiliation",
        "event": "event",
        "conference": "event",
        "speaking": "event",
    }
    return mapping.get(raw, raw or "other")


def extract_relations(title: str, content: str) -> List[Dict[str, str]]:
    """LLM提取关系。"""
    if not content or len(content) < 50:
        return []

    prompt = RELATION_PROMPT.format(
        title=title or "Untitled",
        content=content[:4000],
    )

    try:
        response = call_llm(prompt, max_tokens=800, temperature=0.1)
        cleaned = _clean_json_text(response)
        json_match = re.search(r"\[[\s\S]*\]", cleaned)
        if not json_match:
            return []

        relations = json.loads(json_match.group(0))
        if not isinstance(relations, list):
            return []

        valid: List[Dict[str, str]] = []
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            if not all(k in rel for k in ["from", "to", "type", "evidence"]):
                continue

            from_org = str(rel.get("from", "")).strip()
            to_org = str(rel.get("to", "")).strip()
            relation_type = _normalize_relation_type(str(rel.get("type", "")))
            evidence = str(rel.get("evidence", "")).strip()

            if from_org == to_org or len(from_org) <= 2 or len(to_org) <= 2:
                continue
            if not evidence:
                continue

            valid.append(
                {
                    "from": from_org,
                    "to": to_org,
                    "type": relation_type,
                    "evidence": evidence[:200],
                }
            )

        return valid
    except Exception:
        return []


def process_intelligence_items(batch_size: int = 50) -> Dict[str, Any]:
    """批量处理情报项提取关系。"""
    db = SessionLocal()
    try:
        print("=" * 60)
        print(f"从新闻提取合作关系 (batch={batch_size})")
        print("=" * 60)

        rows = db.execute(
            text(
                """
                SELECT id, title, content, source_name, country
                FROM intelligence_items
                WHERE source_name NOT IN ('ARDA', 'PewResearch', 'JoshuaProject', 'ARDA_Denomination')
                  AND (relations_extracted IS NULL OR relations_extracted = 0)
                  AND content IS NOT NULL
                  AND LENGTH(content) > 200
                ORDER BY ingested_at DESC
                LIMIT :limit
                """
            ),
            {"limit": batch_size},
        ).fetchall()
        print(f"\n待处理: {len(rows)} 条新闻")

        total_relations = 0
        processed = 0

        for item_id, title, content, source, country in rows:
            relations = extract_relations(title, content)

            if relations:
                print(f"\n[{item_id}] {(title or '')[:50]}")
                for rel in relations:
                    print(f"  -> {rel['from']} --{rel['type']}--> {rel['to']}")
                    print(f"     证据: {rel['evidence'][:60]}...")
                    total_relations += 1
                    try:
                        db.execute(
                            text(
                                """
                                INSERT INTO intelligence_relations
                                (item_id, from_org, to_org, relation_type, evidence, created_at)
                                VALUES (:item_id, :from_org, :to_org, :rtype, :evidence, datetime('now'))
                                """
                            ),
                            {
                                "item_id": item_id,
                                "from_org": rel["from"],
                                "to_org": rel["to"],
                                "rtype": rel["type"],
                                "evidence": rel["evidence"],
                            },
                        )
                    except Exception:
                        pass

            db.execute(
                text("UPDATE intelligence_items SET relations_extracted = 1 WHERE id = :id"),
                {"id": item_id},
            )
            processed += 1

            if processed % 10 == 0:
                print(f"\n  ...已处理 {processed}/{len(rows)}, 提取 {total_relations} 条关系")

        db.commit()

        print(f"\n{'=' * 60}")
        print(f"完成: 处理 {processed} 条新闻, 提取 {total_relations} 条关系")
        print(f"{'=' * 60}")
        return {"processed": processed, "relations": total_relations}
    finally:
        db.close()


if __name__ == "__main__":
    result = process_intelligence_items(batch_size=50)
    print(f"\n结果: {result}")
