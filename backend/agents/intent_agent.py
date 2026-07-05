import re
from typing import Dict, List, Optional

from .base_agent import BaseAgent

INTENT_SYSTEM_PROMPT = """你是Christian Intel的意图识别专家。

你的任务：分析用户查询，识别真实意图，输出结构化JSON。

支持的意图类型：
- "country_analysis": 国家/地区基督教概况分析
- "organization_profile": 特定机构画像查询
- "score_query": 机构评分查询（如 digital score, people score, composite score）
- "score_comparison": 机构评分对比（如 compare A and B scores）
- "investment_opportunity": 投资机会分析
- "investment_relations": 投资关系查询（如 who invested in X）
- "competitor_landscape": 竞争格局分析
- "partnership_recommendation": 合作推荐
- "contact_inquiry": 联系人/联系方式查询
- "news_intelligence": 新闻/动态查询
- "general": 通用查询

输出格式（严格JSON）：
{
    "intent": "意图类型",
    "confidence": 0.0-1.0,
    "entities": {
        "country": "国家名或null",
        "organization": "机构名或null",
        "keywords": ["关键词1", "关键词2"],
        "time_range": "时间范围或null"
    },
    "complexity": "simple|multi_step",
    "required_agents": ["需要的Agent列表"]
}

判断规则：
- 含"分析/概况/landscape/overview" → country_analysis
- 含具体机构名 → organization_profile
- 含"投资/invest/opportunity/deal" → investment_opportunity
- 含"竞争/competitor/compare/对比" → competitor_landscape
- 含"合作/partner/collaboration" → partnership_recommendation
- 含"联系/contact/邮件/电话" → contact_inquiry
- 含"新闻/news/最近/动态" → news_intelligence
- 多国多机构交叉 → complexity="multi_step"
"""

COUNTRY_ALIASES = {
    "菲律宾": "Philippines",
    "ph": "Philippines",
    "philippines": "Philippines",
    "韩国": "South Korea",
    "south korea": "South Korea",
    "korea": "South Korea",
    "尼日利亚": "Nigeria",
    "nigeria": "Nigeria",
    "中国": "China",
    "china": "China",
    "美国": "United States",
    "usa": "United States",
    "united states": "United States",
    "肯尼亚": "Kenya",
    "kenya": "Kenya",
}

KNOWN_ORGS = [
    "PCEC",
    "SBC",
    "Southern Baptist Convention",
    "CBN Asia",
    "Victory",
    "Victory Philippines",
    "JIL",
    "CCF",
    "Alpha Southeast Asia",
    "Gloo",
    "Christian and Missionary Alliance",
    "Christian and Missionary Alliance Churches of the Philippines",
]


