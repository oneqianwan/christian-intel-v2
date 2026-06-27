import re
from typing import Any, Dict, List


COUNTRY_ALIASES = {
    "菲律宾": [r"菲律宾", r"philippines"],
    "美国": [r"美国", r"\busa\b", r"\bus\b", r"america", r"united states"],
    "韩国": [r"韩国", r"south korea", r"\bkorea\b"],
    "尼日利亚": [r"尼日利亚", r"nigeria", r"nigerian"],
    "中国": [r"中国", r"\bchina\b", r"chinese"],
    "印度": [r"印度", r"\bindia\b", r"indian"],
}

GLOBAL_KEYWORDS = [
    "全球", "世界", "国际",
    "whole world", "global", "worldwide", "international",
]

GLOBAL_ORGS = [
    "世界基督教", "oikoumene", "wcc",
    "世界福音联盟", "wea", "worldea",
    "洛桑", "lausanne",
    "世界宣明会", "world vision",
    "葛培理", "billy graham",
    "梵蒂冈", "vatican",
    "今日基督教", "christianity today",
    "皮尤", "pew research",
]

COUNTRY_KEYWORDS = [
    "菲律宾", "韩国", "尼日利亚", "美国",
    "philippines", "korea", "nigeria", "usa", "america",
]

KEYWORD_STOPWORDS = {
    "搜集", "采集", "收集", "然后", "对比", "比较", "异同", "区别",
    "最新", "动态", "消息", "情况", "介绍", "有哪些", "是什么",
    "基督教", "教会", "christianity", "church", "global", "worldwide",
    "international", "whole", "world",
}


def infer_scope(message: str, entities: list[str], primary_intent: str) -> str:
    """根据用户输入推断查询范围。"""
    msg_lower = (message or "").lower()

    if any(keyword in msg_lower for keyword in GLOBAL_KEYWORDS):
        return "global"

    has_country = any(keyword in msg_lower for keyword in COUNTRY_KEYWORDS)
    has_global = any(keyword in msg_lower for keyword in GLOBAL_KEYWORDS)
    if has_country and not has_global:
        return "country"

    for org in GLOBAL_ORGS:
        if org in msg_lower:
            return "global"

    if primary_intent in {"knowledge_lookup", "collection_request"}:
        vague_keywords = ["基督教", "教会", "christianity", "church"]
        if any(keyword in msg_lower for keyword in vague_keywords) and not has_country and not has_global and not entities:
            return "needs_clarify"

    return "country"


def extract_keywords(message: str, entities: list[str], countries: list[str]) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9&'.-]{1,}", message or "")
    blocked = {value.lower() for value in entities + countries}
    keywords: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in blocked or lowered in KEYWORD_STOPWORDS:
            continue
        if token not in keywords:
            keywords.append(token)
    return keywords[:8]

ENTITY_PATTERNS = [
    ("PCEC", [r"pcec", r"philippine council of evangelical churches"]),
    ("Victory", [r"victory", r"victory philippines"]),
    ("CCF", [r"ccf", r"christ'?s commission fellowship"]),
]

INTENT_RULES = {
    "contact_lookup": {
        "weight": 3,
        "patterns": [
            r"负责人", r"联系人", r"联系谁", r"找谁",
            r"帮我联系", r"联系一下", r"对接",
            r"电话", r"邮箱", r"email", r"e-mail",
            r"怎么联系", r"如何联系", r"联系方式",
            r"谁负责", r"主管", r"领导", r"主任", r"牧师",
        ],
    },
    "analysis_request": {
        "weight": 3,
        "patterns": [r"异同", r"区别", r"差异", r"比较", r"对比", r"versus", r"\bvs\b"],
    },
    "collection_request": {
        "weight": 2,
        "patterns": [
            r"最近.*动态", r"最新.*动态", r"近\d+天", r"近\d+周", r"近\d+月",
            r"采集", r"搜集", r"收集", r"最新.*新闻", r"最新.*消息", r"最新.*情况",
            r"最近.*什么.*新闻", r"近一周", r"最新.*活动",
        ],
    },
    "knowledge_lookup": {
        "weight": 2,
        "patterns": [r"多少", r"占比", r"历史", r"统计", r"介绍", r"是什么", r"有哪些"],
    },
}


