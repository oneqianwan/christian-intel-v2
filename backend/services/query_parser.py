"""
规则解析器：零 LLM，直接 SQL 查询常见模式
数据库能回答的问题，绝不走 Agent
"""

import re
from typing import Dict, Optional, List

from sqlalchemy import or_, func

from models.database import IntelligenceItem, OrganizationProfile, RelationEdge, get_db_session
from services.welcome_trace import emit_welcome_trace, register_welcome_reply


_CONVERSATION_LANG_PREF: dict[str, str] = {}


class QueryParser:
    GREETING_TOKENS = ["你好", "hi", "hello", "早上好", "下午好", "晚上好"]
    SCORE_INTENT_NAME = "organization_score_lookup"
    SCORE_RESPONSE_CONTRACT = "score_lookup"
    SCORE_ALL_FIELDS = ["people_score", "digital_score", "intel_score"]
    RELATIONSHIP_GRAPH_INTENT_NAME = "organization_relationship_graph_lookup"
    RELATIONSHIP_GRAPH_RESPONSE_CONTRACT = "relationship_graph"

    """规则解析器：匹配常见查询模式，直接返回数据库结果"""

    SCORE_KEYWORDS = [
        r"score",
        r"评分",
        r"分数",
        r"得分",
        r"people score",
        r"digital score",
        r"intel score",
        r"composite score",
        r"综合评分",
        r"评分是多少",
        r"分数多少",
    ]

    COMPARE_KEYWORDS = [
        r"compare",
        r"对比",
        r"比较",
        r"vs\b",
        r"versus",
        r"谁更强",
        r"谁更好",
        r"哪个更高",
        r"谁的评分",
        r"评分更高",
        r"分数更高",
    ]

    INVESTMENT_KEYWORDS = [
        r"invested in",
        r"投资了",
        r"投资了谁",
        r"投资哪些",
        r"谁投资了",
        r"who invested in",
        r"partnered with",
        r"合作关系",
    ]

    EXISTENCE_KEYWORDS = [
        r"数据库里有多少",
        r"how many.*in the database",
        r"覆盖率",
        r"coverage",
    ]

    CONTACT_KEYWORDS = [
        r"contact",
        r"contacts",
        r"联系方式",
        r"联系信息",
        r"邮箱",
        r"电话",
        r"负责人",
        r"对接",
    ]

    RELATIONSHIP_GRAPH_KEYWORDS = [
        r"relationship\s+graph",
        r"relationship\s+network",
        r"\bnetwork\b",
        r"\bconnected\s+to\b",
        r"\bpartners?\b",
        r"\brelated\s+organizations?\b",
        r"关系图谱",
        r"关系网络",
        r"合作网络",
        r"关系边",
        r"关联机构",
        r"合作方",
        r"有关联",
    ]

    PROFILE_KEYWORDS = [
        r"profile",
        r"介绍",
        r"是什么机构",
        r"是什么组织",
        r"信息",
        r"情况",
    ]

    CAPABILITIES_KEYWORDS = [
        r"你会什么",
        r"你能做什么",
        r"你可以做什么",
        r"具备哪些能力",
        r"有哪些能力",
        r"支持哪些功能",
        r"capabilities",
        r"what can you do",
        r"what can you help",
        r"features",
        r"functions",
    ]

    def __init__(self):
        self.db = get_db_session()
        self._lang = "en"

    def parse(self, user_message: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        msg = (user_message or "").strip()
        if not msg:
            return None

        # ===== Phase 0: 通用意图 + 语言检测 =====
        msg_lower = msg.lower().strip()
        lang = "en"
        if re.search(r"[\u4e00-\u9fff]", msg) or any(p in msg_lower for p in ["中文", "用中文", "说中文"]):
            lang = "zh"
        self._lang = lang

        greeting_matched = self._match_greeting(msg)
        greeting_only = self._is_greeting_only(msg)

        if any(p in msg_lower for p in ["你能理解中文", "你会中文", "支持中文", "懂中文"]):
            return {
                "data_found": True,
                "response": "是的，我完全支持中文交流。你可以用中文向我查询任何 Christian 机构的信息。",
                "direct_answer": True,
            }

        weather_keywords = ["天气", "股票", "比特币", "笑话", "唱歌", "今天星期", "几点了"]
        if any(p in msg_lower for p in weather_keywords):
            return {
                "data_found": True,
                "response": "我只回答与 Christian 机构相关的问题，包括机构评分、投资关系、情报时间线等。请问你想了解哪家机构？"
                if lang == "zh"
                else "I only answer questions related to Christian organizations. How can I help you today?",
                "direct_answer": True,
            }

        if greeting_matched:
            direct_answer = bool(greeting_only)
            print(
                "[GreetingHandler] "
                f"Question={msg} | "
                f"GreetingMatched={greeting_matched} | "
                f"GreetingOnly={greeting_only} | "
                f"DirectAnswer={direct_answer}"
            )

        if greeting_matched and greeting_only:
            response = self._assistant_greeting(lang)
            welcome_reply_uuid = register_welcome_reply(conversation_id, response)
            emit_welcome_trace(
                "GENERATE_UUID",
                welcome_reply_uuid,
                conversation_id=conversation_id,
                extra={"file": "backend/services/query_parser.py", "function": "QueryParser.parse", "line": 148},
            )
            emit_welcome_trace(
                "RETURN_UUID",
                welcome_reply_uuid,
                conversation_id=conversation_id,
                extra={"file": "backend/services/query_parser.py", "function": "QueryParser.parse", "line": 149},
            )
            return {
                "data_found": True,
                "response": response,
                "direct_answer": True,
                "welcome_reply_uuid": welcome_reply_uuid,
            }

        if self._is_assistant_intro_query(msg):
            return self._handle_assistant_intro_query(msg, conversation_id=conversation_id)

        if self._is_capabilities_query(msg):
            return self._handle_capabilities_query(msg, conversation_id=conversation_id)

        lang_cmd = self._detect_language_command(msg)
        if lang_cmd:
            if conversation_id:
                _CONVERSATION_LANG_PREF[conversation_id] = lang_cmd
            if lang_cmd == "zh":
                return {"data_found": True, "response": "好的，我会用中文回答。", "direct_answer": True}
            return {"data_found": True, "response": "OK. I will answer in English.", "direct_answer": True}

        if self._is_existence_query(msg):
            return self._handle_existence_query(msg, conversation_id=conversation_id)

        if self._is_relationship_graph_query(msg):
            return self._handle_relationship_graph_query(msg, conversation_id=conversation_id)

        if self._is_contact_query(msg):
            return self._handle_contact_query(msg, conversation_id=conversation_id)

        if self._is_org_profile_query(msg):
            return self._handle_org_profile_query(msg, conversation_id=conversation_id)

        if self._is_compare_query(msg):
            return self._handle_compare_query(msg, conversation_id=conversation_id)

        if self._is_score_query(msg):
            return self._handle_score_query(msg, conversation_id=conversation_id)

        if self._is_investment_in_query(msg):
            return self._handle_investment_in(msg, conversation_id=conversation_id)

        if self._is_investment_out_query(msg):
            return self._handle_investment_out(msg, conversation_id=conversation_id)

        if self._is_intelligence_timeline_query(msg):
            return self._handle_intelligence_timeline(msg, conversation_id=conversation_id)

        return None

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:
            return

    def _is_score_query(self, msg: str) -> bool:
        return any(re.search(kw, msg, re.IGNORECASE) for kw in self.SCORE_KEYWORDS)

    def _extract_requested_scores(self, msg: str) -> List[str]:
        raw = str(msg or "")
        requested: list[str] = []

        score_patterns = [
            ("people_score", [r"\bpeople\s+score(?:s)?\b", r"人员评分", r"people/digital/intel\s+score"]),
            ("digital_score", [r"\bdigital\s+score(?:s)?\b", r"数字评分", r"people/digital/intel\s+score"]),
            ("intel_score", [r"\bintel\s+score(?:s)?\b", r"情报评分", r"people/digital/intel\s+score"]),
            ("composite_score", [r"\bcomposite\s+score(?:s)?\b", r"\boverall\s+score(?:s)?\b", r"综合评分"]),
        ]

        for field_name, patterns in score_patterns:
            if any(re.search(pattern, raw, re.IGNORECASE) for pattern in patterns):
                requested.append(field_name)

        if requested:
            canonical_order = ["people_score", "digital_score", "intel_score", "composite_score"]
            return [field for field in canonical_order if field in requested]

        if re.search(r"三项评分|all\s+scores|show\s+me.+scores|give\s+me.+scores", raw, re.IGNORECASE):
            return list(self.SCORE_ALL_FIELDS)

        return list(self.SCORE_ALL_FIELDS)

    def _clean_score_org_candidate(self, candidate: str) -> Optional[str]:
        clean = (candidate or "").strip()
        if not clean:
            return None

        clean = clean.strip(" \t\r\n?？!！,，.。:：;；\"'`/()[]{}")
        clean = re.sub(
            r"^(?:what\s+is\s+the\s+score\s+of|what\s+is\s+the|what\s+is|show\s+me|give\s+me|tell\s+me|query|查询一下|查询|查一下|查|给我|请给我|请查询|告诉我|请告诉我)(?:\s+|[:：])+",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"^(?:of|for)\s+", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"(?:的)?(?:people|digital|intel|composite|overall)\s+score(?:s)?$", "", clean, flags=re.IGNORECASE)
        clean = re.sub(
            r"(?:的)?(?:people\s*/\s*digital\s*/\s*intel\s+score(?:s)?|people\s*,\s*digital\s+and\s+intel\s+score(?:s)?|people,\s*digital\s+and\s+intel\s+score(?:s)?|三项评分|评分是多少|评分多少|评分|分数|得分|score(?:s)?)$",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"(?:是多少|多少|是什么|为多少)$", "", clean, flags=re.IGNORECASE)
        clean = clean.strip()
        clean = re.sub(r"(?:的)?(?:people|digital|intel|composite|overall)\s+score(?:s)?\s*$", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"(?:的)?(?:score(?:s)?|评分|分数|得分)\s*$", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" \t\r\n?？!！,，.。:：;；\"'`/()[]{}")
        if len(clean) <= 1:
            return None
        return clean

    def _extract_score_org_name(self, msg: str) -> Optional[str]:
        raw = (msg or "").strip()
        patterns = [
            r"(?:people|digital|intel|composite|overall)?\s*score(?:s)?\s+of\s+(.+?)(?:\?|？|$)",
            r"(?:show\s+me|give\s+me|tell\s+me|查询一下|查询|查一下|查|给我|请给我|请查询|告诉我|请告诉我)\s+(.+?)(?:\?|？|$)",
            r"(.+?)(?:的)?(?:people\s*/\s*digital\s*/\s*intel\s+score(?:s)?|people\s*,\s*digital\s+and\s+intel\s+score(?:s)?|三项评分|people\s+score(?:s)?|digital\s+score(?:s)?|intel\s+score(?:s)?|composite\s+score(?:s)?|overall\s+score(?:s)?|评分是多少|评分多少|评分|分数|得分|score(?:s)?)(?:\?|？|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            candidate = self._clean_score_org_candidate(match.group(1) or "")
            if candidate:
                return candidate

        return self._clean_score_org_candidate(raw)

    def _build_score_lookup_intent(self, msg: str) -> Optional[Dict]:
        if not self._is_score_query(msg):
            return None

        organization_name = self._extract_score_org_name(msg)
        if not organization_name:
            return None

        requested_scores = self._extract_requested_scores(msg)
        return {
            "data_found": False,
            "direct_answer": False,
            "intent": self.SCORE_INTENT_NAME,
            "organization_name": organization_name,
            "requested_scores": requested_scores,
            "response_contract": self.SCORE_RESPONSE_CONTRACT,
            "requires_database_lookup": True,
        }

    def _is_compare_query(self, msg: str) -> bool:
        return any(re.search(kw, msg, re.IGNORECASE) for kw in self.COMPARE_KEYWORDS)

    def _is_investment_out_query(self, msg: str) -> bool:
        patterns = [
            r"(.+?)(?:投资了谁|投资了哪些|invested who)",
            r"(.+?)(?:的投资关系|的投资)",
            r"(?:what organizations did|which organizations did)\s+(.+?)\s+invested in",
        ]
        return any(re.search(p, msg, re.IGNORECASE) for p in patterns)

    def _is_investment_in_query(self, msg: str) -> bool:
        patterns = [
            r"谁投资了(.+)",
            r"who invested in (.+)",
            r"(.+?)的投资方",
            r"who invested in by (.+)",
        ]
        return any(re.search(p, msg, re.IGNORECASE) for p in patterns)

    def _is_existence_query(self, msg: str) -> bool:
        return any(
            re.search(kw, msg, re.IGNORECASE)
            for kw in [
                r"数据库里有多少",
                r"how many.*in the database",
                r"覆盖率",
                r"coverage",
                r"how many organizations have",
                r"how many.*have.*score",
                r"how many.*have.*>",
            ]
        )

    def _is_intelligence_timeline_query(self, msg: str) -> bool:
        """是否是情报时间线查询"""
        patterns = [
            r"show.*latest.*intelligence",
            r"latest.*intelligence.*about",
            r"show.*news.*about",
            r"最近.*情报",
            r"最新.*动态",
            r"时间线",
            r"timeline",
        ]
        return any(re.search(p, msg, re.IGNORECASE) for p in patterns)

    def _is_contact_query(self, msg: str) -> bool:
        return any(re.search(kw, msg, re.IGNORECASE) for kw in self.CONTACT_KEYWORDS)

    def _is_relationship_graph_query(self, msg: str) -> bool:
        raw = str(msg or "").strip()
        if not raw:
            return False
        if self._is_score_query(raw) or self._is_contact_query(raw):
            return False
        return any(re.search(kw, raw, re.IGNORECASE) for kw in self.RELATIONSHIP_GRAPH_KEYWORDS)

    def _is_capabilities_query(self, msg: str) -> bool:
        return any(re.search(kw, msg, re.IGNORECASE) for kw in self.CAPABILITIES_KEYWORDS)

    def _is_greeting_only(self, msg: str) -> bool:
        normalized = re.sub(r"[\s,.!?\-，。！？；;:：]+", "", str(msg or "").lower())
        return normalized in {"你好", "hello", "hi", "早上好", "下午好", "晚上好"}

    def _match_greeting(self, msg: str) -> bool:
        lowered = str(msg or "").lower()
        return any(token in lowered for token in self.GREETING_TOKENS)

    def _is_assistant_intro_query(self, msg: str) -> bool:
        patterns = [
            r"介绍一下你自己",
            r"介绍你自己",
            r"自我介绍",
            r"你是谁",
            r"你是干什么的",
            r"你能做什么",
            r"你可以做什么",
            r"具备哪些能力",
            r"有哪些能力",
            r"支持哪些功能",
            r"怎么使用",
            r"如何使用",
            r"使用方法",
            r"帮助",
            r"help",
            r"产品介绍",
            r"系统说明",
            r"架构说明",
            r"和\s*chatgpt\s*有什么区别",
            r"与\s*chatgpt\s*有什么区别",
            r"chatgpt.*区别",
            r"数据来源",
            r"来源是什么",
            r"数据从哪里来",
            r"数据库没有数据怎么办",
            r"没有数据怎么办",
            r"没数据怎么办",
            r"faithmate",
            r"christian intelligence os",
            r"\bcio\b",
        ]
        return any(re.search(pattern, msg, re.IGNORECASE) for pattern in patterns)

    def _assistant_greeting(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "Christian Intelligence Operating System（CIO）是一套面向研究、分析与决策支持的企业级基督教情报分析平台。\n"
                "系统专注于整合全球公开数据、机构资料、人物信息、媒体动态及关系网络，帮助用户快速获取可追溯、可验证、可分析的情报。\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。\n\n"
                "推荐查询\n"
                "• 查询 Victory Philippines 的评分\n"
                "• 查询 Every Nation\n"
                "• 查询 Billy Graham\n"
                "• 查询菲律宾基督教媒体\n"
                "• 查询韩国基督教情况\n"
                "• 查询 OpenAI 和 Microsoft 的关系\n"
                "• 查询 Compassion International 的资金来源"
            )
        return (
            "Christian Intelligence Operating System (CIO)\n"
            "Enterprise Christian Intelligence Platform\n\n"
            "Christian Intelligence Operating System (CIO) is an enterprise Christian intelligence platform for research, "
            "analysis, and decision support.\n"
            "It integrates public data, organization profiles, people records, media activity, and relationship networks.\n"
            "Answers are based on the database and public sources first. It does not invent data that does not exist."
        )

    def _assistant_identity_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "Christian Intelligence Operating System（CIO）是一套面向研究、分析与决策支持的企业级基督教情报分析平台。\n"
                "系统专注于整合全球公开数据、机构资料、人物信息、媒体动态及关系网络，帮助用户快速获取可追溯、可验证、可分析的情报。\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。\n\n"
                "核心能力\n"
                "① 数据查询\n"
                "- 机构\n- 人物\n- 媒体\n- 国家\n- 基金会\n- 教会\n- 宣教组织\n- 教育机构\n\n"
                "② 情报分析\n"
                "- 机构评分\n- 数字影响力分析\n- 关系网络分析\n- 投资与资助关系\n- 公开情报分析\n- 趋势分析\n\n"
                "③ 数据验证\n"
                "- 来源\n- URL\n- 证据\n- 可信度\n\n"
                "④ 数据覆盖\n"
                "- 全球机构\n- 全球媒体\n- 公开新闻\n- 公开数据库\n\n"
                "系统原则\n"
                "① 数据优先（Database First）\n"
                "② 来源可追溯（Traceable）\n"
                "③ 不编造（No Hallucination）\n"
                "④ 可分析（Analysis）"
            )
        return (
            "Christian Intelligence Operating System (CIO)\n"
            "Enterprise Christian Intelligence Platform\n\n"
            "Christian Intelligence Operating System (CIO) is an enterprise Christian intelligence platform for research, analysis, and decision support.\n"
            "It integrates global public data, organization profiles, people records, media activity, and relationship networks.\n"
            "Answers are based on the database and public sources first. It does not invent data that does not exist."
        )

    def _assistant_how_to_use_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "如何使用\n\n"
                "【机构】\n"
                "- 查询 Victory Philippines\n"
                "- 查询 Every Nation\n"
                "- 查询 Hillsong\n\n"
                "【人物】\n"
                "- 查询 Billy Graham\n"
                "- 查询 Steve Murrell\n\n"
                "【评分】\n"
                "- 查询 Victory Philippines 的评分\n"
                "- 查询机构数字影响力\n\n"
                "【关系】\n"
                "- 查询 OpenAI 与 Microsoft 的关系\n"
                "- 查询 Every Nation 的关联机构\n\n"
                "【媒体】\n"
                "- 查询菲律宾基督教媒体\n"
                "- 查询美国福音媒体\n\n"
                "【新闻】\n"
                "- 查询菲律宾最新基督教新闻\n"
                "- 查询某机构最新动态\n\n"
                "【公开情报】\n"
                "- 查询带来源情报\n"
                "- 查询公开证据\n\n"
                "系统会：\n"
                "- 优先查询数据库\n"
                "- 展示评分\n"
                "- 展示来源\n"
                "- 展示URL\n"
                "- 数据库没有的数据会明确说明，而不会编造\n\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "You can query in natural language, for example:\n\n"
            "Organization queries\n"
            "- Query Victory Philippines\n"
            "- Query Hillsong\n"
            "- Query Every Nation\n\n"
            "Score queries\n"
            "- Query the score of Victory Philippines\n"
            "- Query digital influence scores\n\n"
            "People queries\n"
            "- Query Steve Murrell\n"
            "- Query Billy Graham\n\n"
            "Relationship analysis\n"
            "- Compare the relationship between OpenAI and Microsoft\n"
            "- Query organization relationship networks\n\n"
            "Media queries\n"
            "- Query Christian media in the Philippines\n"
            "- Query evangelical media in the United States\n\n"
            "News queries\n"
            "- Query the latest Christian news in the Philippines\n\n"
            "Country queries\n"
            "- Query Christianity in South Korea\n"
            "- Query the religious overview of the Philippines\n\n"
            "Public intelligence\n"
            "- Query intelligence with sources\n"
            "- Query public evidence\n\n"
            "The system will:\n"
            "Prioritize the database;\n"
            "Show scores;\n"
            "Show sources;\n"
            "Show URLs;\n"
            "State clearly when data is missing instead of inventing it."
        )

    def _assistant_about_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "Christian Intelligence Operating System（CIO）是一套面向研究、分析与决策支持的企业级基督教情报分析平台。\n"
                "系统专注于整合全球公开数据、机构资料、人物信息、媒体动态及关系网络，帮助用户快速获取可追溯、可验证、可分析的情报。\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "Christian Intelligence Operating System (CIO) is a Christian intelligence analysis platform for research, "
            "analysis, and decision support.\n\n"
            "Core capabilities include:\n"
            "• Organization database\n"
            "• People database\n"
            "• Scoring system\n"
            "• Relationship analysis\n"
            "• Public intelligence\n"
            "• Source tracking\n"
            "• Media monitoring\n"
            "• Data analysis\n\n"
            "Answers are based on the database and public sources first. I do not invent data that does not exist."
        )

    def _assistant_capabilities_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "核心能力\n"
                "① 数据查询\n"
                "- 机构\n- 人物\n- 媒体\n- 国家\n- 基金会\n- 教会\n- 宣教组织\n- 教育机构\n\n"
                "② 情报分析\n"
                "- 机构评分\n- 数字影响力分析\n- 关系网络分析\n- 投资与资助关系\n- 公开情报分析\n- 趋势分析\n\n"
                "③ 数据验证\n"
                "- 来源\n- URL\n- 证据\n- 可信度\n\n"
                "④ 数据覆盖\n"
                "- 全球机构\n- 全球媒体\n- 公开新闻\n- 公开数据库\n\n"
                "系统原则\n"
                "① 数据优先（Database First）\n"
                "② 来源可追溯（Traceable）\n"
                "③ 不编造（No Hallucination）\n"
                "④ 可分析（Analysis）\n\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "I am the Christian Intelligence Operating System (CIO) intelligence assistant. "
            "I can help you with:\n"
            "1) Querying Christian organization profiles.\n"
            "2) Querying organization scores, including People Score, Digital Score, Intel Score, and Composite Score.\n"
            "3) Querying people records and organizational relationships.\n"
            "4) Querying investment and funding relationships.\n"
            "5) Querying media organizations, country religion data, public news, and public intelligence.\n"
            "6) Showing sources and URLs.\n"
            "7) Analyzing and summarizing information already in the database.\n\n"
            "Answers are based on the database and public sources first. I do not invent data that does not exist."
        )

    def _assistant_system_vs_chatgpt_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "和 ChatGPT 的区别\n"
                "- CIO 聚焦基督教机构、人物、媒体、国家、基金会、教会、宣教组织与教育机构的数据查询与情报分析。\n"
                "- CIO 优先基于数据库与公开来源，强调来源、URL、证据与可追溯性。\n"
                "- CIO 输出机构评分、关系网络、投资与资助关系、公开情报分析与趋势分析。\n"
                "- ChatGPT 是通用对话模型；CIO 是面向研究、分析与决策支持的垂直情报平台。\n\n"
                "系统原则\n"
                "① 数据优先（Database First）\n"
                "② 来源可追溯（Traceable）\n"
                "③ 不编造（No Hallucination）\n"
                "④ 可分析（Analysis）\n\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "Christian Intelligence Operating System (CIO) is an Enterprise Christian Intelligence Platform.\n"
            "Compared with ChatGPT, CIO is specialized for Christian intelligence research, source-traceable evidence, "
            "database-first retrieval, and relationship analysis."
        )

    def _assistant_data_sources_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "数据来源\n"
                "- 数据库\n"
                "- 公开来源\n"
                "- 机构资料\n"
                "- 人物信息\n"
                "- 媒体动态\n"
                "- 公开新闻\n"
                "- 公开数据库\n"
                "- 可追溯 URL 与证据\n\n"
                "系统原则\n"
                "① 数据优先（Database First）\n"
                "② 来源可追溯（Traceable）\n"
                "③ 不编造（No Hallucination）\n"
                "④ 可分析（Analysis）\n\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "Christian Intelligence Operating System (CIO) uses database records and public sources, including organization "
            "profiles, people records, media activity, public news, public databases, and traceable URLs."
        )

    def _assistant_no_data_text(self, lang: str) -> str:
        if lang == "zh":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "如果数据库没有数据\n"
                "- 明确说明数据库没有相关数据\n"
                "- 不编造不存在的数据\n"
                "- 若有公开来源证据，优先展示来源与 URL\n"
                "- 若当前仍无可验证信息，直接说明数据缺口\n"
                "- 在已有数据范围内提供分析与边界说明\n\n"
                "系统原则\n"
                "① 数据优先（Database First）\n"
                "② 来源可追溯（Traceable）\n"
                "③ 不编造（No Hallucination）\n"
                "④ 可分析（Analysis）\n\n"
                "回答优先基于数据库与公开来源，不编造不存在的数据。"
            )
        return (
            "If the database does not contain the requested data, CIO states that clearly, does not invent missing facts, "
            "and only shows traceable public evidence when available."
        )

    def _handle_assistant_intro_query(self, msg: str, conversation_id: Optional[str] = None) -> Dict:
        lang = self._lang or _CONVERSATION_LANG_PREF.get(conversation_id or "", "en")
        lowered = (msg or "").lower()
        if any(token in lowered for token in ["如何使用", "怎么使用", "使用方法", "how to use"]):
            response = self._assistant_how_to_use_text(lang)
        elif "chatgpt" in lowered:
            response = self._assistant_system_vs_chatgpt_text(lang)
        elif any(token in lowered for token in ["数据来源", "来源是什么", "数据从哪里来", "data source", "sources"]):
            response = self._assistant_data_sources_text(lang)
        elif any(token in lowered for token in ["数据库没有数据怎么办", "没有数据怎么办", "没数据怎么办", "no data", "if the database does not contain"]):
            response = self._assistant_no_data_text(lang)
        elif any(token in lowered for token in ["about", "产品介绍", "系统说明", "架构说明"]):
            response = self._assistant_about_text(lang)
        elif self._is_capabilities_query(msg):
            response = self._assistant_capabilities_text(lang)
        else:
            response = self._assistant_identity_text(lang)

        evidence = [
            {
                "title": "CIO assistant identity",
                "source_name": "system",
                "url": "",
                "confidence": 1.0,
                "published_at": "",
                "updated_at": "",
                "type": "system_capability",
                "snippet": "Christian Intelligence Operating System (CIO) identity, scope, how-to-use, and capability template.",
            }
        ]
        return {
            "data_found": True,
            "response": response,
            "answer": response,
            "evidence": evidence,
            "direct_answer": True,
        }

    def _handle_capabilities_query(self, msg: str, conversation_id: Optional[str] = None) -> Dict:
        lang = self._lang or _CONVERSATION_LANG_PREF.get(conversation_id or "", "en")
        response = self._assistant_capabilities_text(lang)

        evidence = [
            {
                "title": "Dialog capability list (rule-based)",
                "source_name": "system",
                "url": "",
                "confidence": 1.0,
                "published_at": "",
                "updated_at": "",
                "type": "system_capability",
                "snippet": "QueryParser direct-answer capabilities: score/compare/investment/timeline/contact/profile/existence.",
            }
        ]

        return {
            "data_found": True,
            "answer": response,
            "evidence": evidence,
            "direct_answer": True,
        }

    def _is_org_profile_query(self, msg: str) -> bool:
        lowered = (msg or "").lower()
        if any(re.search(kw, msg, re.IGNORECASE) for kw in self.SCORE_KEYWORDS):
            return False
        if any(re.search(kw, msg, re.IGNORECASE) for kw in self.COMPARE_KEYWORDS):
            return False
        if any(re.search(kw, msg, re.IGNORECASE) for kw in self.INVESTMENT_KEYWORDS):
            return False
        if any(re.search(kw, msg, re.IGNORECASE) for kw in self.CONTACT_KEYWORDS):
            return False
        return any(re.search(kw, msg, re.IGNORECASE) for kw in self.PROFILE_KEYWORDS) and len(lowered) >= 4

    def _coerce_datetime_str(self, value) -> str:
        if not value:
            return ""
        try:
            return value.isoformat()
        except Exception:
            return ""

    def _pick_org_evidence_url(self, org: OrganizationProfile) -> str:
        return (
            (org.source_url or "").strip()
            or (org.official_website or "").strip()
            or (org.wikipedia_url or "").strip()
            or (org.leader_bio_url or "").strip()
        )

    def _evidence_from_org(self, org: OrganizationProfile, *, evidence_type: str) -> dict:
        snippet = (org.description or org.about_text or org.mission_statement or "").strip()
        return {
            "title": (org.name or "").strip(),
            "source_name": (org.source_name or "").strip(),
            "url": self._pick_org_evidence_url(org),
            "confidence": float(org.confidence or 0.0),
            "published_at": "",
            "updated_at": self._coerce_datetime_str(getattr(org, "updated_at", None)),
            "type": evidence_type,
            "snippet": snippet[:240] if snippet else "",
        }

    def _evidence_from_item(self, item: IntelligenceItem, *, evidence_type: str) -> dict:
        return {
            "title": (item.title or "").strip(),
            "source_name": (item.source_name or "").strip(),
            "url": (item.source_url or "").strip(),
            "confidence": float(item.confidence or 0.0),
            "published_at": self._coerce_datetime_str(getattr(item, "published_at", None)),
            "updated_at": self._coerce_datetime_str(getattr(item, "ingested_at", None)),
            "type": evidence_type,
            "snippet": ((item.content or "").strip()[:240]) if item.content else "",
        }

    def _evidence_from_relation(self, rel: RelationEdge, *, title: str, snippet: str) -> dict:
        return {
            "title": title,
            "source_name": (rel.evidence_source or "").strip(),
            "url": (rel.evidence_url or "").strip(),
            "confidence": float(rel.confidence or 0.0),
            "published_at": self._coerce_datetime_str(getattr(rel, "evidence_date", None)),
            "updated_at": self._coerce_datetime_str(getattr(rel, "updated_at", None)),
            "type": "relation_edge",
            "snippet": (snippet or "").strip()[:240],
        }

    def _detect_language_command(self, msg: str) -> Optional[str]:
        lowered = (msg or "").lower()
        if any(token in msg for token in ["用中文回答", "请用中文", "中文回答", "用中文回复"]):
            return "zh"
        if any(token in lowered for token in ["answer in chinese", "reply in chinese", "respond in chinese"]):
            return "zh"
        if any(token in msg for token in ["用英文回答", "请用英文", "英文回答", "用英文回复"]):
            return "en"
        if any(token in lowered for token in ["answer in english", "reply in english", "respond in english"]):
            return "en"
        return None

    def _get_lang_pref(self, conversation_id: Optional[str]) -> Optional[str]:
        if not conversation_id:
            return self._lang
        return _CONVERSATION_LANG_PREF.get(conversation_id) or self._lang

    def _extract_org_name(self, msg: str) -> Optional[str]:
        raw = (msg or "").strip()
        score_of = re.search(r"(?:people|digital|intel|composite)?\s*score\s+of\s+(.+?)(?:\?|$)", raw, flags=re.IGNORECASE)
        if score_of:
            candidate = (score_of.group(1) or "").strip()
            if candidate:
                return candidate

        zh_score = re.search(r"(.+?)(?:的)?(?:评分|分数)(?:是多少|多少|为多少)?", raw)
        if zh_score:
            candidate = (zh_score.group(1) or "").strip()
            if candidate and len(candidate) > 1:
                return candidate

        clean = raw
        replacements = [
            "what is the",
            "what is",
            "show me",
            "tell me",
            "查一下",
            "查询",
            "的评分",
            "的分数",
            "的 score",
            "的综合评分",
            "是多少",
            "?",
            "？",
        ]
        for token in replacements:
            clean = re.sub(re.escape(token), "", clean, flags=re.IGNORECASE).strip()

        clean = re.sub(r"^(of|for)\s+", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"\b(score|scores|composite|people|digital|intel)\b", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"\b(compare|vs|versus|and)\b", " ", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"\s+", " ", clean).strip()

        if len(clean) > 2:
            return clean
        return None

    def _find_organization(self, name: str) -> List[OrganizationProfile]:
        if not name:
            return []

        return (
            self.db.query(OrganizationProfile)
            .filter(
                or_(
                    OrganizationProfile.name.ilike(f"%{name}%"),
                    OrganizationProfile.english_name.ilike(f"%{name}%"),
                    OrganizationProfile.short_name.ilike(f"%{name}%"),
                    OrganizationProfile.official_name.ilike(f"%{name}%"),
                )
            )
            .limit(5)
            .all()
        )

    def _handle_score_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        _ = conversation_id
        return self._build_score_lookup_intent(msg)

    def _clean_relationship_graph_org_candidate(self, candidate: str) -> Optional[str]:
        clean = (candidate or "").strip()
        if not clean:
            return None
        clean = re.sub(
            r"^(?:show\s+me|show|what\s+organizations\s+is|what\s+are|who\s+are|explain|tell\s+me|give\s+me|说明|给我|查一下|查查|帮我|请|请给我)\s+",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(
            r"(?:的)?(?:relationship\s+graph|relationship\s+network|network|partners?|related\s+organizations?|graph|关系图谱|关系网络|合作网络|合作方|关联机构|关系边|有哪些合作方|和哪些机构有关联|有哪些关联机构|是什么)$",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean = re.sub(r"(?:\?|？|。|！|!)+$", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean).strip(" \"'`")
        if len(clean) <= 1:
            return None
        return clean

    def _extract_relationship_graph_org_name(self, msg: str) -> Optional[str]:
        raw = str(msg or "").strip()
        patterns = [
            r"show\s+me\s+the\s+relationship\s+graph\s+of\s+(.+?)(?:\?|？|$)",
            r"explain\s+the\s+relationship\s+network\s+of\s+(.+?)(?:\?|？|$)",
            r"what\s+organizations\s+is\s+(.+?)\s+connected\s+to(?:\?|？|$)",
            r"who\s+are\s+(.+?)\s+partners(?:\?|？|$)",
            r"what\s+are\s+the\s+related\s+organizations\s+of\s+(.+?)(?:\?|？|$)",
            r"show\s+(.+?)\s+network(?:\?|？|$)",
            r"(.+?)\s+的关系图谱是什么(?:\?|？|$)",
            r"说明\s+(.+?)\s+的关系图谱(?:\?|？|$)",
            r"说明\s+(.+?)\s+的关系网络(?:\?|？|$)",
            r"(.+?)\s+和哪些机构有关联(?:\?|？|$)",
            r"(.+?)\s+有哪些合作方(?:\?|？|$)",
            r"(.+?)\s+的关联机构有哪些(?:\?|？|$)",
            r"给我\s+(.+?)\s+的关系图谱(?:\?|？|$)",
            r"查一下\s+(.+?)\s+的合作网络(?:\?|？|$)",
            r"(.+?)\s+的关系边有哪些(?:\?|？|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            candidate = self._clean_relationship_graph_org_candidate(match.group(1) or "")
            if candidate:
                return candidate
        return None

    def _build_relationship_graph_intent(self, msg: str) -> Optional[Dict]:
        if not self._is_relationship_graph_query(msg):
            return None
        organization_name = self._extract_relationship_graph_org_name(msg)
        if not organization_name:
            return None
        return {
            "data_found": False,
            "direct_answer": False,
            "intent": self.RELATIONSHIP_GRAPH_INTENT_NAME,
            "organization_name": organization_name,
            "response_contract": self.RELATIONSHIP_GRAPH_RESPONSE_CONTRACT,
            "depth": 1,
            "include_unverified": False,
            "requires_database_lookup": True,
        }

    def _handle_relationship_graph_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        _ = conversation_id
        return self._build_relationship_graph_intent(msg)

    def _handle_compare_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        """处理对比查询"""
        raw = (msg or "").strip()
        msg_lower = raw.lower()

        if "pcec" in msg_lower and "sbc" in msg_lower:
            org1_list = self._find_organization("PCEC")
            org2_list = self._find_organization("SBC")
            if org1_list and org2_list:
                org1, org2 = org1_list[0], org2_list[0]
                c1 = (org1.people_score or 0) + (org1.digital_score or 0) + (org1.intel_score or 0)
                c2 = (org2.people_score or 0) + (org2.digital_score or 0) + (org2.intel_score or 0)
                if self._get_lang_pref(conversation_id) == "zh":
                    response = (
                        f"**{org1.name}** ({org1.country or 'N/A'})\n"
                        f"- 人员评分: {org1.people_score or 0} | 数字评分: {org1.digital_score or 0} | 情报评分: {org1.intel_score or 0} | **综合评分: {c1}**\n\n"
                        f"**{org2.name}** ({org2.country or 'N/A'})\n"
                        f"- 人员评分: {org2.people_score or 0} | 数字评分: {org2.digital_score or 0} | 情报评分: {org2.intel_score or 0} | **综合评分: {c2}**\n"
                    )
                else:
                    response = (
                        f"**{org1.name}** ({org1.country or 'N/A'})\n"
                        f"- People: {org1.people_score or 0} | Digital: {org1.digital_score or 0} | Intel: {org1.intel_score or 0} | **Composite: {c1}**\n\n"
                        f"**{org2.name}** ({org2.country or 'N/A'})\n"
                        f"- People: {org2.people_score or 0} | Digital: {org2.digital_score or 0} | Intel: {org2.intel_score or 0} | **Composite: {c2}**\n"
                    )
                evidence = [
                    self._evidence_from_org(org1, evidence_type="organization_compare"),
                    self._evidence_from_org(org2, evidence_type="organization_compare"),
                ]
                return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

        def clean_org_token(token: str) -> str:
            t = (token or "").strip()
            t = t.strip(" ?？.!。;；,:，\"'`")
            t = re.sub(r"\b(compare|vs|versus|and)\b", " ", t, flags=re.IGNORECASE)
            t = re.sub(r"(谁的|谁|哪个|更高|更好|更强|评分|分数|得分)", " ", t)
            t = re.sub(r"\b(score|scores|composite|people|digital|intel)\b", " ", t, flags=re.IGNORECASE)
            t = re.sub(r"\s+", " ", t).strip()
            if t.upper() == "SBC":
                return "Southern Baptist Convention"
            if t.upper() == "PCEC":
                return "Philippine Council of Evangelical Churches"
            return t

        org_a = None
        org_b = None

        zh = re.search(r"(.+?)\s*(?:和|与)\s*(.+?)\s*(?:谁|哪个|对比|比较|评分|分数|得分|更高|更好|更强)", raw)
        if zh:
            org_a = clean_org_token(zh.group(1))
            org_b = clean_org_token(zh.group(2))
        else:
            en = re.search(r"(?:compare\s+)?(.+?)\s*(?:and|vs|versus|&)\s*(.+?)(?:\?|$)", raw, flags=re.IGNORECASE)
            if en:
                org_a = clean_org_token(en.group(1))
                org_b = clean_org_token(en.group(2))

        if not org_a or not org_b or len(org_a) < 2 or len(org_b) < 2:
            return None

        org1_list = self._find_organization(org_a)
        org2_list = self._find_organization(org_b)

        if not org1_list or not org2_list:
            return None

        org1, org2 = org1_list[0], org2_list[0]
        c1 = (org1.people_score or 0) + (org1.digital_score or 0) + (org1.intel_score or 0)
        c2 = (org2.people_score or 0) + (org2.digital_score or 0) + (org2.intel_score or 0)

        if self._get_lang_pref(conversation_id) == "zh":
            response = (
                f"**{org1.name}** ({org1.country or 'N/A'})\n"
                f"- 人员分: {org1.people_score or 0} | 数字分: {org1.digital_score or 0} | 情报分: {org1.intel_score or 0} | **综合分: {c1}**\n\n"
                f"**{org2.name}** ({org2.country or 'N/A'})\n"
                f"- 人员分: {org2.people_score or 0} | 数字分: {org2.digital_score or 0} | 情报分: {org2.intel_score or 0} | **综合分: {c2}**\n"
            )
        else:
            response = (
                f"**{org1.name}** ({org1.country or 'N/A'})\n"
                f"- People: {org1.people_score or 0} | Digital: {org1.digital_score or 0} | Intel: {org1.intel_score or 0} | **Composite: {c1}**\n\n"
                f"**{org2.name}** ({org2.country or 'N/A'})\n"
                f"- People: {org2.people_score or 0} | Digital: {org2.digital_score or 0} | Intel: {org2.intel_score or 0} | **Composite: {c2}**\n"
            )

        evidence = [
            self._evidence_from_org(org1, evidence_type="organization_compare"),
            self._evidence_from_org(org2, evidence_type="organization_compare"),
        ]
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

    def _handle_investment_out(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        match = re.search(r"(.+?)\s*(?:投资了谁|投资了哪些|invested in whom|的投资关系)", msg, re.IGNORECASE)
        if not match:
            return None

        org_name = match.group(1).strip()
        org_name = org_name.rstrip("？?").strip()

        orgs = self._find_organization(org_name)
        if not orgs:
            return None

        source_org = orgs[0]
        rels = (
            self.db.query(RelationEdge, OrganizationProfile)
            .join(OrganizationProfile, RelationEdge.target_id == OrganizationProfile.id)
            .filter(
                RelationEdge.source_id == source_org.id,
                RelationEdge.relation_type.in_(["invested_in", "co_invested", "partnered_with"]),
            )
            .all()
        )
        if not rels:
            response = f"{source_org.name} 当前没有记录的投资/合作关系。"
            evidence = [self._evidence_from_org(source_org, evidence_type="organization_investment_subject")]
            return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

        if self._get_lang_pref(conversation_id) == "zh":
            lines = [f"找到 {len(rels)} 条关系（{source_org.name}）：\n"]
        else:
            lines = [f"Found {len(rels)} relations for {source_org.name}:\n"]
        for r in rels:
            amount = (
                f"{r.RelationEdge.investment_currency or 'USD'} {r.RelationEdge.investment_amount or 'N/A'}"
                if r.RelationEdge.investment_amount
                else "Amount undisclosed"
            )
            verified = "✓ Verified" if r.RelationEdge.is_verified else "Unverified"
            if self._get_lang_pref(conversation_id) == "zh":
                verified = "✓ 已验证" if r.RelationEdge.is_verified else "未验证"
                amount_label = f"{amount}" if r.RelationEdge.investment_amount else "金额未披露"
                round_label = r.RelationEdge.investment_round or "N/A"
                lines.append(
                    f"- **{r.RelationEdge.relation_type.upper()}** → {r.OrganizationProfile.name} ({r.OrganizationProfile.country or 'N/A'})\n"
                    f"  金额: {amount_label} | 轮次: {round_label} | {verified}\n"
                )
                continue
            lines.append(
                f"- **{r.RelationEdge.relation_type.upper()}** → {r.OrganizationProfile.name} ({r.OrganizationProfile.country or 'N/A'})\n"
                f"  Amount: {amount} | Round: {r.RelationEdge.investment_round or 'N/A'} | {verified}\n"
            )
        evidence = [self._evidence_from_org(source_org, evidence_type="organization_investment_subject")]
        for r in rels[:20]:
            rel_obj = r.RelationEdge
            title = f"{source_org.name} -> {r.OrganizationProfile.name} ({rel_obj.relation_type})"
            snippet = f"{rel_obj.investment_currency or 'USD'} {rel_obj.investment_amount or ''} {rel_obj.investment_round or ''}".strip()
            evidence.append(self._evidence_from_relation(rel_obj, title=title, snippet=snippet))
        response = "\n".join(lines)
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

    def _handle_investment_in(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        patterns = [
            r"谁投资了\s*(.+?)(?:\s*[？?]|$)",
            r"who invested in\s*(.+?)(?:\s*[?]|$)",
            r"(.+?)的投资方",
        ]

        org_name = None
        for p in patterns:
            match = re.search(p, msg, re.IGNORECASE)
            if match:
                org_name = match.group(1).strip()
                break

        if not org_name:
            return None

        orgs = self._find_organization(org_name)
        if not orgs:
            return None

        target_org = orgs[0]
        rels = (
            self.db.query(RelationEdge, OrganizationProfile)
            .join(OrganizationProfile, RelationEdge.source_id == OrganizationProfile.id)
            .filter(
                RelationEdge.target_id == target_org.id,
                RelationEdge.relation_type.in_(["invested_in", "co_invested"]),
            )
            .all()
        )
        if not rels:
            response = f"当前没有记录的投资方投资了 {target_org.name}。"
            evidence = [self._evidence_from_org(target_org, evidence_type="organization_investment_subject")]
            return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

        if self._get_lang_pref(conversation_id) == "zh":
            lines = [f"{target_org.name} 的投资方：\n"]
        else:
            lines = [f"Investors in {target_org.name}:\n"]
        for r in rels:
            amount = (
                f"{r.RelationEdge.investment_currency or 'USD'} {r.RelationEdge.investment_amount or 'N/A'}"
                if r.RelationEdge.investment_amount
                else "Amount undisclosed"
            )
            verified = "✓ Verified" if r.RelationEdge.is_verified else "Unverified"
            if self._get_lang_pref(conversation_id) == "zh":
                verified = "✓ 已验证" if r.RelationEdge.is_verified else "未验证"
                amount_label = f"{amount}" if r.RelationEdge.investment_amount else "金额未披露"
                round_label = r.RelationEdge.investment_round or "N/A"
                lines.append(
                    f"- **{r.OrganizationProfile.name}** ({r.OrganizationProfile.country or 'N/A'})\n"
                    f"  {r.RelationEdge.relation_type.upper()} | 金额: {amount_label} | 轮次: {round_label} | {verified}\n"
                )
                continue
            lines.append(
                f"- **{r.OrganizationProfile.name}** ({r.OrganizationProfile.country or 'N/A'})\n"
                f"  {r.RelationEdge.relation_type.upper()} | Amount: {amount} | Round: {r.RelationEdge.investment_round or 'N/A'} | {verified}\n"
            )

        evidence = [self._evidence_from_org(target_org, evidence_type="organization_investment_subject")]
        for r in rels[:20]:
            rel_obj = r.RelationEdge
            title = f"{r.OrganizationProfile.name} -> {target_org.name} ({rel_obj.relation_type})"
            snippet = f"{rel_obj.investment_currency or 'USD'} {rel_obj.investment_amount or ''} {rel_obj.investment_round or ''}".strip()
            evidence.append(self._evidence_from_relation(rel_obj, title=title, snippet=snippet))
        response = "\n".join(lines)
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

    def _handle_existence_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        total = self.db.query(func.count(OrganizationProfile.id)).scalar() or 0
        people_covered = (
            self.db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.people_score > 0).scalar() or 0
        )
        digital_covered = (
            self.db.query(func.count(OrganizationProfile.id))
            .filter(OrganizationProfile.official_website.isnot(None))
            .scalar()
            or 0
        )
        intel_covered = (
            self.db.query(func.count(OrganizationProfile.id)).filter(OrganizationProfile.intel_score > 0).scalar() or 0
        )
        people_pct = (people_covered * 100 // total) if total else 0
        digital_pct = (digital_covered * 100 // total) if total else 0
        intel_pct = (intel_covered * 100 // total) if total else 0

        if self._get_lang_pref(conversation_id) == "zh":
            response = (
                "数据库覆盖率：\n"
                f"- 机构总数: {total}\n"
                f"- 有 People Score 的机构: {people_covered} ({people_pct}%)\n"
                f"- 有 Digital Score 线索（官网不为空）: {digital_covered} ({digital_pct}%)\n"
                f"- 有 Intel Score 的机构: {intel_covered} ({intel_pct}%)\n"
            )
        else:
            response = (
                "Database Coverage:\n"
                f"- Total organizations: {total}\n"
                f"- With People Score: {people_covered} ({people_pct}%)\n"
                f"- With Digital Score: {digital_covered} ({digital_pct}%)\n"
                f"- With Intel Score: {intel_covered} ({intel_pct}%)\n"
            )
        return {"data_found": True, "response": response, "answer": response, "evidence": [], "direct_answer": True}

    def _handle_intelligence_timeline(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        """处理情报时间线查询"""
        raw = (msg or "").strip()
        org_name = None

        patterns = [
            r"latest\s+\d+\s+intelligence\s+items\s+about\s+(.+?)(?:\?|$)",
            r"show\s+the\s+latest\s+\d+\s+intelligence\s+items\s+about\s+(.+?)(?:\?|$)",
            r"latest\s+intelligence\s+about\s+(.+?)(?:\?|$)",
            r"show\s+.*news\s+about\s+(.+?)(?:\?|$)",
            r"(.+?)\s+的最新情报",
            r"(.+?)\s+最近.*情报",
            r"(.+?)\s+最新.*动态",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                org_name = (match.group(1) or "").strip().rstrip("？?")
                break

        if not org_name:
            org_name = self._extract_org_name(raw)

        if not org_name:
            country_match = re.search(r"about\s+(.+?)(?:\s+in\s+\d+|\s*$)", raw, re.IGNORECASE)
            if country_match:
                org_name = (country_match.group(1) or "").strip().rstrip("？?")

        if not org_name:
            return None

        from sqlalchemy import desc
        from models.database import IntelligenceItem

        items = (
            self.db.query(IntelligenceItem)
            .filter(IntelligenceItem.entity_name == org_name)
            .order_by(desc(IntelligenceItem.ingested_at))
            .limit(10)
            .all()
        )

        if not items:
            items = (
                self.db.query(IntelligenceItem)
                .filter(IntelligenceItem.entity_name.ilike(f"%{org_name}%"))
                .order_by(desc(IntelligenceItem.ingested_at))
                .limit(10)
                .all()
            )

        if not items:
            if self._get_lang_pref(conversation_id) == "zh":
                return {
                    "data_found": True,
                    "response": f"数据库中未找到 {org_name} 的相关情报条目。",
                    "answer": f"数据库中未找到 {org_name} 的相关情报条目。",
                    "evidence": [],
                    "direct_answer": True,
                }
            return {
                "data_found": True,
                "response": f"No intelligence items found for {org_name}.",
                "answer": f"No intelligence items found for {org_name}.",
                "evidence": [],
                "direct_answer": True,
            }

        # 双重过滤：黑名单 + 标题相关性
        noise_keywords = ["Serena Williams", "tennis", "Wimbledon", "NBA", "football", "crypto", "bitcoin"]
        entity_keywords = org_name.lower().split()
        filtered = []
        for item in items:
            title = (item.title or "").lower()

            if any(keyword.lower() in title for keyword in noise_keywords):
                continue

            if not any(keyword in title for keyword in entity_keywords):
                continue

            filtered.append(item)

        display_items = filtered

        if not display_items:
            response = f"数据库中找到了 {len(items)} 条关于 {org_name} 的条目，但经相关性过滤后无可展示的有效情报。建议扩充数据源或调整查询条件。"
            evidence = [self._evidence_from_item(item, evidence_type="intelligence_timeline_candidate") for item in items[:10]]
            return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

        if self._get_lang_pref(conversation_id) == "zh":
            lines = [f"{org_name} 的最新情报：\n"]
        else:
            lines = [f"Latest intelligence about {org_name}:\n"]

        for item in display_items[:10]:
            date = item.ingested_at.strftime("%Y-%m-%d") if item.ingested_at else "N/A"
            lines.append(f"- {item.title or 'Untitled'} ({item.source_name or 'Unknown'}, {date})")

        evidence = [self._evidence_from_item(item, evidence_type="intelligence_timeline") for item in display_items[:10]]
        response = "\n".join(lines)
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

    def _handle_contact_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        org_name = self._extract_org_name(msg)
        if not org_name:
            return None
        orgs = self._find_organization(org_name)
        if not orgs:
            response = f'数据库中未找到 "{org_name}" 的相关机构。'
            return {"data_found": True, "response": response, "answer": response, "evidence": [], "direct_answer": True}
        org = orgs[0]
        if self._get_lang_pref(conversation_id) == "zh":
            response = (
                f"**{org.name}** ({org.country or 'N/A'})\n"
                f"- 官网: {org.official_website or '未知'}\n"
                f"- 邮箱: {org.contact_email or '未知'}\n"
                f"- 电话: {org.phone_public or '未知'}\n"
                f"- 负责人: {org.leader_name or '未知'} ({org.leader_title or '未知'})\n"
            )
        else:
            response = (
                f"**{org.name}** ({org.country or 'N/A'})\n"
                f"- Website: {org.official_website or 'Unknown'}\n"
                f"- Email: {org.contact_email or 'Unknown'}\n"
                f"- Phone: {org.phone_public or 'Unknown'}\n"
                f"- Leader: {org.leader_name or 'Unknown'} ({org.leader_title or 'Unknown'})\n"
            )
        evidence = [self._evidence_from_org(org, evidence_type="organization_contacts")]
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}

    def _handle_org_profile_query(self, msg: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
        org_name = self._extract_org_name(msg)
        if not org_name:
            return None
        orgs = self._find_organization(org_name)
        if not orgs:
            response = f'数据库中未找到 "{org_name}" 的相关机构。'
            return {"data_found": True, "response": response, "answer": response, "evidence": [], "direct_answer": True}
        org = orgs[0]
        desc = (org.description or org.about_text or "").strip()
        snippet = desc[:300] if desc else ""
        if self._get_lang_pref(conversation_id) == "zh":
            response = (
                f"**{org.name}** ({org.country or 'N/A'})\n"
                f"- 宗派/类型: {org.denomination or 'N/A'}\n"
                f"- 官网: {org.official_website or 'N/A'}\n"
                + (f"- 简介: {snippet}\n" if snippet else "")
            )
        else:
            response = (
                f"**{org.name}** ({org.country or 'N/A'})\n"
                f"- Denomination/Type: {org.denomination or 'N/A'}\n"
                f"- Website: {org.official_website or 'N/A'}\n"
                + (f"- Summary: {snippet}\n" if snippet else "")
            )
        evidence = [self._evidence_from_org(org, evidence_type="organization_profile")]
        return {"data_found": True, "response": response, "answer": response, "evidence": evidence, "direct_answer": True}