class IntentAgent(BaseAgent):
    """意图识别Agent。"""

    def __init__(self):
        super().__init__(
            name="IntentAgent",
            system_prompt=INTENT_SYSTEM_PROMPT,
            max_tokens=500,
        )

    def recognize(self, user_message: str) -> dict:
        """识别用户意图，返回结构化结果。"""
        prompt = f"""分析以下用户查询：

用户输入："{user_message}"

请输出JSON格式的意图分析。"""

        response = self.call(prompt, temperature=0.1)
        result = self.parse_json(response)

        if not result or "intent" not in result:
            return self._heuristic_intent(user_message)

        entities = result.get("entities") or {}
        extracted_country = self._extract_country(user_message)
        extracted_org = self._extract_organization(user_message)
        extracted_keywords = self._extract_keywords(user_message)
        extracted_time_range = self._extract_time_range(user_message)

        country = self._normalize_country(entities.get("country")) or extracted_country
        organization = entities.get("organization") or extracted_org
        keywords = self._normalize_keywords((entities.get("keywords") or []) + extracted_keywords)
        time_range = entities.get("time_range") or extracted_time_range
        complexity = result.get("complexity") or self._infer_complexity(user_message, result["intent"])

        lowered = (user_message or "").lower()
        score_tokens = ["digital score", "people score", "intel score", "composite", "score", "scores"]
        is_score_compare = any(token in lowered for token in ["compare", "vs", "versus", "对比"]) and any(
            token in lowered for token in ["score", "scores", "composite"]
        )
        is_score_query = any(token in lowered for token in score_tokens) and bool(extracted_org or organization)
        is_investment_relations = any(token in lowered for token in ["who invested", "invested in", "invested in by", "invest in"]) and bool(extracted_org or organization)
        is_news_intelligence = any(token in lowered for token in ["intelligence", "latest", "timeline", "news", "动态", "最近"])

        if is_score_compare:
            result["intent"] = "score_comparison"
            if extracted_org and "|||" in extracted_org:
                organization = extracted_org
        elif is_score_query:
            result["intent"] = "score_query"
        elif is_investment_relations:
            result["intent"] = "investment_relations"
        elif is_news_intelligence and bool(extracted_org or country):
            result["intent"] = "news_intelligence"

        result["entities"] = {
            "country": country,
            "organization": organization,
            "keywords": keywords,
            "time_range": time_range,
        }
        result["complexity"] = complexity
        result["required_agents"] = self._required_agents(complexity)
        result["confidence"] = result.get("confidence", 0.7)
        result["raw_message"] = user_message
        return result

    def _heuristic_intent(self, user_message: str) -> dict:
        text = user_message or ""
        lowered = text.lower()
        country = self._extract_country(text)
        organization = self._extract_organization(text)
        keywords = self._extract_keywords(text)
        time_range = self._extract_time_range(text)

        score_tokens = [
            "digital score",
            "people score",
            "intel score",
            "composite score",
            "composite scores",
            "score of",
            "scores of",
            "score",
            "composite",
        ]
        is_score_compare = any(token in lowered for token in ["compare", "vs", "versus", "对比"]) and any(
            token in lowered for token in ["score", "scores", "composite"]
        )
        is_score_query = any(token in lowered for token in score_tokens) and bool(organization)
        is_investment_relations = any(token in lowered for token in ["who invested", "invested in", "invested in by", "invest in"]) and bool(organization)

        if is_score_compare:
            intent = "score_comparison"
        elif is_score_query:
            intent = "score_query"
        elif is_investment_relations:
            intent = "investment_relations"
        elif any(token in lowered for token in ["intelligence", "latest", "timeline", "news", "动态", "最近"]):
            intent = "news_intelligence"
        elif any(token in lowered for token in ["投资", "invest", "opportunity", "deal"]):
            intent = "investment_opportunity"
        elif any(token in lowered for token in ["竞争", "competitor", "compare", "对比", "landscape"]):
            intent = "competitor_landscape"
        elif any(token in lowered for token in ["合作", "partner", "collaboration"]):
            intent = "partnership_recommendation"
        elif any(token in lowered for token in ["联系", "contact", "邮件", "邮箱", "电话"]):
            intent = "contact_inquiry"
        elif organization:
            intent = "organization_profile"
        elif country and any(token in lowered for token in ["分析", "概况", "overview", "landscape"]):
            intent = "country_analysis"
        elif country:
            intent = "country_analysis"
        else:
            intent = "general"

        complexity = self._infer_complexity(text, intent)
        return {
            "intent": intent,
            "confidence": 0.65,
            "entities": {
                "country": country,
                "organization": organization,
                "keywords": keywords,
                "time_range": time_range,
            },
            "complexity": complexity,
            "required_agents": self._required_agents(complexity),
            "raw_message": user_message,
        }

    def _extract_country(self, text: str) -> Optional[str]:
        normalized = self._normalize_country(text)
        if normalized:
            return normalized
        lowered = (text or "").lower()
        for alias, canonical in COUNTRY_ALIASES.items():
            if alias in lowered:
                return canonical
        return None

    def _extract_organization(self, text: str) -> Optional[str]:
        raw = text or ""
        lowered = raw.lower()
        if any(token in lowered for token in ["compare", "对比"]) and " and " in lowered:
            match = re.search(
                r"compare\s+(.+?)\s+and\s+(.+?)(?:\s+(?:composite|score|scores).*)?$",
                raw,
                flags=re.IGNORECASE,
            )
            if match:
                first = (match.group(1) or "").strip()
                second = (match.group(2) or "").strip()
                if first and second and len(first) <= 80 and len(second) <= 80:
                    return f"{first}|||{second}"

        score_match = re.search(r"(?:digital|people|intel|composite)?\s*score\s+of\s+(.+?)(?:\?|$)", raw, flags=re.IGNORECASE)
        if score_match:
            candidate = (score_match.group(1) or "").strip()
            if candidate and len(candidate) <= 120:
                return candidate

        invested_match = re.search(r"(?:who\s+)?invested\s+in\s+(.+?)(?:\?|$)", raw, flags=re.IGNORECASE)
        if invested_match:
            candidate = (invested_match.group(1) or "").strip()
            if candidate and len(candidate) <= 120:
                return candidate

        about_match = re.search(r"(?:about|for)\s+(.+?)(?:\?|$)", raw, flags=re.IGNORECASE)
        if about_match:
            candidate = (about_match.group(1) or "").strip()
            if candidate and len(candidate) <= 120:
                return candidate

        for org in KNOWN_ORGS:
            if org.lower() in raw.lower():
                return org

        quoted = re.search(r"[\"“](.*?)[\"”]", raw)
        if quoted:
            candidate = quoted.group(1).strip()
            if candidate and len(candidate) <= 80:
                return candidate
        return None

    def _extract_keywords(self, text: str) -> List[str]:
        keyword_map = {
            "ai": "AI",
            "人工智能": "AI",
            "score": "score",
            "scores": "score",
            "composite": "composite",
            "digital score": "digital",
            "people score": "people",
            "intel score": "intel",
            "教会": "church",
            "church": "church",
            "使命": "mission",
            "mission": "mission",
            "数字化": "digital",
            "digital": "digital",
            "投资": "investment",
            "合作": "partnership",
            "新闻": "news",
        }
        lowered = (text or "").lower()
        found: List[str] = []
        for token, normalized in keyword_map.items():
            if token in lowered and normalized not in found:
                found.append(normalized)
        return found

    def _normalize_country(self, text: Optional[str]) -> Optional[str]:
        lowered = (text or "").strip().lower()
        if not lowered:
            return None
        return COUNTRY_ALIASES.get(lowered)

    def _normalize_keywords(self, keywords: List[str]) -> List[str]:
        normalized: List[str] = []
        for keyword in keywords:
            value = (keyword or "").strip()
            lowered = value.lower()
            mapped = None
            if "ai" in lowered or "人工智能" in lowered:
                mapped = "AI"
            elif "教会" in value or "church" in lowered:
                mapped = "church"
            elif "mission" in lowered or "使命" in value:
                mapped = "mission"
            elif "digital" in lowered or "数字化" in value:
                mapped = "digital"
            elif "投资" in value or "invest" in lowered:
                mapped = "investment"
            elif "合作" in value or "partner" in lowered:
                mapped = "partnership"
            elif "新闻" in value or "news" in lowered:
                mapped = "news"
            if mapped and mapped not in normalized:
                normalized.append(mapped)
        return normalized

    def _extract_time_range(self, text: str) -> Optional[str]:
        lowered = (text or "").lower()
        if "最近" in lowered or "近期" in lowered or "recent" in lowered:
            return "recent"
        if "今年" in lowered or "2026" in lowered:
            return "this_year"
        return None

    def _infer_complexity(self, text: str, intent: str) -> str:
        lowered = (text or "").lower()
        multi_tokens = ["分析", "overview", "landscape", "机会", "对比", "compare", "投资", "合作"]
        hit_count = sum(1 for token in multi_tokens if token in lowered)
        if intent in {"investment_opportunity", "competitor_landscape", "partnership_recommendation"}:
            return "multi_step"
        if hit_count >= 2:
            return "multi_step"
        return "simple"

    def _required_agents(self, complexity: str) -> List[str]:
        if complexity == "multi_step":
            return ["data_agent", "analysis_agent", "report_agent"]
        return ["data_agent", "report_agent"]
