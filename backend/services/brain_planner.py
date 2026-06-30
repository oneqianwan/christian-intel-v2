from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

from .truth_engine import TruthEngine

@dataclass
class SubTask:
    """子任务定义"""

    task_id: str
    tool_name: str
    params: Dict[str, Any]
    depends_on: List[str] = field(default_factory=list)
    description: str = ""
    priority: int = 0


@dataclass
class PlanResult:
    """规划执行结果"""

    subtask_results: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    errors: List[str] = field(default_factory=list)


class QueryPlanner:
    """查询规划器：将用户Query拆解为子任务序列"""

    COUNTRY_ALIASES = {
        "Philippines": ["菲律宾", "菲律宾的", "philippines"],
        "United States": ["美国", "美国的", "united states", "usa"],
        "South Korea": ["韩国", "韩国的", "south korea", "korea"],
        "United Kingdom": ["英国", "英国的", "united kingdom", "england", "britain"],
        "China": ["中国", "中国的", "china"],
        "India": ["印度", "印度的", "india"],
        "Japan": ["日本", "日本的", "japan"],
        "Singapore": ["新加坡", "新加坡的", "singapore"],
        "Australia": ["澳大利亚", "澳洲", "australia"],
        "Nigeria": ["尼日利亚", "尼日利亚的", "nigeria"],
        "Kenya": ["肯尼亚", "肯尼亚的", "kenya"],
    }

    COUNTRY_LOCAL_NAMES = {
        "Philippines": "菲律宾",
        "United States": "美国",
        "South Korea": "韩国",
        "United Kingdom": "英国",
        "China": "中国",
        "India": "印度",
        "Japan": "日本",
        "Singapore": "新加坡",
        "Australia": "澳大利亚",
        "Nigeria": "尼日利亚",
        "Kenya": "肯尼亚",
    }

    ONTOLOGY_MAPPING = [
        ("organization_type", "church_network", ["教会网络", "network church", "church network"]),
        ("organization_type", "church_independent", ["独立教会"]),
        ("organization_type", "church_denomination", ["宗派体系教会", "宗派教会"]),
        ("organization_type", "church_mega", ["大型教会", "超级教会"]),
        ("organization_type", "mission_agency", ["差传机构", "宣教机构", "mission agency"]),
        ("organization_type", "mission_bible_translation", ["圣经翻译", "bible translation"]),
        ("organization_type", "mission_relief", ["救援", "发展机构", "relief"]),
        ("organization_type", "foundation_grant", ["资助型基金会", "grant foundation"]),
        ("organization_type", "foundation_investment", ["投资型基金会", "investment foundation"]),
        ("organization_type", "foundation_family", ["家族基金会", "family foundation"]),
        ("organization_type", "faithtech_bible", ["圣经科技", "bible tech"]),
        ("organization_type", "faithtech_worship", ["敬拜科技", "worship tech"]),
        ("organization_type", "faithtech_social", ["基督教社交媒体", "christian social media"]),
        ("organization_type", "faithtech_fintech", ["基督教金融科技", "christian fintech"]),
        (
            "organization_type",
            "faithtech_ai",
            ["faithtech ai", "基督教ai", "faithtech", "faith tech", "church tech", "christian tech", "christian ai"],
        ),
        ("organization_type", "faithtech_education", ["教育科技", "门徒训练平台", "edtech"]),
        ("organization_type", "faithtech_media", ["基督教媒体", "christian media"]),
        ("organization_type", "ngo_christian", ["基督教ngo", "christian ngo"]),
        ("organization_type", "seminary", ["神学院", "seminary"]),
        ("organization_type", "accelerator", ["加速器", "孵化器", "accelerator", "incubator"]),
        ("organization_type", "media_outlet", ["媒体机构", "media outlet"]),
        ("organization_type", "association", ["协会", "联盟", "association", "alliance"]),
        ("theology", "evangelical", ["福音派", "evangelical"]),
        ("theology", "pentecostal", ["五旬节", "pentecostal"]),
        ("theology", "charismatic", ["灵恩", "charismatic"]),
        ("theology", "reformed", ["改革宗", "reformed"]),
        ("theology", "baptist", ["浸信会", "baptist"]),
        ("theology", "methodist", ["卫理公会", "methodist"]),
        ("theology", "anglican", ["圣公会", "anglican"]),
        ("theology", "lutheran", ["路德宗", "lutheran"]),
        ("theology", "catholic", ["天主教", "catholic"]),
        ("theology", "orthodox", ["东正教", "orthodox"]),
        ("theology", "nondenominational", ["无宗派", "non-denominational", "nondenominational"]),
        ("theology", "interdenominational", ["跨宗派", "interdenominational"]),
        ("scale", "micro", ["微型", "micro"]),
        ("scale", "small", ["小型", "small"]),
        ("scale", "medium", ["中型", "medium"]),
        ("scale", "large", ["大型", "large"]),
        ("scale", "mega", ["超大型", "mega"]),
        ("ai_maturity", "level_0", ["无数字化", "no digital"]),
        ("ai_maturity", "level_1", ["基础数字化", "basic digital"]),
        ("ai_maturity", "level_2", ["数字化工具", "digital tools"]),
        ("ai_maturity", "level_3", ["ai辅助", "ai assisted"]),
        ("ai_maturity", "level_4", ["ai原生", "ai native"]),
        ("collaboration", "seeking_investment", ["寻找投资", "seeking investment", "investment opportunity"]),
        ("collaboration", "seeking_acquisition", ["寻找收购方", "收购", "acquisition"]),
        ("collaboration", "open_partnership", ["开放合作", "partnership", "collaboration"]),
        ("collaboration", "making_investments", ["进行投资", "making investments"]),
        ("collaboration", "seeking_projects", ["寻找项目", "seeking projects"]),
        ("collaboration", "not_open", ["暂不开放", "not open"]),
        ("collaboration", "exploring", ["探索中", "exploring"]),
    ]

    QUERY_TEMPLATES = {
        "global_overview": {
            "patterns": ["全球", "概览", "overview", "market", "landscape", "全景", "总览", "市场分析"],
            "subtasks": [
                {
                    "tool": "query_database",
                    "description": "查询全局机构分布统计",
                    "param_override": {"scope": "global", "country": None, "entity": None, "limit": 20},
                },
                {
                    "tool": "query_ontology",
                    "description": "查询机构类型分布",
                    "param_override": {"filter_type": "organization_type", "filter_value": "faithtech_ai", "country": None, "limit": 20},
                },
                {
                    "tool": "query_investors",
                    "description": "查询活跃投资机构概览",
                    "param_override": {"focus_area": "faithtech", "country": None, "limit": 15},
                },
                {
                    "tool": "query_funding_rounds",
                    "description": "查询融资事件概览",
                    "param_override": {"entity_name": None, "focus_area": "faithtech", "limit": 20},
                },
                {
                    "tool": "query_organization_profile",
                    "description": "查询高AI成熟度机构代表",
                    "param_override": {"org_name": "{representative_org}"},
                },
            ],
            "aggregation": True,
            "report_override": {
                "title": "Christian Tech Global Market Overview",
                "sections": [
                    "market_size",
                    "regional_distribution",
                    "ai_maturity_landscape",
                    "funding_overview",
                    "key_players",
                    "investment_opportunities",
                ],
            },
        },
        "country_analysis": {
            "patterns": ["分析", "国家", "地区", "overview", "market in", "landscape"],
            "subtasks": [
                {"tool": "query_arda_country", "description": "查询国家宗教基线数据"},
                {
                    "tool": "query_database",
                    "description": "查询该国机构与市场情报",
                    "param_override": {"scope": "country", "country": "{country_local}"},
                },
                {
                    "tool": "query_ontology",
                    "description": "查询该国机构分类统计",
                    "param_override": {"country": "{country_local}"},
                },
            ],
        },
        "organization_profile": {
            "patterns": ["什么机构", "介绍", "是谁", "profile", "about", "organization"],
            "subtasks": [
                {"tool": "query_organization_profile", "description": "查询机构画像"},
                {"tool": "query_contacts", "description": "查询联系人"},
                {"tool": "query_funding_rounds", "description": "查询融资历史"},
            ],
        },
        "investment_opportunity": {
            "patterns": ["投资", "机会", "funding", "investor", "investment", "融资"],
            "subtasks": [
                {
                    "tool": "query_database",
                    "description": "查询目标市场机构与情报线索",
                    "param_override": {"scope": "country", "country": "{country_local}"},
                },
                {"tool": "query_investors", "description": "查询投资人"},
                {"tool": "match_investors", "description": "匹配投资人"},
                {"tool": "query_funding_rounds", "description": "查询融资历史"},
            ],
        },
        "competitor_analysis": {
            "patterns": ["对比", "竞争", "比较", "vs", "versus", "competitor"],
            "subtasks": [
                {"tool": "query_organization_profile", "description": "查询多个机构画像"},
                {"tool": "query_ontology", "description": "查询分类对比"},
            ],
        },
        "partnership_recommendation": {
            "patterns": ["合作", "推荐", "partner", "collaboration", "work with"],
            "subtasks": [
                {"tool": "query_organization_profile", "description": "查询潜在合作机构"},
                {"tool": "query_contacts", "description": "查询联系方式"},
                {"tool": "query_ontology", "description": "查询匹配度"},
            ],
        },
    }

    def classify_intent(self, query: str) -> Optional[str]:
        """
        轻量意图分类：将Query匹配到预设模板类型
        返回模板key或None（未匹配）
        """

        query_lower = (query or "").lower()
        if self._is_global_overview_query(query):
            return "global_overview"

        explicit_org_name = self._extract_org_name_from_query(query)
        if explicit_org_name and any(
            token in query_lower for token in ["是什么机构", "是什么组织", "是什么", "介绍", "profile", "about", "值得投资"]
        ):
            return "organization_profile"

        if self._is_country_analysis_query(query):
            return "country_analysis"

        best_intent: Optional[str] = None
        best_score = 0

        for template_key, template in self.QUERY_TEMPLATES.items():
            score = sum(1 for pattern in template.get("patterns", []) if (pattern or "").lower() in query_lower)
            if template_key == "organization_profile" and explicit_org_name:
                score += 2
            if template_key == "investment_opportunity" and any(
                token in query_lower for token in ["值得投资", "投资机会", "invest", "investor", "funding", "融资"]
            ):
                score += 3
            if template_key == "country_analysis" and self._extract_country_info(query)[0]:
                score += 1

            if score > best_score:
                best_score = score
                best_intent = template_key

        return best_intent if best_score > 0 else None

    def _is_global_overview_query(self, query: str) -> bool:
        lowered = (query or "").lower()
        has_global = any(token in lowered for token in ["全球", "global", "worldwide", "international"])
        has_overview = any(token in lowered for token in ["概览", "overview", "landscape", "总览", "全景", "市场分析"])
        has_market_subject = any(token in lowered for token in ["市场", "market", "christian tech", "faithtech", "基督教科技"])
        return has_global and has_overview and has_market_subject

    def _is_country_analysis_query(self, query: str) -> bool:
        lowered = (query or "").lower()
        has_country = bool(self._extract_country_info(query)[0])
        has_analysis = any(token in lowered for token in ["分析", "概览", "overview", "landscape", "market"])
        return has_country and has_analysis

    def plan(self, query: str, entities: List[str] = None) -> List[SubTask]:
        """
        将Query拆解为子任务序列
        返回按依赖关系排序的SubTask列表
        """

        intent = self.classify_intent(query)
        if not intent or intent not in self.QUERY_TEMPLATES:
            return []

        template = self.QUERY_TEMPLATES[intent]
        extracted_params = self._extract_params(query, entities or [])

        subtasks: List[SubTask] = []
        for idx, st in enumerate(template.get("subtasks", [])):
            tool_name = st.get("tool") or ""
            task_id = f"{intent}_{idx}"
            params = self._build_tool_params(tool_name, extracted_params)
            params = self._apply_param_override(params, st.get("param_override"), extracted_params)
            subtasks.append(
                SubTask(
                    task_id=task_id,
                    tool_name=tool_name,
                    params=params,
                    description=st.get("description", ""),
                    priority=idx,
                )
            )
        return subtasks

    def _extract_params(self, query: str, entities: List[str]) -> Dict[str, Any]:
        """从Query中提取关键参数，增加语义校验"""

        params: Dict[str, Any] = {"query": query}
        detected_country, detected_country_local = self._extract_country_info(query)
        if detected_country:
            params["country"] = detected_country
        if detected_country_local:
            params["country_local"] = detected_country_local

        org_name = self._select_best_entity(query, entities or [])
        if not org_name:
            org_name = self._extract_org_name_from_query(query)

        if org_name and not self._is_country_name(org_name):
            params["organization_name"] = org_name

        focus_area = self._extract_focus_area(query)
        if focus_area:
            params["focus_area"] = focus_area

        representative_org = self._extract_representative_org(query, focus_area)
        if representative_org:
            params["representative_org"] = representative_org

        stage = self._extract_stage(query)
        if stage:
            params["stage"] = stage
        return params

    def _build_tool_params(self, tool_name: str, extracted: Dict[str, Any]) -> Dict[str, Any]:
        """根据工具名构建参数"""

        param_mapping = {
            "query_arda_country": lambda e: {"country": e.get("country", "")},
            "query_organization_profile": lambda e: {
                "org_name": e.get("organization_name") or "",
            },
            "query_database": lambda e: {
                "scope": self._infer_scope(e),
                "country": e.get("country_local") or e.get("country"),
                "entity": e.get("organization_name"),
                "keywords": self._extract_keywords(e.get("query", "")),
                "limit": 10,
            },
            "query_intelligence": lambda e: {
                "scope": self._infer_scope(e),
                "country": e.get("country_local") or e.get("country"),
                "entity": e.get("organization_name"),
                "keywords": self._extract_keywords(e.get("query", "")),
                "limit": 10,
            },
            "query_investors": lambda e: {
                "focus_area": e.get("focus_area"),
                "country": e.get("country_local") or e.get("country"),
                "stage": e.get("stage"),
                "limit": 10,
            },
            "match_investors": lambda e: {
                "project_description": e.get("query", ""),
                "focus_area": e.get("focus_area", ""),
                "stage": e.get("stage", ""),
                "country": e.get("country_local") or e.get("country", ""),
                "region": e.get("country_local") or e.get("country", ""),
                "limit": 5,
            },
            "query_funding_rounds": lambda e: {
                "entity_name": e.get("organization_name"),
                "focus_area": None if e.get("organization_name") else e.get("focus_area"),
                "limit": 10,
            },
            "query_contacts": lambda e: {"org_name": e.get("organization_name") or ""},
            "query_ontology": lambda e: self._build_ontology_params(e),
        }

        builder = param_mapping.get(tool_name)
        if builder is None:
            return dict(extracted)
        return builder(extracted)

    def _extract_country_info(self, query: str) -> tuple[Optional[str], Optional[str]]:
        lowered = (query or "").lower()
        for english_name, aliases in self.COUNTRY_ALIASES.items():
            if any(self._contains_alias(lowered, alias) for alias in aliases):
                return english_name, self.COUNTRY_LOCAL_NAMES.get(english_name, english_name)
        return None, None

    def _contains_alias(self, lowered_query: str, alias: str) -> bool:
        alias_lower = (alias or "").lower()
        if not alias_lower:
            return False
        if re.search(r"[a-z]", alias_lower):
            return re.search(rf"\b{re.escape(alias_lower)}\b", lowered_query) is not None
        return alias_lower in lowered_query

    def _is_country_name(self, value: Optional[str]) -> bool:
        candidate = (value or "").strip().lower()
        if not candidate:
            return False
        for english_name, aliases in self.COUNTRY_ALIASES.items():
            if candidate == english_name.lower() or candidate == self.COUNTRY_LOCAL_NAMES.get(english_name, "").lower():
                return True
            if any(candidate == alias.lower() for alias in aliases):
                return True
        return False

    def _select_best_entity(self, query: str, entities: List[str]) -> Optional[str]:
        if not entities:
            return None

        query_lower = (query or "").lower()
        explicit_matches = []
        for entity in entities:
            cleaned = (entity or "").strip()
            if not cleaned or self._is_country_name(cleaned):
                continue
            if cleaned.lower() in query_lower:
                explicit_matches.append(cleaned)
        if explicit_matches:
            return max(explicit_matches, key=len)

        query_org = self._extract_org_name_from_query(query)
        if query_org:
            for entity in entities:
                cleaned = (entity or "").strip()
                if cleaned.lower() == query_org.lower():
                    return cleaned

        return max(
            [(entity or "").strip() for entity in entities if (entity or "").strip() and not self._is_country_name(entity)],
            key=len,
            default=None,
        )

    def _extract_org_name_from_query(self, query: str) -> Optional[str]:
        query_text = (query or "").strip()
        if not query_text:
            return None

        org_patterns = [
            r"(.+?)(?:是什么机构|是什么组织|是什么|的机构|介绍一下|介绍|profile|about)",
            r"(.+?)(?:值得投资|invest|funding|融资)",
        ]
        for pattern in org_patterns:
            match = re.search(pattern, query_text, re.IGNORECASE)
            if not match:
                continue
            candidate = match.group(1).strip(" ，。?？!！,")
            candidate = re.sub(r"^(请问|帮我|想了解|请分析)\s*", "", candidate, flags=re.IGNORECASE).strip()
            if candidate and not self._is_country_name(candidate):
                return candidate
        return None

    def _extract_focus_area(self, query: str) -> Optional[str]:
        lowered = (query or "").lower()
        focus_mapping = [
            ("faithtech", ["faithtech", "faith tech", "christian tech", "church tech", "基督教科技"]),
            ("media", ["media", "christian media", "社交媒体", "媒体"]),
            ("edtech", ["edtech", "education", "教育科技", "神学教育"]),
            ("mission", ["mission", "宣教", "差传", "福音"]),
            ("ai", ["ai", "人工智能", "基督教ai", "christian ai"]),
        ]
        for focus_area, tokens in focus_mapping:
            if any(token in lowered for token in tokens):
                return focus_area
        return None

    def _extract_representative_org(self, query: str, focus_area: Optional[str]) -> Optional[str]:
        lowered = (query or "").lower()
        if "gloo" in lowered:
            return "Gloo"

        defaults = {
            "faithtech": "Gloo",
            "media": "Christianity Today",
            "edtech": "Cru",
            "mission": "OneHope Foundation",
            "ai": "Gloo",
        }
        return defaults.get(focus_area or "")

    def _extract_stage(self, query: str) -> Optional[str]:
        lowered = (query or "").lower()
        stage_mapping = [
            ("pre_seed", ["pre-seed", "pre seed", "天使前", "preseed"]),
            ("seed", ["seed", "种子轮", "种子"]),
            ("series_a", ["series a", "a轮"]),
            ("growth", ["growth", "成长期"]),
            ("grant", ["grant", "资助"]),
        ]
        for stage, tokens in stage_mapping:
            if any(token in lowered for token in tokens):
                return stage
        return None

    def _extract_keywords(self, query: str) -> List[str]:
        query_text = (query or "").strip()
        if not query_text:
            return []

        raw_tokens = re.split(r"[\s,，。；;、:/]+", query_text)
        blocked = {
            "分析", "哪些", "什么", "机构", "投资", "机会", "概览", "包括", "以及", "值得", "吗",
            "的", "和", "在", "to", "for", "the", "a", "an",
        }
        keywords = []
        for token in raw_tokens:
            cleaned = token.strip().strip("?？!！")
            if len(cleaned) < 2 or cleaned.lower() in blocked or cleaned in blocked:
                continue
            keywords.append(cleaned)
        return keywords[:8]

    def _infer_scope(self, extracted: Dict[str, Any]) -> str:
        if extracted.get("organization_name") and extracted.get("organization_name") != extracted.get("country"):
            return "entity"
        if extracted.get("country") or extracted.get("country_local"):
            return "country"
        return "global"

    def _build_ontology_params(self, extracted: Dict[str, Any]) -> Dict[str, Any]:
        filter_type, filter_value = self._infer_ontology_filter(extracted.get("query", ""))
        params: Dict[str, Any] = {
            "filter_type": filter_type,
            "filter_value": filter_value,
            "limit": 20,
        }
        if extracted.get("country_local") or extracted.get("country"):
            params["country"] = extracted.get("country_local") or extracted.get("country")
        return params

    def _apply_param_override(
        self,
        params: Dict[str, Any],
        override: Optional[Dict[str, Any]],
        extracted: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not override:
            return params

        merged = dict(params)
        placeholders = {
            "country": extracted.get("country"),
            "country_local": extracted.get("country_local"),
            "organization_name": extracted.get("organization_name"),
            "representative_org": extracted.get("representative_org"),
            "query": extracted.get("query"),
            "focus_area": extracted.get("focus_area"),
            "stage": extracted.get("stage"),
        }

        for key, value in override.items():
            if value is None:
                merged.pop(key, None)
                continue

            if isinstance(value, str):
                replacement = value
                for placeholder_key, placeholder_value in placeholders.items():
                    replacement = replacement.replace(f"{{{placeholder_key}}}", str(placeholder_value or ""))
                merged[key] = replacement or None
            else:
                merged[key] = value

        return {k: v for k, v in merged.items() if v not in (None, "")}

    def _infer_ontology_filter(self, query: str) -> tuple[str, str]:
        lowered = (query or "").lower()
        for filter_type, filter_value, tokens in self.ONTOLOGY_MAPPING:
            if any(token.lower() in lowered for token in tokens):
                return filter_type, filter_value

        if any(token in lowered for token in ["faithtech", "faith tech", "christian tech", "church tech", "christian ai", "基督教科技", "基督教ai"]):
            return "organization_type", "faithtech_ai"
        if any(token in lowered for token in ["投资", "invest", "fund", "vc", "融资"]):
            return "collaboration", "seeking_investment"
        return "organization_type", "church_network"


class ExecutiveReporter:
    """Executive Report统一格式化"""

    REPORT_TEMPLATE = """## Executive Report

### Summary
{summary}

### Key Findings
{findings}

### Evidence
{evidence}

### Confidence Score: {confidence}/100
{confidence_reason}

### Risk Assessment
{risks}

### Recommendation
{recommendations}

### Next Steps
{next_steps}

---
Generated by Christian Intelligence Officer
Data sources: {sources}
"""

    @classmethod
    def format_report(
        cls,
        summary: str,
        findings: List[str],
        evidence: List[Dict[str, str]],
        confidence: int,
        confidence_reason: str,
        risks: List[str],
        recommendations: List[str],
        next_steps: List[str],
        sources: List[str],
    ) -> str:
        """
        统一格式化Executive Report
        所有Brain输出应通过此函数收口
        """

        findings_text = "\n".join([f"- {item}" for item in findings]) if findings else "- 暂无发现"
        evidence_text = (
            "\n".join(
                [
                    f"- [{e.get('source', 'unknown')}] {e.get('content', '')} (confidence: {e.get('confidence', 'N/A')})"
                    for e in evidence
                ]
            )
            if evidence
            else "- 暂无直接证据"
        )
        risks_text = "\n".join([f"- {item}" for item in risks]) if risks else "- 未发现显著风险"
        recommendations_text = (
            "\n".join([f"- {item}" for item in recommendations]) if recommendations else "- 暂无具体建议"
        )
        next_steps_text = "\n".join([f"- {item}" for item in next_steps]) if next_steps else "- 持续监测"
        sources_text = ", ".join(sources) if sources else "Multiple sources"

        normalized_confidence = int(confidence or 0)
        normalized_confidence = max(0, min(100, normalized_confidence))

        return cls.REPORT_TEMPLATE.format(
            summary=summary,
            findings=findings_text,
            evidence=evidence_text,
            confidence=normalized_confidence,
            confidence_reason=confidence_reason,
            risks=risks_text,
            recommendations=recommendations_text,
            next_steps=next_steps_text,
            sources=sources_text,
        )

    @classmethod
    def format_error_report(cls, query: str, error: str) -> str:
        """格式化错误报告"""

        return cls.format_report(
            summary=f"处理查询 '{query}' 时遇到问题",
            findings=["系统在处理过程中遇到错误"],
            evidence=[{"source": "system", "content": error, "confidence": "0"}],
            confidence=0,
            confidence_reason="系统错误导致无法评估置信度",
            risks=["数据可能不完整", "建议稍后重试或人工验证"],
            recommendations=["检查查询条件", "尝试更具体的查询", "联系系统管理员"],
            next_steps=["重试查询", "检查系统状态"],
            sources=["system"],
        )


class BrainPlannerPipeline:
    """Brain Planner完整流水线：规划 + 执行 + 报告"""

    def __init__(self):
        self.planner = QueryPlanner()
        self.reporter = ExecutiveReporter()
        self.truth_engine = TruthEngine()

    def run(self, query: str, execute_func, entities: List[str] = None) -> Dict[str, Any]:
        """
        完整执行流水线

        Args:
            query: 用户Query
            execute_func: 执行单个子任务的函数，签名: func(tool_name, params) -> result
            entities: 实体上下文

        Returns:
            {
                "plan": List[SubTask],
                "results": Dict[str, Any],
                "report": str,
                "used_plan": bool
            }
        """

        subtasks = self.planner.plan(query, entities)
        if not subtasks:
            return {"plan": [], "results": {}, "report": "", "used_plan": False}

        results: Dict[str, Any] = {}
        for st in subtasks:
            try:
                results[st.task_id] = execute_func(st.tool_name, st.params)
            except Exception as exc:
                results[st.task_id] = {"error": str(exc)}

        report = self._synthesize_report(query, subtasks, results)
        return {"plan": subtasks, "results": results, "report": report, "used_plan": True}

    def _synthesize_report(self, query: str, subtasks: List[SubTask], results: Dict[str, Any]) -> str:
        """
        综合子任务结果，生成Executive Report
        这是简化版，后续可接入LLM做更智能的综合
        """
        intent = self.planner.classify_intent(query)
        template = self.planner.QUERY_TEMPLATES.get(intent or "", {})
        if template.get("aggregation"):
            return self._synthesize_aggregate_report(query, subtasks, results, template)
        return self._synthesize_single_report(query, subtasks, results)

    def _synthesize_single_report(self, query: str, subtasks: List[SubTask], results: Dict[str, Any]) -> str:
        """生成单点查询报告"""

        findings: List[str] = []
        evidence: List[Dict[str, str]] = []
        sources: List[str] = []
        errors: List[str] = []

        for st in subtasks:
            result = results.get(st.task_id, {})
            if isinstance(result, dict) and "error" in result:
                errors.append(f"{st.description}: {result.get('error')}")
                continue

            findings.append(f"{st.description}: 已获取数据")
            sources.append(st.tool_name)

            content_text = ""
            published_at = None
            has_cross_validation = False

            if isinstance(result, dict):
                if "data" in result:
                    content_text = str(result.get("data", ""))
                else:
                    content_text = str(result)

                published_at = self._coerce_datetime(
                    result.get("published_at") or result.get("date") or result.get("created_at")
                )
                has_cross_validation = bool(result.get("cross_validated") or result.get("sources_count", 0) > 1)
            else:
                content_text = str(result)

            confidence_report = self.truth_engine.generate_confidence_report(
                st.tool_name,
                content_text,
                published_at=published_at,
                has_cross_validation=has_cross_validation,
            )
            evidence.append(
                {
                    "source": st.tool_name,
                    "content": content_text[:200],
                    "confidence": str(int(confidence_report["confidence_score"] * 100)),
                }
            )

        if evidence:
            confidences: List[int] = []
            for e in evidence:
                raw = (e.get("confidence") or "").strip()
                try:
                    confidences.append(int(raw))
                except Exception:
                    continue
            avg_confidence = sum(confidences) // len(confidences) if confidences else 50
        else:
            avg_confidence = 30

        recommendations = ["基于当前数据制定行动方案", "如需更深入分析，请提供具体机构名称"]
        if errors:
            recommendations.append(f"注意：{len(errors)}个子任务执行失败，数据可能不完整")

        risks = ["数据时效性需关注", "分析基于可用数据，可能存在信息缺口"]
        risks.extend([f"执行错误: {item}" for item in errors[:3]])

        return self.reporter.format_report(
            summary=f"针对「{query}」的情报分析已完成，共执行{len(subtasks)}个子任务。",
            findings=findings,
            evidence=evidence,
            confidence=avg_confidence,
            confidence_reason=f"基于{len(evidence)}条证据的综合评估",
            risks=risks,
            recommendations=recommendations,
            next_steps=["深入分析特定机构", "查看原始数据来源", "设置监测任务跟踪动态"],
            sources=sorted(set(sources)),
        )

    def _synthesize_aggregate_report(
        self,
        query: str,
        subtasks: List[SubTask],
        results: Dict[str, Any],
        template: Dict[str, Any],
    ) -> str:
        """生成聚合型市场概览报告"""

        market_snapshot = self._load_market_snapshot(focus_area="faithtech")
        query_database_items: List[Dict[str, Any]] = []
        ontology_orgs: List[Dict[str, Any]] = []
        investor_data: List[Dict[str, Any]] = []
        funding_data: List[Dict[str, Any]] = []
        representative_profile: Dict[str, Any] = {}
        evidence: List[Dict[str, str]] = []
        sources: List[str] = []
        errors: List[str] = []

        for st in subtasks:
            result = results.get(st.task_id, {})
            if isinstance(result, dict) and "error" in result:
                errors.append(f"{st.description}: {result.get('error')}")
                continue

            payload = self._extract_result_payload(result)
            if st.tool_name == "query_database":
                query_database_items = payload.get("items", []) if isinstance(payload, dict) else []
            elif st.tool_name == "query_ontology":
                ontology_orgs = payload.get("organizations", []) if isinstance(payload, dict) else []
            elif st.tool_name == "query_investors":
                investor_data = payload.get("investors", []) if isinstance(payload, dict) else []
            elif st.tool_name == "query_funding_rounds":
                funding_data = payload.get("rounds", []) if isinstance(payload, dict) else []
            elif st.tool_name == "query_organization_profile":
                representative_profile = payload.get("organization", payload) if isinstance(payload, dict) else {}

            content_text = str(payload if payload else result)
            confidence_report = self.truth_engine.generate_confidence_report(st.tool_name, content_text)
            evidence.append(
                {
                    "source": st.tool_name,
                    "content": self._build_aggregate_evidence_text(st.tool_name, payload, market_snapshot),
                    "confidence": str(int(confidence_report["confidence_score"] * 100)),
                }
            )
            sources.append(st.tool_name)

        top_regions = ", ".join(
            [f"{country}({count})" for country, count in market_snapshot.get("regional_distribution", [])[:5]]
        ) or "暂无区域聚合样本"
        type_distribution = ", ".join(
            [f"{name}({count})" for name, count in market_snapshot.get("type_distribution", [])[:5]]
        ) or "FaithTech标签仍在持续补标"
        ai_dist = market_snapshot.get("ai_maturity_distribution", {})
        top_orgs = market_snapshot.get("top_ai_orgs", [])
        key_player_candidates: List[str] = []
        rep_name = representative_profile.get("name") if isinstance(representative_profile, dict) else None
        if rep_name:
            key_player_candidates.append(rep_name)
        for round_item in funding_data[:8]:
            entity_name = (round_item.get("entity_name") or "").strip()
            if entity_name:
                key_player_candidates.append(entity_name)
        for item in top_orgs[:8]:
            if (item.get("ai_maturity_score") or 0) >= 2 and item.get("name"):
                key_player_candidates.append(item["name"])
        key_player_names = list(dict.fromkeys(key_player_candidates))[:6]
        top_org_lines = [
            f"{item.get('name', 'N/A')} (AI: {item.get('ai_maturity_score', 'N/A')}, {item.get('country', 'N/A')})"
            for item in top_orgs[:5]
        ]
        investor_names = [item.get("name", "N/A") for item in investor_data[:5]]
        investor_text = "、".join(investor_names) if investor_names else "暂无高置信活跃投资方样本"

        summary = (
            f"{template.get('report_override', {}).get('title', 'Christian Tech Global Market Overview')}："
            f"基于{market_snapshot.get('org_count', 0)}家机构、{market_snapshot.get('funding_count', 0)}条融资事件、"
            f"{market_snapshot.get('investor_count', 0)}家投资机构的数据库快照生成。"
        )

        findings = [
            f"市场规模：当前数据库收录机构 {market_snapshot.get('org_count', 0)} 家，其中带官网 {market_snapshot.get('url_count', 0)} 家、People 画像 {market_snapshot.get('people_count', 0)} 家、深度档案 {market_snapshot.get('deep_profile_count', 0)} 家",
            f"区域分布：{top_regions}",
            f"AI成熟度分布：0-1分 {ai_dist.get('0-1', 0)} 家，2-3分 {ai_dist.get('2-3', 0)} 家，4-5分 {ai_dist.get('4-5', 0)} 家，未评分 {ai_dist.get('unknown', 0)} 家",
            f"融资概览：数据库收录 {market_snapshot.get('funding_count', 0)} 条融资事件，披露金额合计约 ${market_snapshot.get('funding_total_amount_m', 0):.1f}M",
            f"类型分布：{type_distribution}",
            f"关键玩家：{'、'.join(key_player_names) if key_player_names else ('; '.join(top_org_lines) if top_org_lines else '暂无高AI成熟度代表机构样本')}",
            f"活跃投资方样本：{investor_text}",
        ]

        if representative_profile:
            rep_name = representative_profile.get("name") or "代表机构"
            rep_country = representative_profile.get("country") or "N/A"
            rep_ai = representative_profile.get("ai_maturity_score", "N/A")
            findings.append(f"高AI代表机构：{rep_name}（{rep_country}，AI成熟度 {rep_ai}）")

        recommendations = [
            "优先跟踪 AI 成熟度 4-5 分且已有官网/产品化能力的机构，作为 Christian Tech 头部样本池",
            "东南亚尤其菲律宾在组织密度上具备潜力，但资本覆盖仍弱，适合作为白地带优先研究区域",
            "持续扩充 FaithTech 标签与融资事件映射，避免市场概览退化成通用投资匹配",
        ]
        risks = [
            f"URL覆盖率仍有限（当前 {market_snapshot.get('url_count', 0)}/{market_snapshot.get('org_count', 0)}）",
            f"People覆盖率仍薄（当前 {market_snapshot.get('people_count', 0)}/{market_snapshot.get('org_count', 0)}）",
            "融资数据仍是 curated subset，尚不是完整实时市场 feed",
        ]
        risks.extend([f"执行错误: {item}" for item in errors[:3]])

        confidence_values = []
        for item in evidence:
            try:
                confidence_values.append(int(item.get("confidence", "0")))
            except Exception:
                continue
        avg_confidence = sum(confidence_values) // len(confidence_values) if confidence_values else 65

        return self.reporter.format_report(
            summary=summary,
            findings=findings,
            evidence=evidence or [{"source": "system", "content": "聚合报告未取得足够直接证据", "confidence": "40"}],
            confidence=avg_confidence,
            confidence_reason=f"基于{market_snapshot.get('org_count', 0)}家机构数据库快照与{len(evidence)}个聚合子任务结果生成",
            risks=risks,
            recommendations=recommendations,
            next_steps=["扩充 FaithTech 标签覆盖", "补足高AI机构官网与People档案", "建立全球市场自动化监测面板"],
            sources=sorted(set(sources + ["CIO Database", "ARDA", "Wikipedia", "Wikidata"])),
        )

    def _extract_result_payload(self, result: Any) -> Any:
        if isinstance(result, dict) and "data" in result:
            return result.get("data")
        return result

    def _build_aggregate_evidence_text(self, tool_name: str, payload: Any, snapshot: Dict[str, Any]) -> str:
        if tool_name == "query_database" and isinstance(payload, dict):
            return f"全局情报信号 {payload.get('count', 0)} 条；数据库机构总量 {snapshot.get('org_count', 0)} 家"
        if tool_name == "query_ontology" and isinstance(payload, dict):
            return f"FaithTech/AI 相关标签样本 {payload.get('count', 0)} 家"
        if tool_name == "query_investors" and isinstance(payload, dict):
            return f"命中活跃投资机构样本 {payload.get('count', 0)} 家"
        if tool_name == "query_funding_rounds" and isinstance(payload, dict):
            return f"命中融资事件样本 {payload.get('count', 0)} 条"
        if tool_name == "query_organization_profile" and isinstance(payload, dict):
            org = payload.get("organization", {}) if isinstance(payload.get("organization"), dict) else {}
            org_name = org.get("name") or payload.get("org_name") or "代表机构"
            return f"高AI代表机构样本：{org_name}"
        return str(payload)[:200]

    def _load_market_snapshot(self, focus_area: Optional[str] = None) -> Dict[str, Any]:
        try:
            from sqlalchemy import func, or_
            from models.database import (
                FundingRound,
                Investor,
                KnowledgeEntity,
                OrganizationOntologyTag,
                OrganizationProfile,
                OrganizationType,
                get_db,
            )

            db = next(get_db())
            try:
                org_query = db.query(OrganizationProfile)
                filtered_org_ids: List[str] = []
                type_distribution: List[tuple[str, int]] = []
                faithtech_tag_ids = {
                    "faithtech_ai",
                    "faithtech_bible",
                    "faithtech_worship",
                    "faithtech_social",
                    "faithtech_media",
                    "faithtech_fintech",
                    "faithtech_education",
                }

                if focus_area == "faithtech":
                    filtered_org_ids = [
                        row[0]
                        for row in (
                            db.query(OrganizationOntologyTag.organization_id)
                            .filter(
                                OrganizationOntologyTag.tag_type == "organization_type",
                                OrganizationOntologyTag.tag_id.in_(list(faithtech_tag_ids)),
                            )
                            .distinct()
                            .all()
                        )
                    ]
                    if filtered_org_ids:
                        org_query = org_query.filter(OrganizationProfile.id.in_(filtered_org_ids))

                    tag_name_map = {
                        row.id: row.name
                        for row in db.query(OrganizationType).filter(OrganizationType.id.in_(list(faithtech_tag_ids))).all()
                    }
                    tag_counts = (
                        db.query(OrganizationOntologyTag.tag_id, func.count(OrganizationOntologyTag.organization_id))
                        .filter(
                            OrganizationOntologyTag.tag_type == "organization_type",
                            OrganizationOntologyTag.tag_id.in_(list(faithtech_tag_ids)),
                        )
                        .group_by(OrganizationOntologyTag.tag_id)
                        .all()
                    )
                    type_distribution = sorted(
                        [(tag_name_map.get(tag_id, tag_id), int(count)) for tag_id, count in tag_counts],
                        key=lambda item: item[1],
                        reverse=True,
                    )

                orgs = org_query.all()
                org_count = len(orgs)
                url_count = sum(1 for org in orgs if (org.official_website or "").strip())
                people_count = sum(1 for org in orgs if (org.leader_name or "").strip())
                deep_profile_count = sum(
                    1
                    for org in orgs
                    if (org.description or "").strip()
                    or (org.about_text or "").strip()
                    or org.ai_maturity_score is not None
                    or org.digital_score is not None
                )

                country_counter = Counter((org.country or "Unknown").strip() or "Unknown" for org in orgs)
                regional_distribution = country_counter.most_common(8)

                ai_maturity_distribution = {"0-1": 0, "2-3": 0, "4-5": 0, "unknown": 0}
                for org in orgs:
                    score = org.ai_maturity_score
                    if score is None:
                        ai_maturity_distribution["unknown"] += 1
                    elif score <= 1:
                        ai_maturity_distribution["0-1"] += 1
                    elif score <= 3:
                        ai_maturity_distribution["2-3"] += 1
                    else:
                        ai_maturity_distribution["4-5"] += 1

                sorted_orgs = sorted(
                    orgs,
                    key=lambda org: (
                        org.ai_maturity_score if org.ai_maturity_score is not None else -1,
                        org.digital_score if org.digital_score is not None else -1,
                        org.updated_at or datetime.min,
                    ),
                    reverse=True,
                )
                top_ai_orgs = [
                    {
                        "name": org.name,
                        "country": org.country,
                        "ai_maturity_score": org.ai_maturity_score,
                        "digital_score": org.digital_score,
                    }
                    for org in sorted_orgs[:8]
                ]

                investor_count = db.query(Investor).count()

                rounds = (
                    db.query(FundingRound.amount, KnowledgeEntity.category, KnowledgeEntity.entity_type, KnowledgeEntity.name)
                    .join(KnowledgeEntity, FundingRound.entity_id == KnowledgeEntity.id)
                    .all()
                )
                funding_aliases = {
                    "faithtech",
                    "bible tech",
                    "church tech",
                    "christian ai",
                    "christian media",
                    "media",
                    "technology",
                    "ai",
                }
                funding_items = []
                for amount, category, entity_type, entity_name in rounds:
                    tokens = {
                        str(category or "").strip().lower(),
                        str(entity_type or "").strip().lower(),
                        str(entity_name or "").strip().lower(),
                    }
                    if focus_area == "faithtech" and not (tokens & funding_aliases):
                        continue
                    funding_items.append(amount or 0.0)
                funding_count = len(funding_items)
                funding_total_amount_m = round(sum(funding_items) / 1_000_000, 1) if funding_items else 0.0

                return {
                    "org_count": org_count,
                    "url_count": url_count,
                    "people_count": people_count,
                    "deep_profile_count": deep_profile_count,
                    "regional_distribution": regional_distribution,
                    "ai_maturity_distribution": ai_maturity_distribution,
                    "type_distribution": type_distribution,
                    "top_ai_orgs": top_ai_orgs,
                    "investor_count": investor_count,
                    "funding_count": funding_count,
                    "funding_total_amount_m": funding_total_amount_m,
                    "filtered_org_ids": filtered_org_ids,
                }
            finally:
                db.close()
        except Exception:
            return {
                "org_count": 0,
                "url_count": 0,
                "people_count": 0,
                "deep_profile_count": 0,
                "regional_distribution": [],
                "ai_maturity_distribution": {"0-1": 0, "2-3": 0, "4-5": 0, "unknown": 0},
                "type_distribution": [],
                "top_ai_orgs": [],
                "investor_count": 0,
                "funding_count": 0,
                "funding_total_amount_m": 0.0,
                "filtered_org_ids": [],
            }

    def _coerce_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            normalized = raw.replace("Z", "+00:00")
            for candidate in [normalized, raw]:
                try:
                    return datetime.fromisoformat(candidate)
                except Exception:
                    continue
        return None

    def generate_executive_report(self, query_type: str, context: List[Dict[str, Any]], target: str) -> str:
        """为复杂分析模式生成简版 Executive Report。"""
        findings: List[str] = []
        evidence: List[Dict[str, str]] = []
        sources: List[str] = []

        for item in context:
            tool_name = item.get("tool", "unknown")
            result = item.get("result")
            findings.append(f"{tool_name}: 已完成")
            sources.append(tool_name)
            evidence.append(
                {
                    "source": tool_name,
                    "content": str(result)[:200],
                    "confidence": "70",
                }
            )

        summary_map = {
            "country_deep": f"已完成 {target} 的国家深度分析，整合国家宗教概况、机构分布、新闻与投资线索。",
            "competitor_landscape": f"已完成 {target} 的竞争格局分析，输出目标机构与同类机构的对比视图。",
            "investment_opportunity": f"已完成 {target} 的投资机会分析，初步筛出值得继续尽调的目标。",
        }

        return self.reporter.format_report(
            summary=summary_map.get(query_type, f"已完成 {target} 的综合分析。"),
            findings=findings or ["已完成多步分析，但当前可用证据较少"],
            evidence=evidence or [{"source": "system", "content": "暂无充足证据", "confidence": "40"}],
            confidence=72 if evidence else 40,
            confidence_reason=f"基于 {len(evidence)} 条多步执行结果综合生成",
            risks=["部分步骤可能受数据库覆盖率限制", "建议对关键结论做人工复核"],
            recommendations=["优先查看关键机构详情", "将结果作为进一步尽调输入"],
            next_steps=["补充缺失字段", "扩展目标机构样本", "继续跟踪近期动态"],
            sources=sorted(set(sources)) or ["system"],
        )


# ========== 复杂分析模式（新增） ==========


class AnalysisPatterns:
    """三种复杂分析模式的 Plan 模板。"""

    COUNTRY_DEEP_ANALYSIS = """
分析目标：{country} 基督教行业深度分析

执行步骤：
1. 【国家概况】调用 query_arda_country 获取宗教数据
2. 【机构扫描】调用 query_database 获取该国Top机构
3. 【新闻动态】调用 query_intelligence 获取近期新闻
4. 【投资概况】调用 query_investors 获取该国投资机构
5. 【综合报告】整合以上信息生成Executive Report

输出格式：
## {country} 基督教行业深度分析
### 国家宗教概况
（ARDA数据）

### 主要机构（Top 10）
（机构列表+负责人+AI成熟度）

### 近期动态
（新闻摘要）

### 投资机会
（投资机构+匹配建议）

### 风险提示
（政策/安全/竞争）
"""

    COMPETITOR_LANDSCAPE = """
分析目标：{entity} 竞争格局分析

执行步骤：
1. 【机构画像】调用 query_organization_profile 获取目标机构详情
2. 【同类扫描】调用 query_database 获取同国家同类型机构
3. 【对比分析】对比规模/AI成熟度/People/Programs
4. 【机会识别】找出差异化合作或竞争机会

输出格式：
## {entity} 竞争格局
### 目标机构概况
### 同类机构对比（3-5家）
| 机构 | 国家 | 类型 | AI成熟度 | People | 差异化 |
### 合作机会
### 竞争威胁
"""

    INVESTMENT_OPPORTUNITY = """
分析目标：{country}/{sector} 投资机会分析

执行步骤：
1. 【机构筛选】调用 query_database 筛选高成长机构
2. 【AI成熟度排序】按ai_maturity_score降序
3. 【Funding概况】调用 query_investors 获取投资数据
4. 【推荐排序】综合AI+People+Programs+Country排名

输出格式：
## {country} {sector} 投资机会
### 推荐机构（Top 5）
| 机构 | AI成熟度 | People | 缺口 | 投资价值 |
### 投资匹配
### 入场建议
"""


def detect_analysis_type(user_message: str) -> Optional[str]:
    """检测用户查询是否为分析类，返回分析类型与目标。"""
    if not user_message:
        return None

    country_analysis_patterns = [
        r"(.+?)\s*(?:的)?深度分析",
        r"(.+?)\s*(?:的)?行业分析",
        r"(.+?)\s*(?:的)?(?:基督教|教会|宣教)(?:行业|生态|概况)",
        r"分析\s*(.+?)\s*(?:的)?(?:基督教|教会)",
        r"(?:深度|全面|详细)了解\s*(.+?)",
        r"(?:give me|need|want)\s+(?:deep|full|comprehensive)\s+analysis\s+(?:of|on)?\s*(.+?)$",
        r"what'?s\s+(?:the\s*)?(?:christian|church)\s+landscape\s+(?:in|of)?\s*(.+?)$",
    ]

    competitor_patterns = [
        r"(.+?)\s*(?:的)?竞争(?:格局|分析|对手)",
        r"(.+?)\s*(?:的)?同类机构",
        r"(?:和|与)\s*(.+?)\s*(?:对比|比较)",
        r"(?:competitor|competitive|landscape)\s+(?:of|for)?\s*(.+?)$",
        r"compare\s+(.+?)\s+(?:with|and)\s+.+$",
        r"who\s+(?:competes|is competing)\s+(?:with|against)?\s*(.+?)$",
    ]

    investment_patterns = [
        r"(.+?)\s*(?:的)?投资(?:机会|分析|建议)",
        r"(.+?)\s*(?:值得|适合)(?:投资|合作)",
        r"(?:investment|opportunity|deal\s+flow)\s+(?:in|for)?\s*(.+?)$",
        r"where\s+(?:to|should)\s+(?:invest|partner)\s+(?:in|for)?\s*(.+?)$",
        r"(?:best|top)\s+(?:investment|partnership)\s+(?:in|for)?\s*(.+?)$",
    ]

    def _extract_best_target(patterns: List[str]) -> Optional[str]:
        for pattern in patterns:
            match = re.search(pattern, user_message, re.IGNORECASE)
            if match:
                candidate = (match.group(1) or "").strip(" ?，,。.!")
                if candidate:
                    return candidate
        return None

    planner = QueryPlanner()

    candidate = _extract_best_target(country_analysis_patterns)
    if candidate:
        country = planner._extract_country_info(candidate)[0] or candidate
        return f"COUNTRY_DEEP:{country}"

    candidate = _extract_best_target(competitor_patterns)
    if candidate:
        return f"COMPETITOR:{candidate}"

    candidate = _extract_best_target(investment_patterns)
    if candidate:
        country = planner._extract_country_info(candidate)[0] or candidate
        return f"INVESTMENT:{country}"

    return None


def build_analysis_plan(analysis_type: str, target: str) -> List[SubTask]:
    """根据分析类型构建多步分析计划。"""
    normalized_target = (target or "").strip()
    if not normalized_target:
        return []

    if analysis_type == "COUNTRY_DEEP":
        return [
            SubTask(task_id="analysis_1", tool_name="query_arda_country", params={"country": normalized_target}, description="国家宗教概况", priority=1),
            SubTask(task_id="analysis_2", tool_name="query_database", params={"scope": "country", "country": normalized_target, "limit": 10}, description="机构扫描", priority=2),
            SubTask(task_id="analysis_3", tool_name="query_intelligence", params={"scope": "country", "country": normalized_target, "limit": 5}, description="新闻动态", priority=3),
            SubTask(task_id="analysis_4", tool_name="query_investors", params={"country": normalized_target}, description="投资机会", priority=4),
            SubTask(task_id="analysis_5", tool_name="executive_report", params={"type": "country_deep", "country": normalized_target}, description="综合报告", priority=5),
        ]
    if analysis_type == "COMPETITOR":
        return [
            SubTask(task_id="analysis_1", tool_name="query_organization_profile", params={"org_name": normalized_target}, description="目标机构画像", priority=1),
            SubTask(task_id="analysis_2", tool_name="query_database", params={"scope": "country", "entity": normalized_target, "limit": 8}, description="同类扫描", priority=2),
            SubTask(task_id="analysis_3", tool_name="executive_report", params={"type": "competitor_landscape", "entity": normalized_target}, description="对比报告", priority=3),
        ]
    if analysis_type == "INVESTMENT":
        return [
            SubTask(task_id="analysis_1", tool_name="query_database", params={"scope": "country", "country": normalized_target, "limit": 10}, description="机构筛选", priority=1),
            SubTask(task_id="analysis_2", tool_name="query_database", params={"scope": "country", "country": normalized_target, "keywords": ["AI", "digital"], "limit": 10}, description="AI成熟度排序", priority=2),
            SubTask(task_id="analysis_3", tool_name="query_investors", params={"country": normalized_target}, description="投资概况", priority=3),
            SubTask(task_id="analysis_4", tool_name="executive_report", params={"type": "investment_opportunity", "country": normalized_target}, description="推荐报告", priority=4),
        ]
    return []
