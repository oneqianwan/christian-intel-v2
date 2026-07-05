import logging
from typing import Dict, List, Optional

from sqlalchemy import desc, or_

from .base_agent import BaseAgent
from models.database import IntelligenceItem, KnowledgeEntity, OrganizationProfile, SessionLocal

logger = logging.getLogger(__name__)

DATA_SYSTEM_PROMPT = """你是 Christian Intel 的数据查询专家。 

你的任务：根据意图和实体，从数据库获取相关数据。 

【可查询的表和字段】 

1. organization_profiles（机构主表） 
   - name, english_name, short_name, official_name 
   - country, city 
   - official_website, leader_name, leader_title 
   - people_score (0-100), people_score_grade (A-F) 
   - digital_score (0-100), digital_score_grade (A-F) 
   - intel_score (0-100), intel_score_grade (A-F) 
   - organization_type, denomination 
   - member_count, employee_count, annual_revenue 
   - has_ai_initiative, has_online_giving, has_mobile_app 
   - founded_year, description, mission_statement 

2. relation_edges（投资/合作关系表） 
   - source_id → target_id 
   - relation_type: invested_in / co_invested / partnered_with 
   - investment_amount, investment_currency, investment_round 
   - evidence_url, evidence_source, is_verified 

3. intelligence_items（情报条目） 
   - entity_name, title, content, category, source_name 

【查询规则】 
- 机构评分查询 → 直接查 organization_profiles 的 *_score 字段 
- 机构对比查询 → 查多个机构的 *_score 字段 
- 投资关系查询 → 查 relation_edges，JOIN organization_profiles 获取名称 
- 通用情报查询 → 查 intelligence_items 

【输出格式】 
{ 
    "queries_executed": ["查询描述"], 
    "organizations": [ 
        { 
            "name": "机构名", 
            "country": "国家", 
            "people_score": 0, "digital_score": 0, "intel_score": 0, 
            "leader_name": "负责人", 
            "website": "官网" 
        } 
    ], 
    "relations": [ 
        { 
            "relation_type": "invested_in", 
            "other_org_name": "对方机构", 
            "investment_amount": "金额", 
            "investment_round": "轮次", 
            "is_verified": true 
        } 
    ], 
    "intelligence": [], 
    "total_found": 0 
} 
""" 


