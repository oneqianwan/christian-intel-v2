"""
Intel Score 计算服务
基于 intelligence_items 表，通过 entity_name 模糊匹配机构
评估机构的情报覆盖度，0-100
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from models.database import IntelligenceItem, OrganizationProfile


class IntelScorer:
    VOLUME_TIERS = [
        (0, 0),
        (1, 5),
        (3, 10),
        (5, 15),
        (10, 20),
        (20, 25),
        (50, 30),
    ]

    RECENCY_TIERS = [
        (7, 25),
        (30, 20),
        (90, 15),
        (180, 10),
        (365, 5),
        (9999, 0),
    ]

    def calculate_all(self, session, orgs: List[OrganizationProfile]) -> Dict[str, Dict]:
        """
        一次性计算所有机构的 Intel Score
        策略：加载所有 intelligence_items，内存匹配 entity_name
        返回: {org_id: score_result}
        """
        items = session.query(IntelligenceItem).all()
        print(f"Loaded {len(items)} intelligence items")

        entity_items: dict[str, list[IntelligenceItem]] = defaultdict(list)
        for item in items:
            entity_name = (item.entity_name or "").strip().lower()
            if entity_name:
                entity_items[entity_name].append(item)

        org_aliases: list[tuple[str, str]] = []
        exact_map: dict[str, str] = {}
        for org in orgs:
            for alias in self._collect_aliases(org):
                exact_map.setdefault(alias, org.id)
                org_aliases.append((alias, org.id))

        org_intel: dict[str, list[IntelligenceItem]] = defaultdict(list)
        matched = 0
        for entity_name, item_list in entity_items.items():
            org_id = exact_map.get(entity_name)
            if org_id:
                org_intel[org_id].extend(item_list)
                matched += len(item_list)
                continue

            best_match = None
            best_len = 0
            for alias, candidate_org_id in org_aliases:
                if len(alias) < 4:
                    continue
                if alias in entity_name or entity_name in alias:
                    if len(alias) > best_len:
                        best_match = candidate_org_id
                        best_len = len(alias)

            if best_match:
                org_intel[best_match].extend(item_list)
                matched += len(item_list)

        print(f"Matched {matched}/{len(items)} items to {len(org_intel)} organizations")

        results = {}
        for org in orgs:
            items_for_org = org_intel.get(org.id, [])
            results[org.id] = self._score_org(items_for_org)
        return results

    def _collect_aliases(self, org: OrganizationProfile) -> list[str]:
        aliases = []
        for value in [org.name, org.short_name, org.english_name, org.official_name]:
            normalized = (value or "").strip().lower()
            if normalized and normalized not in aliases:
                aliases.append(normalized)
        return aliases

    def _score_org(self, items: List[IntelligenceItem]) -> Dict:
        result = {
            "total_score": 0,
            "grade": "F",
            "dimensions": {
                "volume": 0,
                "recency": 0,
                "sources": 0,
                "coverage": 0,
            },
            "item_count": len(items),
            "sources_list": [],
            "latest_date": None,
            "error": None,
        }

        if not items:
            return result

        count = len(items)
        for threshold, score in self.VOLUME_TIERS:
            if count >= threshold:
                result["dimensions"]["volume"] = score

        now = datetime.utcnow()
        latest = max((item.ingested_at or item.published_at or now) for item in items)
        result["latest_date"] = latest.isoformat() if latest else None

        days_ago = (now - latest).days if latest else 999
        for threshold, score in self.RECENCY_TIERS:
            if days_ago <= threshold:
                result["dimensions"]["recency"] = score
                break

        unique_sources = set()
        for item in items:
            source_name = (item.source_name or "").strip()
            if source_name:
                unique_sources.add(source_name)
        result["sources_list"] = sorted(unique_sources)
        source_count = len(unique_sources)

        if source_count >= 6:
            result["dimensions"]["sources"] = 25
        elif source_count >= 3:
            result["dimensions"]["sources"] = 20
        elif source_count >= 2:
            result["dimensions"]["sources"] = 10
        elif source_count >= 1:
            result["dimensions"]["sources"] = 5

        unique_types = set()
        unique_categories = set()
        for item in items:
            if item.entity_type:
                unique_types.add(item.entity_type.strip().lower())
            if item.category:
                unique_categories.add(item.category.strip().lower())

        coverage_score = 0
        if len(unique_types) >= 1:
            coverage_score += 5
        if len(unique_types) >= 3:
            coverage_score += 5
        if len(unique_categories) >= 2:
            coverage_score += 5
        if len(unique_categories) >= 5:
            coverage_score += 5

        result["dimensions"]["coverage"] = min(coverage_score, 20)
        result["total_score"] = sum(result["dimensions"].values())
        result["grade"] = self._to_grade(result["total_score"])
        return result

    def _to_grade(self, score: int) -> str:
        if score >= 80:
            return "A"
        if score >= 60:
            return "B"
        if score >= 40:
            return "C"
        if score >= 20:
            return "D"
        return "F"