class IntentRouter:
    def extract_countries(self, message: str) -> List[str]:
        lowered = (message or "").lower()
        countries: List[str] = []
        for country, patterns in COUNTRY_ALIASES.items():
            if any(re.search(pattern, lowered) for pattern in patterns):
                countries.append(country)
        return countries

    def extract_entities(self, message: str) -> List[str]:
        lowered = (message or "").lower()
        entities: List[str] = []
        for entity, patterns in ENTITY_PATTERNS:
            if any(re.search(pattern, lowered) for pattern in patterns):
                entities.append(entity)

        if entities:
            return entities

        english_phrases = re.findall(
            r"([A-Za-z][A-Za-z0-9&'.-]*(?:\s+[A-Za-z][A-Za-z0-9&'.-]*)*)",
            message or "",
        )
        ignored = {"help", "contact", "compare", "difference", "differences", "versus", "vs"}
        for phrase in english_phrases:
            cleaned = phrase.strip()
            if not cleaned:
                continue
            if cleaned.lower() in ignored:
                continue
            if cleaned not in entities:
                entities.append(cleaned)
        return entities

    def _has_compare_signal(self, message: str) -> bool:
        lowered = (message or "").lower()
        return any(token in lowered for token in ["异同", "区别", "差异", "比较", "对比", "vs", "versus"])

    def _has_contact_signal(self, message: str) -> bool:
        lowered = (message or "").lower()
        return any(token in lowered for token in ["联系", "帮我联系", "联系一下", "对接", "找谁", "联系方式"])

    def detect_multi_intent(self, message: str, entities: List[str], countries: List[str]) -> Dict[str, Any] | None:
        lowered = (message or "").lower()
        has_collect = any(token in lowered for token in ["搜集", "采集", "收集"])
        has_then = any(token in lowered for token in ["然后", "接着", "再"])
        has_compare = self._has_compare_signal(message)

        if has_compare and len(entities) >= 2:
            primary_entities = entities[:2]
            return {
                "primary_intent": "multi_intent",
                "scores": {"multi_intent": 999},
                "entities": primary_entities,
                "countries": countries,
                "actions": [
                    {"type": "collect", "target": primary_entities[0]},
                    {"type": "collect", "target": primary_entities[1]},
                    {"type": "compare", "target": f"{primary_entities[0]} vs {primary_entities[1]}"},
                ],
            }

        if not (has_collect and has_then and has_compare):
            return None

        primary_entities = entities[:2]
        if len(primary_entities) < 2:
            matches = re.findall(r"([A-Za-z][A-Za-z0-9&'.-]{1,})", message)
            for match in matches:
                if match not in primary_entities:
                    primary_entities.append(match)
                if len(primary_entities) >= 2:
                    break

        if len(primary_entities) < 2:
            primary_entities = ["目标A", "目标B"]

        return {
            "primary_intent": "multi_intent",
            "scores": {"multi_intent": 999},
            "entities": primary_entities,
            "countries": countries,
            "actions": [
                {"type": "collect", "target": primary_entities[0]},
                {"type": "collect", "target": primary_entities[1]},
                {"type": "compare", "target": f"{primary_entities[0]} vs {primary_entities[1]}"},
            ],
        }

    def route(self, message: str, context: dict | None = None) -> Dict[str, Any]:
        message = (message or "").strip()
        entities = self.extract_entities(message)
        countries = self.extract_countries(message)
        keywords = extract_keywords(message, entities, countries)

        multi_intent = self.detect_multi_intent(message, entities, countries)
        if multi_intent:
            multi_intent["inferred_scope"] = infer_scope(message, entities, multi_intent["primary_intent"])
            multi_intent["keywords"] = keywords
            return multi_intent

        lowered = (message or "").lower()
        scores: Dict[str, int] = {}
        for intent, rule in INTENT_RULES.items():
            score = 0
            for pattern in rule["patterns"]:
                if re.search(pattern, lowered):
                    score += rule["weight"]
            scores[intent] = score

        primary_intent = max(scores, key=lambda key: scores[key])
        best_score = scores[primary_intent]
        broad_markers = ["怎么样", "如何", "咋样", "情况", "有什么", "哪些方面", "介绍下"]
        if self._has_contact_signal(message) and entities:
            primary_intent = "contact_lookup"
            best_score = max(best_score, INTENT_RULES["contact_lookup"]["weight"])
        elif (entities or countries) and any(
            token in lowered
            for token in ["最近动态", "最新动态", "最近新闻", "最新新闻", "最新消息", "最近消息", "最近有什么新闻"]
        ):
            primary_intent = "collection_request"
            best_score = max(best_score, INTENT_RULES["collection_request"]["weight"])
        provisional_intent = primary_intent if best_score > 0 else "knowledge_lookup"
        provisional_scope = infer_scope(message, entities, provisional_intent)
        if (
            best_score < 2
            and not entities
            and (not countries or any(marker in lowered for marker in broad_markers))
            and provisional_scope == "needs_clarify"
        ):
            return {
                "primary_intent": "clarify",
                "scores": {**scores, "clarify": best_score},
                "entities": entities,
                "countries": countries,
                "keywords": keywords,
                "inferred_scope": "needs_clarify",
                "actions": [{"type": "clarify", "target": message}],
            }
        if best_score == 0:
            primary_intent = "knowledge_lookup"

        actions: List[Dict[str, str]] = []
        if primary_intent == "contact_lookup":
            for entity in entities:
                actions.append({"type": "lookup_contact", "target": entity})
        elif primary_intent == "collection_request":
            targets = entities or countries or ["default"]
            for target in targets[:2]:
                actions.append({"type": "collect", "target": target})
        elif primary_intent == "analysis_request":
            targets = entities[:2]
            if len(targets) >= 2:
                actions.append({"type": "compare", "target": f"{targets[0]} vs {targets[1]}"})
        else:
            for entity in entities[:2]:
                actions.append({"type": "lookup_knowledge", "target": entity})

        return {
            "primary_intent": primary_intent,
            "scores": scores,
            "entities": entities,
            "countries": countries,
            "keywords": keywords,
            "inferred_scope": infer_scope(message, entities, primary_intent),
            "actions": actions,
        }


_router = IntentRouter()


def get_router() -> IntentRouter:
    return _router


def classify_intent(message: str) -> str:
    return get_router().route(message)["primary_intent"]