class DataAgent(BaseAgent):
    """数据查询Agent，直接与数据库交互。"""

    def __init__(self):
        super().__init__(
            name="DataAgent",
            system_prompt=DATA_SYSTEM_PROMPT,
            max_tokens=2000,
        )
        self.db = SessionLocal()

    def __del__(self):
        if hasattr(self, "db"):
            self.db.close()

    def query(self, intent_result: dict) -> dict:
        """根据意图结果执行数据查询。"""
        intent = intent_result.get("intent", "general")
        entities = intent_result.get("entities", {})
        country = entities.get("country")
        org_name = entities.get("organization")
        keywords = entities.get("keywords", [])

        result = {
            "queries_executed": [],
            "organizations": [],
            "relations": [],
            "intelligence": [],
            "country_stats": {},
            "total_found": 0,
        }

        try:
            # ===== 评分直接查询 =====
            if org_name and (intent in ["score_query", "score_comparison"] or any(k in (keywords or []) for k in ["score", "digital", "people", "intel", "composite"])):
                from models.database import OrganizationProfile

                org_candidates: list[str] = []
                if isinstance(org_name, str) and "|||" in org_name:
                    org_candidates = [part.strip() for part in org_name.split("|||") if part.strip()]
                else:
                    org_candidates = [org_name]

                if intent == "score_comparison" and len(org_candidates) < 2:
                    raw_message = str(intent_result.get("raw_message") or "")
                    lowered = raw_message.lower()
                    import re

                    match = None
                    if "compare" in lowered and " and " in lowered:
                        match = re.search(
                            r"compare\s+(.+?)\s+and\s+(.+?)(?:\s+(?:composite|score|scores).*)?$",
                            raw_message,
                            flags=re.IGNORECASE,
                        )
                    if not match and " vs " in lowered:
                        match = re.search(
                            r"(.+?)\s+vs\s+(.+?)(?:\s+(?:composite|score|scores).*)?$",
                            raw_message,
                            flags=re.IGNORECASE,
                        )
                    if match:
                        first = (match.group(1) or "").strip()
                        second = (match.group(2) or "").strip()
                        if first and second:
                            org_candidates = [first, second]

                matched_orgs: list[OrganizationProfile] = []
                for candidate in org_candidates[:5]:
                    if not candidate:
                        continue
                    alias_map = {
                        "SBC": ["Southern Baptist Convention", "Southern Baptist"],
                    }

                    search_terms = [candidate]
                    normalized_candidate = (candidate or "").strip()
                    if normalized_candidate in alias_map:
                        search_terms.extend(alias_map[normalized_candidate])

                    filters = []
                    for term in search_terms:
                        if not term:
                            continue
                        filters.extend(
                            [
                                OrganizationProfile.name.ilike(f"%{term}%"),
                                OrganizationProfile.english_name.ilike(f"%{term}%"),
                                OrganizationProfile.short_name.ilike(f"%{term}%"),
                            ]
                        )

                    per_candidate_limit = 1 if intent == "score_comparison" else 5
                    hits = (
                        self.db.query(OrganizationProfile)
                        .filter(or_(*filters))
                        .order_by(
                            desc(OrganizationProfile.priority_tier == "T1"),
                            desc(OrganizationProfile.people_score),
                            desc(OrganizationProfile.digital_score),
                            desc(OrganizationProfile.intel_score),
                        )
                        .limit(per_candidate_limit)
                        .all()
                        if filters
                        else []
                    )
                    for hit in hits:
                        if all(existing.id != hit.id for existing in matched_orgs):
                            matched_orgs.append(hit)

                if matched_orgs:
                    return {
                        "queries_executed": [f"精确查询机构评分: {org_name}"],
                        "organizations": [
                            {
                                "id": o.id,
                                "name": o.name,
                                "country": o.country,
                                "people_score": o.people_score or 0,
                                "people_score_grade": o.people_score_grade or "F",
                                "digital_score": o.digital_score or 0,
                                "digital_score_grade": o.digital_score_grade or "F",
                                "intel_score": o.intel_score or 0,
                                "intel_score_grade": o.intel_score_grade or "F",
                                "leader_name": o.leader_name,
                                "website": o.official_website,
                            }
                            for o in matched_orgs
                        ],
                        "relations": [],
                        "intelligence": [],
                        "total_found": len(matched_orgs),
                    }

            # ===== 投资关系查询 =====
            if org_name and intent in ["investment_relations", "investment_opportunity", "partnership_recommendation"]:
                from models.database import OrganizationProfile, RelationEdge

                source_org_ids = [
                    row[0]
                    for row in (
                        self.db.query(OrganizationProfile.id)
                        .filter(
                            or_(
                                OrganizationProfile.name.ilike(f"%{org_name}%"),
                                OrganizationProfile.english_name.ilike(f"%{org_name}%"),
                                OrganizationProfile.short_name.ilike(f"%{org_name}%"),
                            )
                        )
                        .all()
                    )
                ]

                if source_org_ids:
                    edges = (
                        self.db.query(RelationEdge)
                        .filter(
                            RelationEdge.relation_type.in_(["invested_in", "co_invested"]),
                            or_(
                                RelationEdge.source_id.in_(source_org_ids),
                                RelationEdge.target_id.in_(source_org_ids),
                            ),
                        )
                        .all()
                    )

                    other_ids = set()
                    rel_rows = []
                    for edge in edges:
                        if edge.source_id in source_org_ids:
                            other_id = edge.target_id
                        else:
                            other_id = edge.source_id
                        other_ids.add(other_id)
                        rel_rows.append((edge, other_id))

                    org_map = {
                        o.id: o
                        for o in self.db.query(OrganizationProfile).filter(OrganizationProfile.id.in_(list(other_ids))).all()
                    } if other_ids else {}

                    if rel_rows:
                        return {
                            "queries_executed": [f"查询投资关系: {org_name}"],
                            "organizations": [],
                            "relations": [
                                {
                                    "relation_type": edge.relation_type,
                                    "other_org_name": (org_map.get(other_id).name if org_map.get(other_id) else other_id),
                                    "other_org_country": (org_map.get(other_id).country if org_map.get(other_id) else None),
                                    "investment_amount": edge.investment_amount,
                                    "investment_currency": edge.investment_currency,
                                    "investment_round": edge.investment_round,
                                    "is_verified": bool(edge.is_verified),
                                    "evidence_url": edge.evidence_url,
                                }
                                for (edge, other_id) in rel_rows
                            ],
                            "intelligence": [],
                            "total_found": len(rel_rows),
                        }

            if org_name or intent in ["organization_profile", "competitor_landscape", "investment_opportunity", "country_analysis", "general"]:
                orgs = self._query_organizations(org_name, country, keywords, limit=10)
                result["organizations"] = orgs
                result["queries_executed"].append(f"机构查询: name={org_name}, country={country}, keywords={keywords}")
                result["total_found"] = len(orgs)

            if country and intent in ["country_analysis", "investment_opportunity", "competitor_landscape"]:
                stats = self._query_country_stats(country)
                result["country_stats"] = stats
                result["queries_executed"].append(f"国家统计: {country}")

            if intent in ["news_intelligence", "country_analysis", "organization_profile"] and (country or org_name or keywords):
                items = self._query_intelligence(country=country, org_name=org_name, keywords=keywords, limit=8)
                result["intelligence"] = items
                result["queries_executed"].append(f"情报查询: country={country}, org={org_name}, keywords={keywords}")

            if result["total_found"] < 5 and country:
                orgs = self._query_organizations(None, country, keywords, limit=10)
                if len(orgs) > result["total_found"]:
                    result["organizations"] = orgs
                    result["total_found"] = len(orgs)
                    result["queries_executed"].append(f"补充机构查询: country={country}, keywords={keywords}")

            result["summary"] = self._generate_data_summary(result)
            return result
        except Exception as exc:
            logger.error("[DataAgent] 查询失败: %s", exc)
            return result

    def _query_organizations(
        self,
        name: Optional[str],
        country: Optional[str],
        keywords: List[str],
        limit: int = 10,
    ) -> List[dict]:
        """查询机构。"""
        query = self.db.query(OrganizationProfile)

        if name:
            query = query.filter(
                or_(
                    OrganizationProfile.name.ilike(f"%{name}%"),
                    OrganizationProfile.name_local.ilike(f"%{name}%"),
                    OrganizationProfile.official_name.ilike(f"%{name}%"),
                    OrganizationProfile.english_name.ilike(f"%{name}%"),
                )
            )

        if country:
            query = query.filter(OrganizationProfile.country == country)

        if keywords:
            filters = []
            for keyword in keywords:
                if keyword == "AI":
                    filters.append(OrganizationProfile.ai_maturity_score.isnot(None))
                    filters.append(OrganizationProfile.has_ai_initiative.is_(True))
                elif keyword == "church":
                    filters.append(OrganizationProfile.organization_type.ilike("%church%"))
                    filters.append(OrganizationProfile.name.ilike("%church%"))
                else:
                    filters.extend(
                        [
                            OrganizationProfile.description.ilike(f"%{keyword}%"),
                            OrganizationProfile.about_text.ilike(f"%{keyword}%"),
                            OrganizationProfile.mission_statement.ilike(f"%{keyword}%"),
                            OrganizationProfile.name.ilike(f"%{keyword}%"),
                        ]
                    )
            if filters:
                query = query.filter(or_(*filters))

        query = query.order_by(
            desc(OrganizationProfile.priority_tier == "T1"),
            desc(OrganizationProfile.ai_maturity_score),
            desc(OrganizationProfile.digital_score),
        ).limit(limit)

        orgs = query.all()
        return [
            {
                "id": org.id,
                "name": org.name,
                "country": org.country,
                "leader_name": org.leader_name,
                "leader_title": org.leader_title,
                "mission_statement": (org.mission_statement or "")[:200] or None,
                "about_text": (org.about_text or "")[:240] or None,
                "ai_maturity_score": org.ai_maturity_score,
                "digital_score": org.digital_score,
                "official_website": org.official_website,
                "contact_email": org.contact_email,
                "phone_public": org.phone_public,
                "has_programs": org.has_programs,
            }
            for org in orgs
        ]

    def _query_country_stats(self, country: str) -> dict:
        """查询国家统计。"""
        total = self.db.query(OrganizationProfile).filter(OrganizationProfile.country == country).count()
        with_people = (
            self.db.query(OrganizationProfile)
            .filter(OrganizationProfile.country == country, OrganizationProfile.leader_name.isnot(None))
            .count()
        )
        with_ai = (
            self.db.query(OrganizationProfile)
            .filter(OrganizationProfile.country == country, OrganizationProfile.ai_maturity_score.isnot(None))
            .count()
        )
        with_mission = (
            self.db.query(OrganizationProfile)
            .filter(OrganizationProfile.country == country, OrganizationProfile.mission_statement.isnot(None))
            .count()
        )
        return {
            "total_organizations": total,
            "with_people": with_people,
            "with_ai_assessment": with_ai,
            "with_mission": with_mission,
        }

    def _query_intelligence(
        self,
        country: Optional[str],
        org_name: Optional[str],
        keywords: List[str],
        limit: int = 8,
    ) -> List[dict]:
        """查询情报条目。"""
        query = self.db.query(IntelligenceItem)

        if country and not org_name:
            query = query.filter(IntelligenceItem.country == country)

        if org_name:
            query = query.filter(IntelligenceItem.entity_name.ilike(f"%{org_name}%"))

        if keywords:
            filters = []
            for keyword in keywords:
                filters.extend(
                    [
                        IntelligenceItem.title.ilike(f"%{keyword}%"),
                        IntelligenceItem.content.ilike(f"%{keyword}%"),
                        IntelligenceItem.category.ilike(f"%{keyword}%"),
                        IntelligenceItem.source_name.ilike(f"%{keyword}%"),
                    ]
                )
            query = query.filter(or_(*filters))

        items = query.order_by(desc(IntelligenceItem.published_at), desc(IntelligenceItem.ingested_at)).limit(limit).all()
        return [
            {
                "entity_name": item.entity_name,
                "title": item.title,
                "summary": (item.content or "")[:240] or None,
                "source_name": item.source_name,
                "source_url": item.source_url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            }
            for item in items
        ]

    def _generate_data_summary(self, result: Dict) -> str:
        """生成数据摘要，供 AnalysisAgent 使用。"""
        parts: List[str] = []

        organizations = result.get("organizations", [])
        if organizations:
            parts.append(f"找到 {len(organizations)} 家机构：")
            for org in organizations[:5]:
                parts.append(
                    f"- {org['name']} ({org['country']}) | AI:{self._display_score(org['ai_maturity_score'])} | "
                    f"People:{org['leader_name'] or 'N/A'} | Mission:{(org['mission_statement'] or 'N/A')[:80]}"
                )

        stats = result.get("country_stats") or {}
        if stats:
            parts.append(
                f"国家统计：机构 {stats.get('total_organizations', 0)} 家，"
                f"负责人覆盖 {stats.get('with_people', 0)} 家，AI评估 {stats.get('with_ai_assessment', 0)} 家。"
            )

        intelligence = result.get("intelligence", [])
        if intelligence:
            parts.append(f"补充情报 {len(intelligence)} 条。")

        return "\n".join(parts) if parts else "未找到匹配数据"

    def _display_score(self, value: Optional[int]) -> str:
        return str(value) if value is not None else "N/A"
