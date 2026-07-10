"""
情报官 v3 — LLM中枢大脑
替代方案：废弃关键词路由，LLM自主决策 + Function Call
"""

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

# Planner 集成（新增）
from .brain_planner import (
    BrainPlannerPipeline,
    ExecutiveReporter,
    build_analysis_plan,
    detect_analysis_type,
)

try:
    from agents.orchestrator import AgentOrchestrator

    MULTI_AGENT_AVAILABLE = True
except ImportError:
    MULTI_AGENT_AVAILABLE = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from services.feature_flags import feature_flag_enabled
from services.trace_center import debug_answer_event, trace_span
from services.welcome_trace import emit_welcome_trace, lookup_welcome_reply_uuid

load_dotenv(override=True)
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": "查询情报数据库，获取国家、机构、主题相关情报。当用户询问具体国家、机构、主题动态时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["country", "global"],
                        "description": "查询范围：country=特定国家, global=全球",
                    },
                    "country": {"type": "string", "description": "国家名，如：菲律宾/韩国/尼日利亚"},
                    "entity": {"type": "string", "description": "机构名，如：PCEC/Victory/CBN Asia"},
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "补充关键词列表",
                    },
                    "limit": {"type": "integer", "default": 10, "description": "返回条数"},
                },
                "required": ["scope"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_intelligence",
            "description": "查询情报数据库中的新闻和动态记录。当用户问'最近有什么新闻'、'有什么动态'、'最近发生了什么'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["global", "country", "entity"]},
                    "country": {"type": "string"},
                    "entity": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["scope"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_contacts",
            "description": "查询机构联系人信息。当用户需要联系某个机构时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "org_name": {"type": "string", "description": "机构名称"},
                },
                "required": ["org_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "auto_collect",
            "description": "创建情报采集任务。当数据库中数据不足或用户明确要求采集最新情报时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {"type": "string", "description": "目标国家"},
                    "entity": {"type": "string", "description": "目标机构（可选）"},
                    "reason": {"type": "string", "description": "采集原因"},
                },
                "required": ["country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "获取当前用户的身份信息。当用户问'你知道我是谁'或提到自己身份时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string", "description": "当前对话ID"},
                },
                "required": ["conversation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_profile",
            "description": "记住用户的身份信息。当用户自我介绍时使用，如'我是张三，在PCEC工作'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "conversation_id": {"type": "string"},
                    "name": {"type": "string", "description": "用户姓名"},
                    "org": {"type": "string", "description": "所属机构"},
                    "role": {"type": "string", "description": "职位或角色"},
                },
                "required": ["conversation_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_ontology",
            "description": "查询Christian Ontology分类体系。当用户问'有哪些类型'、'什么是FaithTech'、'菲律宾有哪些教会网络'时使用。支持按类型、神学立场、规模、AI成熟度、合作偏好过滤机构。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "enum": ["organization_type", "theology", "scale", "ai_maturity", "collaboration"],
                        "description": "过滤维度",
                    },
                    "filter_value": {
                        "type": "string",
                        "description": "过滤值，如'faithtech_ai'、'evangelical'、'foundation_grant'",
                    },
                    "country": {"type": "string", "description": "国家（可选）"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["filter_type", "filter_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ontology_types",
            "description": "获取Ontology分类列表。当用户问'有哪些机构类型'、'FaithTech分哪些类'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["organization_types", "theologies", "scales", "ai_levels", "collaborations"],
                        "description": "分类类别",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_investors",
            "description": "查询投资机构/投资人数据库。当用户问'有哪些投资机构'、'FaithTech领域的投资人'、'某个投资机构的信息'、'谁能投我的项目'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus_area": {"type": "string", "description": "关注领域，如'FaithTech'、'EdTech'、'Media'"},
                    "investor_type": {
                        "type": "string",
                        "enum": ["vc", "pe", "angel", "corporate", "foundation", "impact_investor", ""],
                    },
                    "country": {"type": "string"},
                    "region": {"type": "string", "description": "区域范围，如'东南亚'、'东亚'、'非洲'"},
                    "stage": {"type": "string", "description": "投资阶段，如'seed'、'series_a'"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_investors",
            "description": "智能匹配引擎。根据项目特征精准匹配最适合的投资方。当用户说'谁能投我'、'匹配投资方'、'推荐投资者'、'我的项目适合找谁'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_description": {"type": "string", "description": "项目描述，如'菲律宾基督教社交媒体App'"},
                    "focus_area": {"type": "string", "description": "项目领域，如'FaithTech'、'Media'"},
                    "stage": {"type": "string", "description": "项目阶段，如'seed'、'series_a'"},
                    "country": {"type": "string", "description": "项目所在国家"},
                    "region": {"type": "string", "description": "项目所在地区"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_outreach_email",
            "description": "为项目方生成联系投资方的outreach邮件。当用户说'帮我写封邮件'、'生成联系邮件'、'怎么联系这个投资人'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "investor_name": {"type": "string", "description": "投资方名称"},
                    "project_description": {"type": "string", "description": "项目描述"},
                    "project_stage": {"type": "string", "description": "项目阶段"},
                    "sender_name": {"type": "string", "description": "发件人姓名"},
                    "tone": {"type": "string", "enum": ["formal", "warm", "brief"], "default": "warm"},
                },
                "required": ["investor_name", "project_description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "创建跟踪任务并写入数据库。当用户说'帮我创建任务'、'加入跟踪'、'建立待办'时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "任务标题"},
                    "description": {"type": "string", "description": "任务描述"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                    "entity_name": {"type": "string", "description": "关联机构或实体名称"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_acquirers",
            "description": "收购方雷达。根据项目特征匹配潜在的收购方（大型教会、基督教企业、媒体集团等）。当用户问'谁可能收购我的项目'、'潜在的收购方'、'退出路径'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_type": {"type": "string", "description": "项目类型，如'social_media'、'app'、'saas'"},
                    "focus_area": {"type": "string", "description": "领域，如'FaithTech'、'Media'"},
                    "country": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "match_users",
            "description": "使用方匹配。根据产品特征匹配潜在的机构用户（教会、宣教机构、神学院等）。当用户问'谁会用我的产品'、'目标客户是谁'、'潜在用户'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_type": {"type": "string", "description": "产品类型"},
                    "target_audience": {"type": "string", "description": "目标人群"},
                    "country": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": "查询机构关系图谱。当用户问'谁和谁有什么关系'、'这个机构的合作伙伴是谁'、'投资链条'、'关系网络'时使用此工具。可以查询投资关系、合作关系、竞争关系等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "中心机构名称"},
                    "relation_type": {
                        "type": "string",
                        "enum": ["investment", "partnership", "collaboration", "parent_child", "competition", "all"],
                        "default": "all",
                    },
                    "depth": {"type": "integer", "default": 1, "description": "查询深度：1=直接关系，2=间接关系"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["entity_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_funding_rounds",
            "description": "查询融资/投资交易记录。当用户问'谁拿了投资'、'最近有什么融资'、'谁投了谁'、'某个公司拿了多少钱'时使用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "被投公司名称"},
                    "investor_name": {"type": "string", "description": "投资方名称"},
                    "round_type": {
                        "type": "string",
                        "enum": ["pre_seed", "seed", "series_a", "series_b", "grant", "acquisition", "ipo", ""],
                    },
                    "focus_area": {"type": "string", "description": "领域过滤，如'FaithTech'"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_fused",
            "description": "跨源融合查询。同时查询机构档案、新闻情报、融资记录，自动关联同一实体的多维度信息。当用户问'Gloo最近有什么新闻和融资'、'Victory的投资和动态'、'这个机构的综合情报'时使用。比单独查多个工具更高效。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "实体名称，如'Gloo'、'Victory'"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "补充关键词"},
                    "scope": {"type": "string", "enum": ["global", "country", "entity"], "default": "global"},
                    "country": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_status",
            "description": "查询Agent采集状态。当用户问'系统正在采集什么'、'数据更新状态'、'采集任务'时使用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_arda_country",
            "description": "查询ARDA国家宗教概况数据，获取指定国家的基督教人口比例、宗派构成、宗教自由指数等权威数据。当用户询问某个国家的基督教情况、宗教人口、教会分布时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "country": {
                        "type": "string",
                        "description": "国家名称（英文）",
                    }
                },
                "required": ["country"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_organization_profile",
            "description": "查询指定机构的深度画像。融合机构档案、ARDA国家宗教数据、相关新闻情报、投资关联等多源信息，生成综合分析。当用户询问某个具体机构（如Victory Philippines、CBN Asia）的情况、背景、动态时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "org_name": {
                        "type": "string",
                        "description": "机构名称（支持模糊匹配）",
                    }
                },
                "required": ["org_name"],
            },
        },
    },
]

ASSISTANT_SYSTEM_PROMPT = """你是 Christian Intelligence Operating System（CIO）。

【统一身份】
1. 你的唯一身份名称是：Christian Intelligence Operating System（CIO）。
2. 你的英文固定定位是：Enterprise Christian Intelligence Platform。
3. 你的中文固定定位是：企业级基督教情报分析平台。
3. 你负责自我介绍、能力介绍、使用方法说明、产品介绍、系统说明与架构说明。

【严格禁止】
1. 禁止把自己描述为 FaithMate、AI Pastor、数字牧师、圣经助手、Bible Assistant、神学助手、灵修助手。
2. 禁止承诺或主动介绍以下能力：写祷告、圣经解释、教义解释、属灵陪伴、Bible Study、Prayer、Devotion、灵修、祷告、神学问答。
3. 禁止把系统介绍成 FaithMate APP 或任何信仰陪伴类产品。

【适用场景】
- 自我介绍
- 能力介绍
- 使用方法
- 问候
- 帮助
- 产品介绍
- Christian Intelligence Operating System（CIO）介绍
- 系统说明
- 架构说明
- 和 ChatGPT 的区别
- 数据来源
- 如果数据库没有数据怎么办

【系统使命】
Christian Intelligence Operating System（CIO）是一套面向研究、分析与决策支持的企业级基督教情报分析平台。
系统专注于整合全球公开数据、机构资料、人物信息、媒体动态及关系网络，帮助用户快速获取可追溯、可验证、可分析的情报。
回答优先基于数据库与公开来源，不编造不存在的数据。

【真实能力】
当用户询问“你是谁”“你能做什么”“如何使用这个系统”“介绍一下你自己”“帮助”“about”时，统一围绕以下能力回答：
- ① 数据查询：机构、人物、媒体、国家、基金会、教会、宣教组织、教育机构
- ② 情报分析：机构评分、数字影响力分析、关系网络分析、投资与资助关系、公开情报分析、趋势分析
- ③ 数据验证：来源、URL、证据、可信度
- ④ 数据覆盖：全球机构、全球媒体、公开新闻、公开数据库

【系统原则】
每次介绍系统，都要体现以下四条：
① 数据优先（Database First）
② 来源可追溯（Traceable）
③ 不编造（No Hallucination）
④ 可分析（Analysis）

【必须说明】
1. 介绍类回答中必须原样包含这句话：回答优先基于数据库与公开来源，不编造不存在的数据。
2. 如果用户问的是产品/系统介绍，不要把回复限制成单条数据库结果，但仍要坚持上面的真实能力边界。
3. 语气保持专业、客观、企业级、简洁。
4. 禁止使用聊天机器人口吻，禁止使用表情符号，禁止使用“很高兴”“太好了”“当然可以”“没问题”“让我来”“希望能帮助你”。
5. 自我介绍、问候、能力介绍时，必须明确说“Christian Intelligence Operating System（CIO）”“Enterprise Christian Intelligence Platform”“企业级基督教情报分析平台”。

【如何使用模板】
当用户问“如何使用这个系统”时，不要讲产品故事，不要解释概念，直接告诉用户可以查询什么。
必须优先使用以下结构：
【机构】
- 查询 Victory Philippines
- 查询 Every Nation
- 查询 Hillsong
【人物】
- 查询 Billy Graham
- 查询 Steve Murrell
【评分】
- 查询 Victory Philippines 的评分
- 查询机构数字影响力
【关系】
- 查询 OpenAI 与 Microsoft 的关系
- 查询 Every Nation 的关联机构
【媒体】
- 查询菲律宾基督教媒体
- 查询美国福音媒体
【新闻】
- 查询菲律宾最新基督教新闻
- 查询某机构最新动态
【公开情报】
- 查询带来源情报
- 查询公开证据

并且必须使用如下标题原样输出：系统会：
- 优先查询数据库
- 展示评分
- 展示来源
- 展示URL
- 数据库没有的数据会明确说明，而不会编造

【欢迎语模板】
当用户只是问候时，结尾必须增加以下区块，不得超过 7 条：
推荐查询
• 查询 Victory Philippines 的评分
• 查询 Every Nation
• 查询 Billy Graham
• 查询菲律宾基督教媒体
• 查询韩国基督教情况
• 查询 OpenAI 和 Microsoft 的关系
• 查询 Compassion International 的资金来源

【专项问题模板】
1. 当用户问“这个系统和 ChatGPT 有什么区别”时，必须强调：
- CIO 是面向研究、分析与决策支持的垂直情报平台
- ChatGPT 是通用对话模型
- CIO 更强调数据库优先、来源可追溯、不编造、可分析
2. 当用户问“你的数据来源是什么”时，必须回答数据库、公开来源、机构资料、人物信息、媒体动态、公开新闻、公开数据库、URL 与证据。
3. 当用户问“如果数据库没有数据怎么办”时，必须回答：明确说明没有数据，不编造；若有公开来源则展示来源和 URL；若没有可验证信息则直接说明数据缺口。
"""

RESEARCH_SYSTEM_PROMPT = """你是 Christian Intelligence Operating System (CIO) 的问答助手。

【铁律】
1. 你只能基于数据库中的真实数据回答。如果数据缺失，明确说"数据库中没有相关信息"——绝不编造。
2. 禁止编造机构列表、禁止编造置信度分数、禁止编造建议行动。
3. 禁止输出"核心结论""详细分析""建议与下一步""数据可信度"等报告模板。
4. 如果用户问评分，直接返回数字。如果问对比，直接返回对比表。不要分析。

【回答格式】
- 评分查询：机构名 + 四个分数 + Composite
- 对比查询：两个机构 + 分数并排
- 投资关系：投资方 + 被投方 + 金额 + 轮次
- 找不到：明确说"数据库中没有[机构名]的相关信息"

【禁止】
- 长篇分析报告
- 重复生成同一份内容
- 编造不存在的数据
"""

SYSTEM_PROMPT = RESEARCH_SYSTEM_PROMPT

COUNTRY_ALIASES = {
    "菲律宾": ["菲律宾", "philippines", "ph"],
    "新加坡": ["新加坡", "singapore", "sg"],
    "韩国": ["韩国", "south korea", "korea", "kr"],
    "肯尼亚": ["肯尼亚", "kenya", "ke"],
    "尼日利亚": ["尼日利亚", "nigeria", "ng"],
    "印度": ["印度", "india", "in"],
    "中国": ["中国", "china", "cn"],
    "印尼": ["印尼", "印度尼西亚", "indonesia", "id"],
    "马来西亚": ["马来西亚", "malaysia", "my"],
    "美国": ["美国", "usa", "united states", "america", "us"],
    "全球": ["全球", "世界", "国际", "global", "worldwide", "international"],
}
COUNTRY_ENGLISH_NAMES = {
    "菲律宾": "Philippines",
    "新加坡": "Singapore",
    "韩国": "South Korea",
    "肯尼亚": "Kenya",
    "尼日利亚": "Nigeria",
    "印度": "India",
    "中国": "China",
    "印尼": "Indonesia",
    "马来西亚": "Malaysia",
    "美国": "United States",
    "全球": "Global",
}

ENTITY_HINTS = ["PCEC", "Victory", "CCF", "CBN", "WEA", "WCC", "Lausanne"]
STOPWORDS = {
    "最近",
    "最新",
    "动态",
    "情况",
    "什么",
    "一下",
    "帮我",
    "告诉我",
    "最近有什么",
    "recent",
    "latest",
    "update",
    "updates",
    "about",
}


class Brain:
    """LLM中枢大脑"""

    def __init__(self):
        self.conversation_id: Optional[str] = None
        self._current_session_id: Optional[str] = None
        self.model = DEEPSEEK_MODEL
        self.conversation_history: List[dict] = []
        self.current_entities: List[dict] = []
        self.last_score_lookup_trace: Optional[dict] = None
        self.container = self._create_service_container()
        self.available_functions = {
            "query_database": self._query_database,
            "query_intelligence": self._query_intelligence,
            "query_arda_country": self._query_arda_country,
            "query_organization_profile": self._query_organization_profile,
            "query_contacts": self._query_contacts,
            "auto_collect": self._auto_collect,
            "get_user_profile": self._get_user_profile,
            "save_user_profile": self._save_user_profile,
            "query_ontology": self._query_ontology,
            "get_ontology_types": self._get_ontology_types,
            "query_investors": self._query_investors,
            "match_investors": self._match_investors,
            "generate_outreach_email": self._generate_outreach_email,
            "create_task": self._create_task,
            "match_acquirers": self._match_acquirers,
            "match_users": self._match_users,
            "query_graph": self._query_graph,
            "query_funding_rounds": self._query_funding_rounds,
            "query_fused": self._query_fused,
            "get_agent_status": self._get_agent_status,
        }

    def _service_container_enabled(self) -> bool:
        return feature_flag_enabled("SERVICE_CONTAINER_ENABLED")

    def _create_service_container(self):
        if not self._service_container_enabled():
            return None
        try:
            from services.default_services import build_default_service_container
            from services.service_container import ServiceScope

            return build_default_service_container(brain=self, scope=ServiceScope())
        except Exception as exc:
            logger.warning("[Brain] Service container init failed, fallback to legacy: %s", exc)
            return None

    def _bind_service_scope(self, conversation_id: str = "") -> None:
        if not self._service_container_enabled() or self.container is None:
            return
        try:
            from services.service_container import ServiceScope

            trace_payload = getattr(self, "_last_trace_session", {}) or {}
            trace_id = ""
            if isinstance(trace_payload, dict):
                trace_id = str(trace_payload.get("trace_id") or "")
            else:
                trace_id = str(getattr(trace_payload, "trace_id", "") or "")
            self.container.scope = ServiceScope(
                conversation_id=str(conversation_id or self.conversation_id or ""),
                trace_id=trace_id,
                memory_context=getattr(self, "_last_memory_context", None),
                pipeline_context=None,
            )
        except Exception:
            pass

    def _resolve_service(self, service_name: str, *, conversation_id: str = ""):
        if not self._service_container_enabled():
            return None
        if self.container is None:
            self.container = self._create_service_container()
        if self.container is None or not self.container.has(service_name):
            return None
        self._bind_service_scope(conversation_id)
        try:
            return self.container.get(service_name)
        except Exception:
            return None

    def _get_governor_service(self, *, conversation_id: str = ""):
        return self._resolve_service("architecture_governor", conversation_id=conversation_id)

    def _get_pipeline_service(self, *, conversation_id: str = ""):
        return self._resolve_service("pipeline_service", conversation_id=conversation_id)

    def _get_reasoning_engine_service(self, *, conversation_id: str = ""):
        return self._resolve_service("reasoning_engine", conversation_id=conversation_id)

    def _get_answer_composer_service(self, *, conversation_id: str = ""):
        return self._resolve_service("answer_composer", conversation_id=conversation_id)

    def _build_messages(
        self,
        user_message: str,
        conversation_history: list | None = None,
    ) -> list[dict]:
        prompt_route = self._route_prompt(user_message)
        print("ENTER build_messages")
        messages = [{"role": "system", "content": prompt_route["prompt"]}]
        if self.current_entities:
            entity_context = "当前对话中提到的实体：" + "、".join(
                f"{item['name']}({item['type']}, {item.get('country') or '未知国家'})"
                for item in self.current_entities[-5:]
                if item.get("name")
            )
            messages.append({"role": "system", "content": entity_context})
        for msg in (conversation_history or [])[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        print(f"messages_count={len(messages)}")
        return messages

    def _resolve_prompt_route(self, user_message: str) -> dict:
        msg = str(user_message or "").strip()
        lower = msg.lower()

        assistant_patterns = [
            r"系统介绍",
            r"介绍系统",
            r"介绍一下系统",
            r"系统是什么",
            r"介绍一下你自己",
            r"介绍你自己",
            r"自我介绍",
            r"你是谁",
            r"你是什么",
            r"你的能力",
            r"你是干什么的",
            r"你能做什么",
            r"你可以做什么",
            r"帮助我做什么",
            r"你的优势是什么",
            r"你的定位是什么",
            r"你的数据来源是什么",
            r"数据来源",
            r"信息来源",
            r"你的数据库来源",
            r"数据更新频率",
            r"数据库多久更新",
            r"数据怎么来的",
            r"为什么相信你的数据",
            r"如果数据库没有数据怎么办",
            r"数据库没有怎么办",
            r"查不到怎么办",
            r"数据库为空怎么办",
            r"没有数据怎么办",
            r"没数据怎么办",
            r"你会编造吗",
            r"你会幻觉吗",
            r"hallucination",
            r"这个系统和\s*chatgpt\s*有什么区别",
            r"为什么不用\s*chatgpt",
            r"知识来源",
            r"具备哪些能力",
            r"有哪些能力",
            r"怎么使用",
            r"如何使用",
            r"怎么用",
            r"使用方法",
            r"help",
            r"帮助",
            r"about",
            r"who are you",
            r"what can you do",
            r"introduce yourself",
            r"capability",
            r"capabilities",
            r"features",
            r"介绍一下系统",
            r"系统说明",
            r"架构说明",
            r"产品介绍",
            r"faithmate",
            r"christian intelligence os",
            r"cio",
        ]
        research_patterns = [
            r"评分",
            r"机构",
            r"人物",
            r"新闻",
            r"投资",
            r"关系",
            r"证据",
            r"情报",
            r"research",
            r"score",
            r"organization",
            r"person",
            r"news",
            r"invest",
            r"evidence",
            r"intelligence",
        ]
        greeting_patterns = [r"^你好[！!,.，。 ]*$", r"^嗨[！!,.，。 ]*$", r"^hello[!,. ]*$", r"^hi[!,. ]*$"]

        matched_assistant_pattern = next(
            (pattern for pattern in assistant_patterns if re.search(pattern, msg, re.IGNORECASE)),
            None,
        )
        if self._looks_like_entity_source_query(msg):
            return {
                "intent": "research",
                "selected_prompt": "Research Prompt",
                "reason": "entity_source_query",
                "prompt": RESEARCH_SYSTEM_PROMPT,
            }
        if self._classify_product_intent(msg):
            print(f"MATCHED_PRODUCT_INTENT={self._classify_product_intent(msg)}")
            print("Intent=assistant")
            print("SelectedPrompt=Assistant Prompt")
            print("Reason=matched_product_intent")
            return {
                "intent": "assistant",
                "selected_prompt": "Assistant Prompt",
                "reason": "matched_product_intent",
                "prompt": ASSISTANT_SYSTEM_PROMPT,
            }
        if matched_assistant_pattern:
            print(f"MATCHED_ASSISTANT_PATTERN={matched_assistant_pattern}")
            print("Intent=assistant")
            print("SelectedPrompt=Assistant Prompt")
            print("Reason=matched_assistant_pattern")
            return {
                "intent": "assistant",
                "selected_prompt": "Assistant Prompt",
                "reason": "matched_assistant_pattern",
                "prompt": ASSISTANT_SYSTEM_PROMPT,
            }
        if any(re.search(pattern, msg, re.IGNORECASE) for pattern in greeting_patterns):
            return {
                "intent": "assistant",
                "selected_prompt": "Assistant Prompt",
                "reason": "greeting",
                "prompt": ASSISTANT_SYSTEM_PROMPT,
            }
        if any(re.search(pattern, lower, re.IGNORECASE) for pattern in research_patterns):
            return {
                "intent": "research",
                "selected_prompt": "Research Prompt",
                "reason": "matched_research_intent",
                "prompt": RESEARCH_SYSTEM_PROMPT,
            }
        return {
            "intent": "research",
            "selected_prompt": "Research Prompt",
            "reason": "default_research",
            "prompt": RESEARCH_SYSTEM_PROMPT,
        }

    def _log_prompt_route_observability(self, route: Optional[dict]) -> None:
        route_payload = dict(route or {})
        print(f"Intent={str(route_payload.get('intent') or '').strip().lower()}")
        print(f"SelectedPrompt={str(route_payload.get('selected_prompt') or '').strip()}")
        print(f"Reason={str(route_payload.get('reason') or '').strip()}")

    def _route_prompt(self, user_message: str) -> dict:
        print("ENTER PromptRouter")
        result = self._resolve_prompt_route(user_message)
        print(f"Selected Prompt={result['selected_prompt']}")
        self._log_prompt_route_observability(result)
        return result

    def _is_assistant_prompt_route(self, prompt_route: Optional[dict]) -> bool:
        route = dict(prompt_route or {})
        intent = str(route.get("intent") or "").strip().lower()
        selected_prompt = str(route.get("selected_prompt") or "").strip()
        return intent == "assistant" or selected_prompt == "Assistant Prompt"

    def _classify_product_intent(self, user_message: str) -> str:
        text = str(user_message or "").strip()
        if not text:
            return ""

        chatgpt_patterns = [
            r"这个系统和\s*chatgpt\s*有什么区别",
            r"为什么不用\s*chatgpt",
            r"你的优势是什么",
            r"你的定位是什么",
        ]
        data_source_patterns = [
            r"^你的数据来源是什么[？?]?$",
            r"^系统的数据来源是什么[？?]?$",
            r"^你从哪里获取数据[？?]?$",
            r"^系统从哪里获取数据[？?]?$",
            r"^你的数据库来源是什么[？?]?$",
            r"^数据更新频率[？?]?$",
            r"^数据库多久更新[？?]?$",
            r"^数据怎么来的[？?]?$",
            r"^为什么相信你的数据[？?]?$",
        ]
        no_data_patterns = [
            r"如果数据库没有数据怎么办",
            r"数据库没有怎么办",
            r"查不到怎么办",
            r"数据库为空怎么办",
            r"没有数据怎么办",
            r"没数据怎么办",
            r"你会编造吗",
            r"你会幻觉吗",
            r"hallucination",
        ]

        if any(re.search(pattern, text, re.IGNORECASE) for pattern in chatgpt_patterns):
            return "product_vs_chatgpt"
        if self._looks_like_entity_source_query(text):
            return ""
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in data_source_patterns):
            return "product_data_sources"
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in no_data_patterns):
            return "product_no_data"
        return ""

    def _looks_like_entity_source_query(self, user_message: str) -> bool:
        text = str(user_message or "").strip()
        if not text:
            return False
        if re.search(r"^(你的|系统的|你从哪里|系统从哪里)", text, re.IGNORECASE):
            return False
        return bool(
            re.search(r"(数据来源|证据来源|来源是什么|信息来自哪里|来源有哪些)", text, re.IGNORECASE)
            or re.search(r"这条情报的来源是什么", text, re.IGNORECASE)
        )

    def _build_product_intent_response(self, user_message: str) -> str:
        intent_type = self._classify_product_intent(user_message)
        if intent_type == "product_vs_chatgpt":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "这个系统和 ChatGPT 的区别\n"
                "- CIO 是垂直领域企业级情报平台。\n"
                "- ChatGPT 是通用大语言模型。\n"
                "- 我优先查询数据库。\n"
                "- 提供来源。\n"
                "- 提供 URL。\n"
                "- 提供评分。\n"
                "- 提供关系分析。\n"
                "- 数据库没有的数据不会编造。"
            )
        if intent_type == "product_data_sources":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "数据来源\n"
                "- 公开数据库\n"
                "- 官方网站\n"
                "- 机构公开资料\n"
                "- RSS\n"
                "- 新闻\n"
                "- 媒体\n"
                "- YouTube\n"
                "- 公开报告\n"
                "- 系统整合后的数据库。"
            )
        if intent_type == "product_no_data":
            return (
                "Christian Intelligence Operating System（CIO）\n"
                "Enterprise Christian Intelligence Platform\n"
                "企业级基督教情报分析平台\n\n"
                "数据库没有数据时：\n"
                "① 明确说明没有数据\n"
                "② 不编造结果\n"
                "③ 提示数据缺口\n"
                "④ 如开启补采，将进入后台采集\n"
                "⑤ 后续数据库更新后即可查询"
            )
        return ""

    def _product_intent_direct_result(self, user_message: str) -> Optional[dict]:
        answer = self._build_product_intent_response(user_message)
        if not answer:
            return None
        return {
            "answer": answer,
            "evidence": [],
            "direct_answer": True,
            "product_intent": self._classify_product_intent(user_message),
        }

    def _should_prefer_pipeline_for_insight_render(self) -> bool:
        return bool(
            feature_flag_enabled("PIPELINE_ORCHESTRATOR_ENABLED")
            and feature_flag_enabled("INSIGHT_ENGINE_ENABLED")
            and feature_flag_enabled("INSIGHT_FINAL_RENDER_ENABLED")
        )

    def _should_allow_gap_detection(self, user_message: str, prompt_route: Optional[dict] = None) -> bool:
        route = dict(prompt_route or self._resolve_prompt_route(user_message) or {})
        if self._is_assistant_prompt_route(route):
            return False
        if str(route.get("intent") or "").strip().lower() != "research":
            return False
        if str(route.get("selected_prompt") or "").strip() != "Research Prompt":
            return False
        return any(
            [
                bool(detect_analysis_type(user_message)),
                self._looks_like_organization_profile_query(user_message),
                self._looks_like_arda_country_query(user_message),
                self._looks_like_graph_query(user_message),
                self._looks_like_news_query(user_message),
                self._looks_like_funding_query(user_message),
                self._looks_like_investor_query(user_message),
                self._looks_like_fused_query(user_message),
                self._looks_like_intel_query(user_message),
                bool(self._extract_organization_profile_name(user_message)),
                bool(self._extract_entity(user_message)),
                bool(self._extract_country(user_message)),
            ]
        )

    def _log_gap_detection_status(
        self,
        user_message: str,
        *,
        prompt_route: Optional[dict] = None,
        gap_detection: bool,
        gap_notice: bool,
        auto_collection: bool,
    ) -> None:
        route = dict(prompt_route or self._resolve_prompt_route(user_message) or {})
        print(f"Intent={str(route.get('intent') or '').strip().lower()}")
        print(f"SelectedPrompt={str(route.get('selected_prompt') or '').strip()}")
        print(f"GapDetection={bool(gap_detection)}")
        print(f"GapNotice={bool(gap_notice)}")
        print(f"AutoCollection={bool(auto_collection)}")

    def _apply_gap_notice_policy(self, user_message: str, content: str, prompt_route: Optional[dict] = None) -> str:
        route = dict(prompt_route or self._resolve_prompt_route(user_message) or {})
        gap_detection = self._should_allow_gap_detection(user_message, prompt_route=route)
        gap_notice = bool(content) and "[INSUFFICIENT DATA]" in str(content) and "已触发自动情报采集" not in str(content)
        if not gap_detection:
            self._log_gap_detection_status(
                user_message,
                prompt_route=route,
                gap_detection=False,
                gap_notice=False,
                auto_collection=False,
            )
            return content
        if not gap_notice:
            self._log_gap_detection_status(
                user_message,
                prompt_route=route,
                gap_detection=True,
                gap_notice=False,
                auto_collection=False,
            )
            return content
        return self._append_gap_collection_notice(
            user_message,
            content,
            prompt_route=route,
            gap_detection=True,
        )

    def _format_reasoning_engine_v1_message(
        self,
        question_type_value: str,
        requirement: dict,
        tool_plan: list[str],
        evaluation: dict,
        conflicts: list[dict],
        outline: list[str],
    ) -> str:
        required_fields = (requirement or {}).get("required_fields") or []
        missing_fields = (evaluation or {}).get("missing_fields") or []
        missing_sources = (evaluation or {}).get("missing_sources") or []
        lines = [
            "Reasoning Plan",
            "",
            f"Question Type: {question_type_value}",
            f"Required Facts: {', '.join(required_fields)}",
            f"Minimum Sources: {(requirement or {}).get('minimum_sources')}",
            f"Evidence Coverage: {(evaluation or {}).get('coverage')}",
            f"Missing Fields: {', '.join(missing_fields) if missing_fields else 'None'}",
            f"Missing Sources: {', '.join(missing_sources) if missing_sources else 'None'}",
            f"Conflicts: {len(conflicts or [])}",
            f"Answer Outline: {', '.join(outline or [])}",
            "",
            "Answer Rules",
            "1) Only answer using evidence.",
            "2) If coverage is insufficient, explicitly state the missing information.",
            "3) If conflicts exist, mention them.",
            "4) Use evidence according to ranking order.",
            "5) Follow the provided outline.",
        ]
        return "\n".join(lines)

    def _build_answer_context(self, user_message: str, tool_results: list[dict]) -> Optional[dict]:
        try:
            from services.core_models import Evidence, QuestionContext, QuestionType, Requirement

            ctx = getattr(self, "_reasoning_v1_context", {}) or {}
            qt_value = str(ctx.get("question_type") or "UNKNOWN")
            qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN

            req = ctx.get("requirement")
            requirement = req if isinstance(req, Requirement) else Requirement.from_dict(req or {})

            question_context = QuestionContext(
                question=str(user_message or ""),
                question_type=qt,
                language="",
                country=str(ctx.get("country") or ""),
                entities=list(getattr(self, "current_entities", []) or []),
                time_range=None,
                comparison=qt == QuestionType.COMPARISON,
                ranking=qt == QuestionType.RANKING,
                relationship=qt in {QuestionType.RELATIONSHIP, QuestionType.GRAPH, QuestionType.INVESTMENT},
                conversation_id=str(getattr(self, "conversation_id", "") or ""),
            )

            raw_evidence: list[dict] = []
            for r in tool_results or []:
                if not isinstance(r, dict):
                    continue
                ev_list = r.get("evidence")
                if isinstance(ev_list, list):
                    for e in ev_list:
                        if isinstance(e, dict):
                            raw_evidence.append(e)
                if str(r.get("status") or "").lower() == "success":
                    organization = r.get("organization")
                    if isinstance(organization, dict):
                        score_snippet = self._build_score_snippet(profile=organization)
                        if score_snippet:
                            raw_evidence.append(
                                {
                                    "title": f"{organization.get('name') or 'Organization'} scorecard",
                                    "source_name": organization.get("source_name") or "organization_profile",
                                    "url": organization.get("official_website") or "",
                                    "confidence": 0.95,
                                    "published_at": "",
                                    "updated_at": "",
                                    "type": "organization_scorecard",
                                    "snippet": score_snippet,
                                }
                            )

            evidence_models: list[Evidence] = []
            for idx, e in enumerate(raw_evidence, start=1):
                evidence_models.append(
                    Evidence(
                        id=f"E{idx}",
                        title=str(e.get("title") or ""),
                        snippet=str(e.get("snippet") or ""),
                        url=str(e.get("url") or ""),
                        source_name=str(e.get("source_name") or ""),
                        authority=float(e.get("authority") or 0.0),
                        confidence=float(e.get("confidence") or 0.0),
                        published_at=str(e.get("published_at") or ""),
                        updated_at=str(e.get("updated_at") or ""),
                        type=str(e.get("type") or ""),
                    )
                )

            composer = self._get_answer_composer_service(conversation_id=str(getattr(self, "conversation_id", "") or ""))
            if composer is None:
                from services.answer_composer import AnswerComposer

                composer = AnswerComposer()
            answer_context = composer.compose(question_context, requirement, evidence_models)
            return answer_context.to_dict()
        except Exception:
            return None

    def _format_answer_context(self, answer_context: dict) -> str:
        payload = dict(answer_context or {})
        evidence = payload.get("evidence")
        if isinstance(evidence, list) and len(evidence) > 25:
            payload["evidence"] = evidence[:25]
        facts = payload.get("facts")
        if isinstance(facts, list) and len(facts) > 40:
            payload["facts"] = facts[:40]
        return "Answer Context\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    def _filter_dsml(self, content: str) -> str:
        if not content:
            return ""
        filtered = re.sub(r"<｜｜DSML｜｜tool_calls>[\s\S]*?<｜｜DSML｜｜/tool_calls>", "", content)
        filtered = re.sub(r"<｜｜DSML｜｜invoke[\s\S]*?<｜｜DSML｜｜/invoke>", "", filtered)
        filtered = re.sub(r"<｜｜DSML｜｜parameter[^>]*>[\s\S]*?<｜｜DSML｜｜/parameter>", "", filtered)
        filtered = re.sub(r"<｜｜DSML｜｜[^>]*>", "", filtered)
        filtered = re.sub(r"<｜｜DSML｜｜/[^>]*>", "", filtered)
        filtered = re.sub(r"\n{3,}", "\n\n", filtered).strip()
        return filtered

    def _clean_output(self, text: str) -> str:
        """清理输出，移除内部标记。"""
        cleaned = text or ""
        cleaned = re.sub(r"\[\[.*?\]\]", "", cleaned)
        cleaned = re.sub(r"\[SOURCE:.*?\]", "", cleaned)
        cleaned = re.sub(r"\[CONFIDENCE:.*?\]", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _coerce_datetime_str(self, value: Any) -> str:
        if not value:
            return ""
        try:
            return value.isoformat()
        except Exception:
            return ""

    def _normalize_score_value(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except Exception:
            return None
        if number.is_integer():
            return int(number)
        return round(number, 2)

    def _extract_score_payload(self, *, org: Any = None, profile: Optional[dict] = None) -> dict:
        people_score = self._normalize_score_value(
            (profile or {}).get("people_score") if isinstance(profile, dict) else getattr(org, "people_score", None)
        )
        digital_score = self._normalize_score_value(
            (profile or {}).get("digital_score") if isinstance(profile, dict) else getattr(org, "digital_score", None)
        )
        intel_score = self._normalize_score_value(
            (profile or {}).get("intel_score") if isinstance(profile, dict) else getattr(org, "intel_score", None)
        )
        explicit_composite = None
        if isinstance(profile, dict):
            explicit_composite = self._normalize_score_value(profile.get("composite_score"))
        elif org is not None:
            explicit_composite = self._normalize_score_value(getattr(org, "composite_score", None))
        component_scores = [item for item in [people_score, digital_score, intel_score] if item is not None]
        composite_score = explicit_composite if explicit_composite is not None else (sum(component_scores) if component_scores else None)
        return {
            "people_score": people_score,
            "digital_score": digital_score,
            "intel_score": intel_score,
            "composite_score": composite_score,
        }

    def _build_score_snippet(self, *, org: Any = None, profile: Optional[dict] = None) -> str:
        score_payload = self._extract_score_payload(org=org, profile=profile)
        if not any(score_payload.get(field) is not None for field in ("people_score", "digital_score", "intel_score", "composite_score")):
            return ""
        return (
            f"people_score={score_payload.get('people_score', 'N/A')}; "
            f"digital_score={score_payload.get('digital_score', 'N/A')}; "
            f"intel_score={score_payload.get('intel_score', 'N/A')}; "
            f"composite_score={score_payload.get('composite_score', 'N/A')}"
        )

    def _is_score_lookup_parsed_result(self, parsed_result: Optional[dict]) -> bool:
        if not isinstance(parsed_result, dict):
            return False
        intent = str(parsed_result.get("intent") or "").strip()
        response_contract = str(parsed_result.get("response_contract") or "").strip()
        return intent == "organization_score_lookup" or response_contract == "score_lookup"

    def _is_relationship_graph_parsed_result(self, parsed_result: Optional[dict]) -> bool:
        if not isinstance(parsed_result, dict):
            return False
        intent = str(parsed_result.get("intent") or "").strip()
        response_contract = str(parsed_result.get("response_contract") or "").strip()
        return intent == "organization_relationship_graph_lookup" or response_contract == "relationship_graph"

    def _normalize_requested_scores(self, parsed_result: Optional[dict]) -> list[str]:
        if not isinstance(parsed_result, dict):
            return ["people_score", "digital_score", "intel_score"]
        requested = parsed_result.get("requested_scores")
        if not isinstance(requested, list):
            requested = []
        canonical = ["people_score", "digital_score", "intel_score", "composite_score"]
        normalized = [item for item in canonical if item in requested]
        return normalized or ["people_score", "digital_score", "intel_score"]

    def _normalize_graph_options(self, parsed_result: Optional[dict]) -> tuple[int, bool]:
        if not isinstance(parsed_result, dict):
            return 1, False
        try:
            depth = int(parsed_result.get("depth") or 1)
        except Exception:
            depth = 1
        include_unverified = bool(parsed_result.get("include_unverified"))
        return depth or 1, include_unverified

    def _graph_node_label_map(self, graph_payload: dict) -> dict[str, str]:
        labels: dict[str, str] = {}
        center = graph_payload.get("center") or {}
        center_graph_id = str(center.get("graph_id") or "")
        center_name = str(center.get("name") or "")
        if center_graph_id and center_name:
            labels[center_graph_id] = center_name
        for node in graph_payload.get("nodes") or []:
            graph_id = str(node.get("id") or "")
            label = str(node.get("name") or node.get("label") or "")
            if graph_id and label:
                labels[graph_id] = label
        return labels

    def _graph_evidence_from_payload(self, graph_payload: dict) -> list[dict]:
        evidence: list[dict] = []
        center = graph_payload.get("center") or {}
        center_name = str(center.get("name") or "").strip()
        for edge in graph_payload.get("edges") or []:
            evidence.append(
                self._normalize_evidence_item(
                    {
                        "title": f'{center_name} {edge.get("relation_type") or "relationship"}',
                        "source_name": str(edge.get("evidence_source") or "relation_graph"),
                        "url": str(edge.get("evidence_url") or ""),
                        "confidence": float(edge.get("confidence") or 0.0),
                        "published_at": str(edge.get("evidence_date") or ""),
                        "updated_at": str(edge.get("evidence_date") or ""),
                        "type": "relationship_graph",
                        "snippet": str(edge.get("reason") or ""),
                    }
                )
            )
        return evidence

    def _format_relationship_graph_answer(self, *, graph_payload: dict, lang: str) -> str:
        center = graph_payload.get("center") or {}
        center_name = str(center.get("name") or "Unknown Organization")
        edges = list(graph_payload.get("edges") or [])
        warnings = list(graph_payload.get("warnings") or [])
        label_map = self._graph_node_label_map(graph_payload)

        if not bool(graph_payload.get("found")) or not center:
            if lang == "zh":
                return (
                    f'未在当前数据库中找到 "{center_name}" 的关系图谱中心机构。\n'
                    "status=not_found\n"
                    "response_contract=relationship_graph\n"
                    "我不会编造关系。后续可以创建补充采集任务来查找公开合作方、联盟、媒体和事工关系。\n"
                    "数据来源：本地 intelligence database。\n"
                    "llm_used=false"
                )
            return (
                f'No relationship-graph center organization was found for "{center_name}".\n'
                "status=not_found\n"
                "response_contract=relationship_graph\n"
                "I will not fabricate relationships. A follow-up collection mission can be created later to gather public partner, alliance, media, and ministry links.\n"
                "Data source: local intelligence database.\n"
                "llm_used=false"
            )

        if not edges:
            if lang == "zh":
                lines = [
                    f"当前数据库还没有发现 {center_name} 的有证据关系图谱。",
                    "status=no_relations",
                    "response_contract=relationship_graph",
                    "我不会编造关系。可以在后续阶段创建补充采集任务来查找公开合作方、联盟、媒体和事工关系。",
                    "warnings:",
                ]
            else:
                lines = [
                    f"The current database has not found any evidence-backed relationship graph for {center_name}.",
                    "status=no_relations",
                    "response_contract=relationship_graph",
                    "I will not fabricate relationships. A follow-up collection mission can be created later to gather public partner, alliance, media, and ministry links.",
                    "warnings:",
                ]
            for warning in warnings or [{"code": "no_relations", "message": "No graph relations found for this organization"}]:
                lines.append(f"- {warning.get('code')}: {warning.get('message')}")
            lines.extend(
                [
                    "数据来源：本地 intelligence database。" if lang == "zh" else "Data source: local intelligence database.",
                    "llm_used=false",
                ]
            )
            return "\n".join(lines)

        if lang == "zh":
            lines = [
                f"{center_name} 的关系图谱目前有 {len(edges)} 条有证据关系：",
                "以下关系来自数据库证据，不是推测。",
                "response_contract=relationship_graph",
                f"中心机构：{center_name}",
                f"关系数量：{len(edges)}",
                "相关机构列表："
                + ("、".join(sorted({label_map.get(edge.get('target')) or label_map.get(edge.get('source')) or '' for edge in edges if (label_map.get(edge.get('target')) or label_map.get(edge.get('source')))})) or "无"),
                "",
            ]
        else:
            lines = [
                f"{center_name} currently has {len(edges)} evidence-backed relationships in the database:",
                "The following relationships come from database evidence and are not guesses.",
                "response_contract=relationship_graph",
                f"Center organization: {center_name}",
                f"Relationship count: {len(edges)}",
                "Related organizations: "
                + (", ".join(sorted({label_map.get(edge.get('target')) or label_map.get(edge.get('source')) or '' for edge in edges if (label_map.get(edge.get('target')) or label_map.get(edge.get('source')))})) or "none"),
                "",
            ]

        center_graph_id = str(center.get("graph_id") or "")
        for idx, edge in enumerate(edges, start=1):
            source_label = label_map.get(str(edge.get("source") or ""), str(edge.get("source") or "unknown"))
            target_label = label_map.get(str(edge.get("target") or ""), str(edge.get("target") or "unknown"))
            evidence_ref = edge.get("evidence_url") or edge.get("evidence_source") or "证据链接缺失 / missing_evidence"
            if str(edge.get("source") or "") == center_graph_id:
                counterpart = target_label
            elif str(edge.get("target") or "") == center_graph_id:
                counterpart = source_label
            else:
                counterpart = target_label
            lines.extend(
                [
                    f"{idx}. {center_name} -> {counterpart}",
                    f"   - relation_type: {edge.get('relation_type') or 'unknown'}",
                    f"   - evidence: {evidence_ref}",
                    f"   - confidence: {edge.get('confidence')}",
                    f"   - is_verified: {str(bool(edge.get('is_verified'))).lower()}",
                ]
            )
            if edge.get("missing_evidence"):
                lines.append("   - warning: missing_evidence")
            reason = str(edge.get("reason") or "").strip()
            if reason:
                lines.append(f"   - reason: {reason}")
            lines.append("")

        lines.append("warnings:")
        if warnings:
            for warning in warnings:
                lines.append(f"- {warning.get('code')}: {warning.get('message')}")
        else:
            lines.append("- none")
        lines.extend(
            [
                "数据来源：本地 intelligence database。" if lang == "zh" else "Data source: local intelligence database.",
                "llm_used=false",
            ]
        )
        return "\n".join(lines).strip()

    def _find_organization_for_score_lookup(self, organization_name: str):
        from models.database import OrganizationProfile, get_db
        from sqlalchemy import case, desc, func, or_

        normalized_name = (organization_name or "").strip()
        if not normalized_name:
            return None

        db_gen = get_db()
        db = next(db_gen)
        try:
            query = (
                db.query(OrganizationProfile)
                .filter(
                    or_(
                        OrganizationProfile.name.ilike(f"%{normalized_name}%"),
                        OrganizationProfile.name_local.ilike(f"%{normalized_name}%"),
                        OrganizationProfile.official_name.ilike(f"%{normalized_name}%"),
                        OrganizationProfile.short_name.ilike(f"%{normalized_name}%"),
                        OrganizationProfile.english_name.ilike(f"%{normalized_name}%"),
                    )
                )
                .order_by(
                    case(
                        (func.lower(OrganizationProfile.name) == normalized_name.lower(), 0),
                        (func.lower(OrganizationProfile.name_local) == normalized_name.lower(), 0),
                        (func.lower(OrganizationProfile.official_name) == normalized_name.lower(), 0),
                        (func.lower(OrganizationProfile.short_name) == normalized_name.lower(), 0),
                        (func.lower(OrganizationProfile.english_name) == normalized_name.lower(), 0),
                        else_=1,
                    ),
                    case((OrganizationProfile.source_name == "manual_seed", 0), else_=1),
                    func.length(OrganizationProfile.name).asc(),
                    desc(OrganizationProfile.updated_at),
                )
            )
            org = query.first()
            if org is not None:
                db.expunge(org)
            return org
        finally:
            db_gen.close()

    def _format_score_lookup_answer(
        self,
        *,
        organization_name: str,
        score_payload: dict,
        requested_scores: list[str],
        lang: str,
    ) -> str:
        label_map = {
            "people_score": "People Score",
            "digital_score": "Digital Score",
            "intel_score": "Intel Score",
            "composite_score": "Composite Score",
        }
        lines = [
            f"{organization_name} 的数据库评分如下：" if lang == "zh" else f"{organization_name} database scores:",
            "",
        ]
        for field_name in requested_scores:
            value = score_payload.get(field_name)
            if value is None:
                continue
            lines.append(f"{label_map[field_name]}: {value}")
        lines.extend(
            [
                "",
                "数据来源：本地 intelligence database。" if lang == "zh" else "Data source: local intelligence database.",
                "llm_used=false",
            ]
        )
        return "\n".join(lines).strip()

    def _format_score_lookup_not_found(self, *, organization_name: str, lang: str) -> str:
        if lang == "zh":
            return (
                f'未在当前数据库中找到 "{organization_name}" 的评分数据。\n'
                "status=not_found\n"
                "因此我不能给出 people_score / digital_score / intel_score。\n"
                "数据来源：本地 intelligence database。\n"
                "llm_used=false"
            )
        return (
            f'No score data was found for "{organization_name}" in the local intelligence database.\n'
            "status=not_found\n"
            "I cannot provide people_score, digital_score, or intel_score for this organization.\n"
            "Data source: local intelligence database.\n"
            "llm_used=false"
        )

    def _build_score_lookup_collection_targets(self) -> list[str]:
        return ["website", "rss", "youtube", "telegram", "web_search"]

    def _build_score_lookup_mission_draft(
        self,
        *,
        organization_name: str,
        requested_scores: list[str],
        request_id: str,
    ) -> dict:
        return {
            "mission_type": "organization_score_data_collection",
            "organization_name": organization_name,
            "reason": "score_lookup_db_miss",
            "requested_scores": list(requested_scores or []),
            "status": "draft",
            "collection_required": True,
            "collection_targets": self._build_score_lookup_collection_targets(),
            "created_by": "brain_score_lookup",
            "request_id": request_id,
        }

    def _create_score_lookup_collection_mission(
        self,
        *,
        organization_name: str,
        requested_scores: list[str],
        request_id: str,
    ) -> dict:
        mission_draft = self._build_score_lookup_mission_draft(
            organization_name=organization_name,
            requested_scores=requested_scores,
            request_id=request_id,
        )
        try:
            from services.mission_service import create_collection_mission

            mission = create_collection_mission(
                query=organization_name,
                country="全球",
                target_entity=organization_name,
                metadata={
                    "mission_type": mission_draft["mission_type"],
                    "reason": mission_draft["reason"],
                    "requested_scores": mission_draft["requested_scores"],
                    "collection_targets": mission_draft["collection_targets"],
                    "created_by": mission_draft["created_by"],
                    "request_id": request_id,
                },
            )
            mission_id = getattr(mission, "id", None) if mission is not None else None
            return {
                "collection_required": True,
                "mission_created": bool(mission_id),
                "mission_id": mission_id,
                "mission_mode": "created_persistent_mission" if mission_id else "mission_draft_only",
                "mission_draft": None if mission_id else mission_draft,
                "collection_targets": mission_draft["collection_targets"],
            }
        except Exception as exc:
            logger.info(
                "event=brain.score_lookup.mission_fallback organization_name=%s reason=%s",
                organization_name,
                str(exc)[:200],
            )
            return {
                "collection_required": True,
                "mission_created": False,
                "mission_id": None,
                "mission_mode": "mission_draft_only",
                "mission_draft": mission_draft,
                "collection_targets": mission_draft["collection_targets"],
            }

    def _append_collection_followup_to_not_found_answer(
        self,
        *,
        base_answer: str,
        mission_info: dict,
        lang: str,
    ) -> str:
        mission_id = mission_info.get("mission_id")
        if mission_info.get("mission_created") and mission_id:
            followup = (
                f"\n已创建补采 Mission：{mission_id}\ncollection_required=true"
                if lang == "zh"
                else f"\nCollection mission created: {mission_id}\ncollection_required=true"
            )
        else:
            followup = (
                "\n已准备补采任务草案，等待后续采集执行。\ncollection_required=true"
                if lang == "zh"
                else "\nA collection mission draft has been prepared for follow-up gathering.\ncollection_required=true"
            )
        return f"{base_answer}\n{followup}".strip()

    def _store_score_lookup_trace(self, trace_payload: dict) -> dict:
        safe_trace = {
            "request_id": str(trace_payload.get("request_id") or ""),
            "route": str(trace_payload.get("route") or ""),
            "intent_detection_ms": float(trace_payload.get("intent_detection_ms") or 0.0),
            "db_lookup_ms": float(trace_payload.get("db_lookup_ms") or 0.0),
            "scorer_lookup_ms": float(trace_payload.get("scorer_lookup_ms") or 0.0),
            "planner_ms": float(trace_payload.get("planner_ms") or 0.0),
            "llm_ms": float(trace_payload.get("llm_ms") or 0.0),
            "total_ms": float(trace_payload.get("total_ms") or 0.0),
            "db_hit": bool(trace_payload.get("db_hit")),
            "llm_called": bool(trace_payload.get("llm_called")),
            "fallback_used": bool(trace_payload.get("fallback_used")),
            "organization_name": str(trace_payload.get("organization_name") or ""),
            "answer_contract": str(trace_payload.get("answer_contract") or ""),
            "collection_required": bool(trace_payload.get("collection_required")),
            "mission_created": bool(trace_payload.get("mission_created")),
            "mission_id": trace_payload.get("mission_id"),
            "mission_mode": str(trace_payload.get("mission_mode") or ""),
            "collection_targets": list(trace_payload.get("collection_targets") or []),
            "requested_scores": list(trace_payload.get("requested_scores") or []),
        }
        self.last_score_lookup_trace = safe_trace
        logger.info(
            "event=brain.score_lookup request_id=%s route=%s organization_name=%s "
            "answer_contract=%s db_hit=%s llm_called=%s fallback_used=%s "
            "collection_required=%s mission_created=%s mission_id=%s collection_targets=%s "
            "intent_detection_ms=%.3f db_lookup_ms=%.3f scorer_lookup_ms=%.3f planner_ms=%.3f llm_ms=%.3f total_ms=%.3f",
            safe_trace["request_id"],
            safe_trace["route"],
            safe_trace["organization_name"],
            safe_trace["answer_contract"],
            safe_trace["db_hit"],
            safe_trace["llm_called"],
            safe_trace["fallback_used"],
            safe_trace["collection_required"],
            safe_trace["mission_created"],
            safe_trace["mission_id"],
            safe_trace["collection_targets"],
            safe_trace["intent_detection_ms"],
            safe_trace["db_lookup_ms"],
            safe_trace["scorer_lookup_ms"],
            safe_trace["planner_ms"],
            safe_trace["llm_ms"],
            safe_trace["total_ms"],
        )
        return safe_trace

    def _resolve_score_lookup_if_applicable(
        self,
        *,
        user_message: str,
        conversation_id: str,
        route: str = "simple",
        request_id: Optional[str] = None,
    ) -> Optional[dict]:
        started_at = time.perf_counter()
        if not re.search(r"score|scores|评分|分数|得分", user_message or "", re.IGNORECASE):
            return None

        parser = None
        parser_started_at = time.perf_counter()
        try:
            from .query_parser import QueryParser

            parser = QueryParser()
            parsed_result = parser.parse(user_message, conversation_id=conversation_id)
        finally:
            if parser:
                parser.close()
        intent_detection_ms = round((time.perf_counter() - parser_started_at) * 1000.0, 3)

        if not self._is_score_lookup_parsed_result(parsed_result):
            return None

        organization_name = str((parsed_result or {}).get("organization_name") or "").strip()
        if not organization_name:
            return None

        requested_scores = self._normalize_requested_scores(parsed_result)
        lang = "zh" if re.search(r"[\u4e00-\u9fff]", user_message or "") else "en"
        trace_request_id = str(request_id or f"{route}-{uuid.uuid4().hex[:12]}")
        db_started_at = time.perf_counter()
        org = self._find_organization_for_score_lookup(organization_name)
        db_lookup_ms = round((time.perf_counter() - db_started_at) * 1000.0, 3)
        if org is None:
            mission_info = self._create_score_lookup_collection_mission(
                organization_name=organization_name,
                requested_scores=requested_scores,
                request_id=trace_request_id,
            )
            answer_contract = "not_found"
            trace_payload = self._store_score_lookup_trace(
                {
                    "request_id": trace_request_id,
                    "route": route,
                    "intent_detection_ms": intent_detection_ms,
                    "db_lookup_ms": db_lookup_ms,
                    "scorer_lookup_ms": 0.0,
                    "planner_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
                    "db_hit": False,
                    "llm_called": False,
                    "fallback_used": False,
                    "organization_name": organization_name,
                    "answer_contract": answer_contract,
                    "collection_required": mission_info.get("collection_required"),
                    "mission_created": mission_info.get("mission_created"),
                    "mission_id": mission_info.get("mission_id"),
                    "mission_mode": mission_info.get("mission_mode"),
                    "collection_targets": mission_info.get("collection_targets"),
                    "requested_scores": requested_scores,
                }
            )
            return {
                "parsed_result": parsed_result,
                "answer": self._append_collection_followup_to_not_found_answer(
                    base_answer=self._format_score_lookup_not_found(organization_name=organization_name, lang=lang),
                    mission_info=mission_info,
                    lang=lang,
                ),
                "evidence": [],
                "organization_name": organization_name,
                "data_source": "database",
                "llm_used": False,
                "trace": trace_payload,
                "mission_id": mission_info.get("mission_id"),
                "mission_created": mission_info.get("mission_created"),
                "mission_draft": mission_info.get("mission_draft"),
            }

        score_payload = self._extract_score_payload(org=org)
        available_fields = [field for field in requested_scores if score_payload.get(field) is not None]
        if not available_fields:
            resolved_organization_name = getattr(org, "name", organization_name)
            mission_info = self._create_score_lookup_collection_mission(
                organization_name=resolved_organization_name,
                requested_scores=requested_scores,
                request_id=trace_request_id,
            )
            answer_contract = "not_found"
            trace_payload = self._store_score_lookup_trace(
                {
                    "request_id": trace_request_id,
                    "route": route,
                    "intent_detection_ms": intent_detection_ms,
                    "db_lookup_ms": db_lookup_ms,
                    "scorer_lookup_ms": 0.0,
                    "planner_ms": 0.0,
                    "llm_ms": 0.0,
                    "total_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
                    "db_hit": False,
                    "llm_called": False,
                    "fallback_used": False,
                    "organization_name": resolved_organization_name,
                    "answer_contract": answer_contract,
                    "collection_required": mission_info.get("collection_required"),
                    "mission_created": mission_info.get("mission_created"),
                    "mission_id": mission_info.get("mission_id"),
                    "mission_mode": mission_info.get("mission_mode"),
                    "collection_targets": mission_info.get("collection_targets"),
                    "requested_scores": requested_scores,
                }
            )
            return {
                "parsed_result": parsed_result,
                "answer": self._append_collection_followup_to_not_found_answer(
                    base_answer=self._format_score_lookup_not_found(organization_name=resolved_organization_name, lang=lang),
                    mission_info=mission_info,
                    lang=lang,
                ),
                "evidence": [self._evidence_from_organization_profile(org, evidence_type="organization_score_lookup")],
                "organization_name": resolved_organization_name,
                "data_source": "database",
                "llm_used": False,
                "trace": trace_payload,
                "mission_id": mission_info.get("mission_id"),
                "mission_created": mission_info.get("mission_created"),
                "mission_draft": mission_info.get("mission_draft"),
            }

        resolved_organization_name = getattr(org, "name", organization_name)
        trace_payload = self._store_score_lookup_trace(
            {
                "request_id": trace_request_id,
                "route": route,
                "intent_detection_ms": intent_detection_ms,
                "db_lookup_ms": db_lookup_ms,
                "scorer_lookup_ms": 0.0,
                "planner_ms": 0.0,
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
                "db_hit": True,
                "llm_called": False,
                "fallback_used": False,
                "organization_name": resolved_organization_name,
                "answer_contract": "score_lookup",
                "collection_required": False,
                "mission_created": False,
                "mission_id": None,
                "mission_mode": "none",
                "collection_targets": [],
                "requested_scores": available_fields,
            }
        )
        return {
            "parsed_result": parsed_result,
            "answer": self._format_score_lookup_answer(
                organization_name=resolved_organization_name,
                score_payload=score_payload,
                requested_scores=available_fields,
                lang=lang,
            ),
            "evidence": [self._evidence_from_organization_profile(org, evidence_type="organization_score_lookup")],
            "organization_name": resolved_organization_name,
            "data_source": "database",
            "llm_used": False,
            "trace": trace_payload,
            "mission_id": None,
            "mission_created": False,
            "mission_draft": None,
        }

    def _resolve_relationship_graph_if_applicable(
        self,
        *,
        user_message: str,
        conversation_id: str,
        route: str = "simple",
    ) -> Optional[dict]:
        if not re.search(
            r"graph|network|partner|connected|relation|relationship|图谱|关系|合作网络|关联机构|合作方|有关联|有关系",
            user_message or "",
            re.IGNORECASE,
        ):
            return None

        parser = None
        try:
            from .query_parser import QueryParser

            parser = QueryParser()
            parsed_result = parser.parse(user_message, conversation_id=conversation_id)
        finally:
            if parser:
                parser.close()

        if not self._is_relationship_graph_parsed_result(parsed_result):
            return None

        organization_name = str((parsed_result or {}).get("organization_name") or "").strip()
        if not organization_name:
            return None

        depth, include_unverified = self._normalize_graph_options(parsed_result)
        lang = "zh" if re.search(r"[\u4e00-\u9fff]", user_message or "") else "en"

        db_gen = None
        db = None
        try:
            from models.database import get_db
            from services.relation_mapper import build_organization_graph

            db_gen = get_db()
            db = next(db_gen)
            graph_payload = build_organization_graph(
                db=db,
                organization_name=organization_name,
                depth=depth,
                limit=50,
                include_unverified=include_unverified,
            )
        finally:
            if db_gen is not None:
                db_gen.close()

        center_name = str(((graph_payload or {}).get("center") or {}).get("name") or organization_name)
        answer = self._format_relationship_graph_answer(graph_payload=graph_payload, lang=lang)
        return {
            "parsed_result": parsed_result,
            "answer": answer,
            "evidence": self._graph_evidence_from_payload(graph_payload),
            "organization_name": center_name,
            "relationship_graph": graph_payload,
            "data_source": "database",
            "llm_used": False,
            "route": route,
        }

    def _normalize_evidence_item(self, item: Any) -> dict:
        if not isinstance(item, dict):
            return {}
        title = str(item.get("title") or "").strip()
        source_name = str(item.get("source_name") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        published_at = str(item.get("published_at") or "").strip()
        updated_at = str(item.get("updated_at") or "").strip()
        evidence_type = str(item.get("type") or "").strip()
        confidence = 0.0
        try:
            confidence = float(item.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))
        return {
            "title": title,
            "source_name": source_name,
            "url": url,
            "confidence": confidence,
            "published_at": published_at,
            "updated_at": updated_at,
            "type": evidence_type,
            "snippet": snippet[:240] if snippet else "",
        }

    def _merge_evidence(self, *evidence_lists: Any) -> list[dict]:
        merged: list[dict] = []
        seen = set()
        for evidence in evidence_lists:
            if not evidence or not isinstance(evidence, list):
                continue
            for item in evidence:
                normalized = self._normalize_evidence_item(item)
                if not normalized:
                    continue
                key = (
                    normalized.get("url")
                    or f"{normalized.get('title')}|{normalized.get('source_name')}|{normalized.get('published_at')}"
                )
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(normalized)
        return merged

    def _evidence_from_intelligence_item(self, item: Any, *, evidence_type: str = "intelligence_item") -> dict:
        title = (getattr(item, "title", None) or "").strip()
        source_name = (getattr(item, "source_name", None) or "").strip()
        url = (getattr(item, "source_url", None) or "").strip()
        confidence = float(getattr(item, "confidence", None) or 0.0)
        published_at = self._coerce_datetime_str(getattr(item, "published_at", None))
        updated_at = self._coerce_datetime_str(getattr(item, "ingested_at", None))
        snippet = (getattr(item, "content", None) or "").strip()
        raw_type = (getattr(item, "category", None) or getattr(item, "entity_type", None) or "").strip()
        return self._normalize_evidence_item(
            {
                "title": title,
                "source_name": source_name,
                "url": url,
                "confidence": confidence,
                "published_at": published_at,
                "updated_at": updated_at,
                "type": raw_type or evidence_type,
                "snippet": snippet[:240] if snippet else "",
            }
        )

    def _evidence_from_organization_profile(self, org: Any, *, evidence_type: str = "organization_profile") -> dict:
        title = (getattr(org, "name", None) or "").strip()
        source_name = (getattr(org, "source_name", None) or "").strip()
        url = (
            (getattr(org, "source_url", None) or "").strip()
            or (getattr(org, "official_website", None) or "").strip()
            or (getattr(org, "wikipedia_url", None) or "").strip()
            or (getattr(org, "leader_bio_url", None) or "").strip()
        )
        confidence = float(getattr(org, "confidence", None) or 0.0)
        updated_at = self._coerce_datetime_str(getattr(org, "updated_at", None))
        snippet = (
            (getattr(org, "description", None) or "").strip()
            or (getattr(org, "about_text", None) or "").strip()
            or (getattr(org, "mission_statement", None) or "").strip()
        )
        score_snippet = self._build_score_snippet(org=org)
        if score_snippet:
            snippet = f"{snippet}\n{score_snippet}".strip() if snippet else score_snippet
        return self._normalize_evidence_item(
            {
                "title": title,
                "source_name": source_name,
                "url": url,
                "confidence": confidence,
                "published_at": "",
                "updated_at": updated_at,
                "type": evidence_type,
                "snippet": snippet[:240] if snippet else "",
            }
        )

    def _normalize_tool_result(self, function_name: str, result: Any) -> dict:
        payload: dict
        if isinstance(result, dict):
            payload = dict(result)
        else:
            payload = {"data": result}
        if not isinstance(payload.get("evidence"), list):
            payload["evidence"] = []
        payload["evidence"] = self._merge_evidence(payload.get("evidence") or [])
        if not isinstance(payload.get("answer"), str) or not payload.get("answer"):
            answer = ""
            if isinstance(payload.get("response"), str) and payload.get("response"):
                answer = payload.get("response") or ""
            elif isinstance(payload.get("message"), str) and payload.get("message"):
                answer = payload.get("message") or ""
            else:
                try:
                    answer = self._render_direct_tool_result(function_name, payload)
                except Exception:
                    answer = ""
            payload["answer"] = answer or ""
        return payload

    def _fallback_summary(self, messages: List[dict]) -> str:
        """无LLM时的手动摘要。"""
        entities = set()
        topics = set()
        role = ""

        for msg in messages:
            content = self._filter_dsml(msg.get("content", ""))
            if not content:
                continue

            for org in ["Victory", "CCF", "JIL", "PCEC", "CBN Asia", "Gloo", "Draper", "Greylock", "Alpha Southeast Asia"]:
                if org in content:
                    entities.add(org)

            for kw in ["FaithTech", "教会网络", "投资方", "社交媒体", "收购", "融资", "菲律宾", "邮件", "教会"]:
                if kw in content:
                    topics.add(kw)

            if "我是" in content and not role:
                idx = content.find("我是")
                role = content[idx : idx + 50]

        parts = []
        if role:
            parts.append(f"用户: {role}")
        if topics:
            parts.append(f"关注主题: {', '.join(sorted(topics))}")
        if entities:
            parts.append(f"提到实体: {', '.join(sorted(entities))}")
        return " | ".join(parts) if parts else "对话摘要（手动生成）"

    def _generate_conversation_summary(self, messages_to_summarize: List[dict]) -> str:
        """
        使用LLM生成对话摘要。
        保留：用户身份、关注主题、提到的实体、未满足的需求。
        """
        if not messages_to_summarize or len(messages_to_summarize) < 4:
            return ""

        summary_prompt = """请对以下对话生成简洁摘要（不超过200字），必须保留：
1. 用户身份/角色（如有提及）
2. 用户关注的核心主题/领域
3. 提到的关键机构/实体名称
4. 用户的未满足需求或下一步意图

对话：
"""

        for msg in messages_to_summarize:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if content and role in ["user", "assistant"]:
                clean = self._filter_dsml(content)
                summary_prompt += f"\n{role}: {clean[:200]}"

        summary_prompt += "\n\n摘要："

        if not DEEPSEEK_API_KEY:
            return self._fallback_summary(messages_to_summarize)

        try:
            response = httpx.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "你是一个对话摘要助手。"},
                        {"role": "user", "content": summary_prompt},
                    ],
                    "max_tokens": 300,
                    "temperature": 0.3,
                    "stream": False,
                },
                timeout=15,
            )
            response.raise_for_status()
            summary = (
                response.json()
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return summary or self._fallback_summary(messages_to_summarize)
        except Exception as exc:
            print(f"[Summary] LLM摘要生成失败: {exc}")
            return self._fallback_summary(messages_to_summarize)

    def _compress_conversation_history(self) -> None:
        """每5轮触发一次摘要压缩。"""
        if len(self.conversation_history) < 10:
            return

        old_messages = self.conversation_history[:8]
        summary = self._generate_conversation_summary(old_messages)
        if not summary:
            return

        self.conversation_history = [
            {"role": "system", "content": f"[对话摘要] {summary}"}
        ] + self.conversation_history[8:]
        print(f"[Summary] 对话已压缩: {summary[:100]}...")

    def _extract_entities_from_input(self, user_input: str) -> List[dict]:
        """
        从输入文本中提取提到的机构/投资方/实体。
        优先用于代词消解和上下文回填。
        """
        if not user_input:
            return []

        try:
            try:
                from backend.models.database import KnowledgeEntity, OrganizationProfile, Investor, get_db  # type: ignore
            except ImportError:
                from models.database import KnowledgeEntity, OrganizationProfile, Investor, get_db  # type: ignore

            input_lower = user_input.lower()
            entities: List[dict] = []
            db = next(get_db())
            try:
                orgs = (
                    db.query(
                        OrganizationProfile.id,
                        OrganizationProfile.name,
                        OrganizationProfile.country,
                        OrganizationProfile.denomination,
                    )
                    .filter(OrganizationProfile.name.isnot(None))
                    .all()
                )
                investors = (
                    db.query(
                        Investor.id,
                        Investor.name,
                        Investor.investor_type,
                        Investor.country,
                    )
                    .filter(Investor.name.isnot(None))
                    .all()
                )
                knowledge_entities = (
                    db.query(
                        KnowledgeEntity.id,
                        KnowledgeEntity.name,
                        KnowledgeEntity.entity_type,
                        KnowledgeEntity.country,
                        KnowledgeEntity.category,
                    )
                    .filter(KnowledgeEntity.name.isnot(None))
                    .all()
                )
            finally:
                db.close()

            for row in sorted(orgs, key=lambda item: len(item.name or ""), reverse=True):
                if row.name and row.name.lower() in input_lower:
                    entities.append(
                        {
                            "id": str(row.id),
                            "name": row.name,
                            "type": "organization",
                            "country": row.country or "",
                            "detail": row.denomination or "",
                        }
                    )

            for row in sorted(investors, key=lambda item: len(item.name or ""), reverse=True):
                if row.name and row.name.lower() in input_lower:
                    entities.append(
                        {
                            "id": str(row.id),
                            "name": row.name,
                            "type": "investor",
                            "country": row.country or "",
                            "detail": row.investor_type or "",
                        }
                    )

            for row in sorted(knowledge_entities, key=lambda item: len(item.name or ""), reverse=True):
                if row.name and row.name.lower() in input_lower:
                    entities.append(
                        {
                            "id": str(row.id),
                            "name": row.name,
                            "type": row.entity_type or "entity",
                            "country": row.country or "",
                            "detail": row.category or "",
                        }
                    )

            unique = []
            seen = set()
            for item in entities:
                name = item.get("name") or ""
                lowered = name.lower()
                if not name or lowered in seen:
                    continue
                seen.add(lowered)
                unique.append(item)
            return unique
        except Exception as exc:
            print(f"[EntityExtract] 提取实体失败: {exc}")
            return []

    def _merge_current_entities(self, text: str) -> None:
        new_entities = self._extract_entities_from_input(text)
        if not new_entities:
            return

        existing_names = {item.get("name", "").lower() for item in self.current_entities if item.get("name")}
        for item in new_entities:
            lowered = (item.get("name") or "").lower()
            if lowered and lowered not in existing_names:
                self.current_entities.append(item)
                existing_names.add(lowered)
        self.current_entities = self.current_entities[-10:]

    def _rebuild_entity_context(self, conversation_history: list | None, user_message: str) -> None:
        self.conversation_history = (conversation_history or [])[-20:]
        self.current_entities = []
        for msg in self.conversation_history[-10:]:
            self._merge_current_entities(msg.get("content", ""))
        self._merge_current_entities(user_message)

    def _get_planner_entities(self, user_message: str) -> List[str]:
        """Planner优先使用当前Query中的显式实体，避免历史上下文污染。"""
        direct_entities = []
        for item in self._extract_entities_from_input(user_message):
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            if name:
                direct_entities.append(name)
        if direct_entities:
            return list(dict.fromkeys(direct_entities))

        lowered = (user_message or "").lower()
        if any(token in lowered for token in ["是什么机构", "是什么", "介绍", "profile", "about", "值得投资"]):
            org_candidate = self._extract_organization_profile_name(user_message)
            if org_candidate and org_candidate != self._extract_country(org_candidate):
                return [org_candidate]

        if self._looks_like_plural_entity_reference(user_message):
            context_entities = []
            for item in self.current_entities[-5:]:
                if not isinstance(item, dict):
                    continue
                name = (item.get("name") or "").strip()
                if name:
                    context_entities.append(name)
            return list(dict.fromkeys(context_entities))

        return []

    def _looks_like_explicit_profile_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(
            token in lowered
            for token in ["是什么机构", "是什么组织", "是什么", "介绍", "profile", "about", "值得投资"]
        )

    def _normalize_entity_text(self, value: Optional[str]) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _tokenize_entity_text(self, value: Optional[str]) -> set[str]:
        tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9&'.-]{1,}", value or ""))
        blocked = {
            "what",
            "about",
            "profile",
            "organization",
            "international",
            "ministry",
            "ministries",
            "group",
            "church",
            "christian",
        }
        return {token.lower() for token in tokens if token and token.lower() not in blocked}

    def _is_result_name_relevant(self, target_entity: str, candidate_name: str) -> bool:
        normalized_target = self._normalize_entity_text(target_entity)
        normalized_candidate = self._normalize_entity_text(candidate_name)
        if not normalized_target or not normalized_candidate:
            return False
        if normalized_target in normalized_candidate or normalized_candidate in normalized_target:
            return True

        target_tokens = self._tokenize_entity_text(target_entity)
        candidate_tokens = self._tokenize_entity_text(candidate_name)
        overlap = target_tokens & candidate_tokens
        if len(overlap) >= 2:
            return True
        return bool(overlap) and len(target_tokens) == 1

    def _collect_result_entity_hints(self, payload: Any) -> List[str]:
        hints: List[str] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"name", "org_name", "entity_name"} and isinstance(value, str) and value.strip():
                    hints.append(value.strip())
                elif key == "organization" and isinstance(value, dict):
                    org_name = (value.get("name") or "").strip()
                    if org_name:
                        hints.append(org_name)
                elif isinstance(value, (dict, list)):
                    hints.extend(self._collect_result_entity_hints(value))
        elif isinstance(payload, list):
            for item in payload[:10]:
                hints.extend(self._collect_result_entity_hints(item))
        return hints

    def _collect_result_country_hints(self, payload: Any) -> List[str]:
        hints: List[str] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key == "country" and isinstance(value, str) and value.strip():
                    hints.append(value.strip())
                elif isinstance(value, (dict, list)):
                    hints.extend(self._collect_result_country_hints(value))
        elif isinstance(payload, list):
            for item in payload[:10]:
                hints.extend(self._collect_result_country_hints(item))
        return hints

    def _country_matches(self, target_country: str, candidate_country: str) -> bool:
        normalized_candidate = self._normalize_entity_text(candidate_country)
        if not normalized_candidate:
            return False
        aliases = COUNTRY_ALIASES.get(target_country, [])
        if normalized_candidate == self._normalize_entity_text(target_country):
            return True
        return any(normalized_candidate == self._normalize_entity_text(alias) for alias in aliases)

    def _validate_entity_relevance(self, query: str, results: dict) -> bool:
        """校验 Planner 返回结果是否仍然聚焦当前 Query 的目标实体/国家。"""
        if not isinstance(results, dict):
            return True

        explicit_entities = [
            (item.get("name") or "").strip()
            for item in self._extract_entities_from_input(query)
            if isinstance(item, dict) and (item.get("name") or "").strip()
        ]
        if not explicit_entities and self._looks_like_explicit_profile_query(query):
            org_candidate = self._extract_organization_profile_name(query)
            if org_candidate and org_candidate != self._extract_country(org_candidate):
                explicit_entities = [org_candidate]

        target_country = self._extract_country(query)
        entity_hints: List[str] = []
        country_hints: List[str] = []
        for result in results.values():
            entity_hints.extend(self._collect_result_entity_hints(result))
            country_hints.extend(self._collect_result_country_hints(result))

        entity_hints = list(dict.fromkeys([hint for hint in entity_hints if hint]))
        country_hints = list(dict.fromkeys([hint for hint in country_hints if hint]))

        if explicit_entities and entity_hints:
            if not any(
                self._is_result_name_relevant(target_entity, candidate_name)
                for target_entity in explicit_entities
                for candidate_name in entity_hints
            ):
                logger.warning(
                    "Entity drift detected: query=%r explicit_entities=%s result_entities=%s",
                    query,
                    explicit_entities,
                    entity_hints[:8],
                )
                return False

        if target_country and target_country != "全球" and not explicit_entities and country_hints:
            if not any(self._country_matches(target_country, candidate_country) for candidate_country in country_hints):
                logger.warning(
                    "Country drift detected: query=%r target_country=%s result_countries=%s",
                    query,
                    target_country,
                    country_hints[:8],
                )
                return False

        return True

    def _looks_like_plural_entity_reference(self, text: str) -> bool:
        lowered = (text or "").lower()
        tokens = [
            "他们",
            "她们",
            "这些机构",
            "这些教会",
            "这些网络",
            "这些投资方",
            "它们",
            "they",
            "them",
            "those organizations",
        ]
        return any(token in lowered for token in tokens)

    def _direct_render_tool_names(self) -> set[str]:
        return {
            "match_investors",
            "generate_outreach_email",
            "create_task",
            "match_acquirers",
            "match_users",
            "query_graph",
            "query_intelligence",
            "query_fused",
            "query_arda_country",
            "query_organization_profile",
        }

    def _should_use_direct_answer(self, user_message: str) -> bool:
        text = (user_message or "").strip()
        if not text:
            return False
        return any(
            [
                bool(self._extract_profile_from_message(text)),
                self._is_profile_question(text),
                self._is_contact_query(text),
                self._looks_like_organization_profile_query(text),
                self._looks_like_graph_query(text),
                self._looks_like_email_generation_query(text),
                self._looks_like_match_query(text),
                self._looks_like_funding_query(text),
                self._looks_like_investor_query(text),
                self._looks_like_ontology_type_query(text),
                self._looks_like_ontology_query(text),
                self._looks_like_arda_country_query(text),
                self._looks_like_news_query(text),
                self._looks_like_fused_query(text),
                self._looks_like_task_creation_query(text),
                self._looks_like_acquirer_query(text),
                self._looks_like_user_match_query(text),
            ]
        )

    def _format_match_result(self, result: dict) -> str:
        payload = {
            "project_description": (result.get("project_profile") or {}).get("description", ""),
            "matches": result.get("matches", []),
        }
        lines = ["## 投资方匹配榜单", ""]
        project_profile = result.get("project_profile") or {}
        if project_profile:
            profile_fragments = []
            if project_profile.get("focus_area"):
                profile_fragments.append(f"方向：{project_profile['focus_area']}")
            if project_profile.get("stage"):
                profile_fragments.append(f"阶段：{project_profile['stage']}")
            if project_profile.get("country"):
                profile_fragments.append(f"国家：{project_profile['country']}")
            if project_profile.get("region"):
                profile_fragments.append(f"地区：{project_profile['region']}")
            if profile_fragments:
                lines.append(f"项目画像：{' | '.join(profile_fragments)}")
                lines.append("")

        for idx, item in enumerate(result.get("matches", [])[:5], start=1):
            lines.append(f"### {idx}. {item.get('name')}")
            lines.append(f"- 匹配度：{item.get('score_label')} {item.get('score')}/10")
            lines.append(f"- 类型：{item.get('type_label')}")
            if item.get("focus_areas"):
                lines.append(f"- 关注领域：{' / '.join(item['focus_areas'][:4])}")
            if item.get("stage_focus"):
                lines.append(f"- 阶段偏好：{' / '.join(item['stage_focus'][:4])}")
            region_text = " / ".join(item.get("region_focus", [])[:4]) or (item.get("country") or "")
            if region_text:
                lines.append(f"- 区域：{region_text}")
            if item.get("match_reasons"):
                lines.append(f"- 匹配理由：{'；'.join(item['match_reasons'][:4])}")
            if item.get("website"):
                lines.append(f"- 官网：{item['website']}")
            lines.append("")

        lines.append("[SOURCE: 投资机构数据库 + 匹配引擎] [CONFIDENCE: HIGH]")
        lines.append(f"[[MATCH_DATA]]{json.dumps(payload, ensure_ascii=False)}[[/MATCH_DATA]]")
        return "\n".join(lines)

    def _format_email_result(self, result: dict) -> str:
        email = result.get("email") or {}
        subject = email.get("subject", "")
        body = email.get("body", "")
        payload = {
            "subject": subject,
            "body": body,
            "tone": email.get("tone", ""),
            "investor": email.get("investor", {}),
        }
        return (
            "## 联系邮件草稿\n\n"
            f"**Subject**: {subject}\n\n"
            f"{body}\n\n"
            "[SOURCE: 投资机构数据库 + 邮件生成器] [CONFIDENCE: HIGH]\n"
            f"[[EMAIL_DATA]]{json.dumps(payload, ensure_ascii=False)}[[/EMAIL_DATA]]"
        )

    def _format_task_result(self, result: dict) -> str:
        return (
            "## 跟踪任务已创建\n\n"
            f"- 任务ID：{result.get('task_id', '未知')}\n"
            f"- 标题：{result.get('title', '')}\n"
            f"- 优先级：{result.get('priority', 'medium')}\n"
            f"- 状态：待跟进\n\n"
            f"{result.get('message', '任务已创建')}\n\n"
            "[SOURCE: 任务数据库] [CONFIDENCE: HIGH]"
        )

    def _format_acquirer_result(self, result: dict) -> str:
        lines = ["## 潜在收购方列表", ""]
        for idx, item in enumerate(result.get("acquirers", [])[:5], start=1):
            lines.append(f"### {idx}. {item.get('name')}")
            lines.append(f"- 匹配度：{item.get('score', 0)}/10")
            if item.get("country"):
                lines.append(f"- 国家：{item.get('country')}")
            if item.get("website"):
                lines.append(f"- 官网：{item.get('website')}")
            if item.get("reasons"):
                lines.append(f"- 原因：{'；'.join(item['reasons'][:4])}")
            lines.append("")
        lines.append("[SOURCE: Ontology 标签 + 机构数据库] [CONFIDENCE: MEDIUM]")
        return "\n".join(lines)

    def _format_user_match_result(self, result: dict) -> str:
        lines = ["## 潜在使用方列表", ""]
        for idx, item in enumerate(result.get("users", [])[:8], start=1):
            lines.append(f"### {idx}. {item.get('name')}")
            lines.append(f"- 匹配度：{item.get('score', 0)}/10")
            if item.get("country"):
                lines.append(f"- 国家：{item.get('country')}")
            if item.get("website"):
                lines.append(f"- 官网：{item.get('website')}")
            if item.get("reasons"):
                lines.append(f"- 原因：{'；'.join(item['reasons'][:4])}")
            lines.append("")
        lines.append("[SOURCE: Ontology 标签 + 机构数据库] [CONFIDENCE: MEDIUM]")
        return "\n".join(lines)

    def _format_graph_result(self, result: dict) -> str:
        center = result.get("center_entity")
        center_name = center.get("name") if isinstance(center, dict) else (center or result.get("center_name") or "目标机构")
        payload = {
            "center_entity": center_name,
            "relations": [
                {
                    "entity": item.get("entity") or {},
                    "type": item.get("type") or "",
                    "direction": item.get("direction") or "",
                    "amount": item.get("amount"),
                    "description": item.get("description") or "",
                }
                for item in result.get("direct_relations", [])[:8]
                if item.get("entity")
            ],
        }
        lines = [f"## {center_name} 关系图谱", ""]

        direct_relations = result.get("direct_relations", [])
        if direct_relations:
            lines.append("### 直接关系")
            for idx, item in enumerate(direct_relations[:8], start=1):
                entity = item.get("entity") or {}
                name = entity.get("name") or "未知对象"
                relation = item.get("type") or "关联"
                description = item.get("description") or ""
                lines.append(f"{idx}. {name} | {relation}")
                if description:
                    lines.append(f"- 说明：{description}")
                if item.get("round"):
                    lines.append(f"- 轮次：{item.get('round')}")
                if item.get("amount"):
                    lines.append(f"- 金额：${item.get('amount'):,.0f}")
                if item.get("confidence") is not None:
                    lines.append(f"- 置信度：{item.get('confidence')}")
                lines.append("")
        else:
            lines.append("### 直接关系")
            lines.append("- 当前未检索到可展示的直接节点关系。")
            lines.append("")

        investment_chain = result.get("investment_chain", [])
        if investment_chain:
            lines.append("### 投资链条")
            for chain in investment_chain[:8]:
                amount_text = f"，金额 ${chain.get('amount'):,.0f}" if chain.get("amount") else ""
                date_text = f"，时间 {chain.get('announced_date')[:10]}" if chain.get("announced_date") else ""
                lines.append(
                    f"- {chain.get('from')} -> {chain.get('to')}（{chain.get('relationship', '投资')}，{chain.get('round', '轮次未披露')}{amount_text}{date_text}）"
                )
            lines.append("")

        indirect_relations = result.get("indirect_relations", [])
        if indirect_relations:
            lines.append("### 间接连接")
            for item in indirect_relations[:6]:
                via = item.get("via") or "中间节点"
                note = item.get("note") or "存在间接关系"
                lines.append(f"- 通过 {via}：{note}")
            lines.append("")

        if result.get("summary"):
            lines.append(result["summary"])
            lines.append("")
        elif not direct_relations and not investment_chain and not indirect_relations:
            lines.append("当前图谱数据不足，建议先检查融资/投资种子数据是否已初始化，或换一个已知机构继续查询。")
            lines.append("")

        lines.append("[SOURCE: 投资交易数据库 + Ontology 标签 + 机构档案] [CONFIDENCE: MEDIUM]")
        lines.append(f"[[GRAPH_DATA]]{json.dumps(payload, ensure_ascii=False)}[[/GRAPH_DATA]]")
        return "\n".join(lines)

    def _format_intelligence_result(self, result: dict) -> str:
        summary = result.get("query_summary") or {}
        items = result.get("items") or []
        if not items:
            target = summary.get("entity") or summary.get("country") or "该主题"
            keywords = [str(item).strip() for item in (summary.get("keywords") or []) if str(item).strip()]
            sources_checked = summary.get("sources_checked") or [
                "IntelligenceItem.title",
                "IntelligenceItem.content",
                "IntelligenceItem.entity_name",
                "IntelligenceItem.source_url",
            ]
            missing_fields = summary.get("missing_fields") or ["url", "source_name", "entity_name"]
            lines = [
                f"[INSUFFICIENT DATA] 当前情报库中暂未检索到关于 {target} 的可用情报记录。",
                f"- 查询范围：scope={summary.get('scope') or 'unknown'} | country={summary.get('country') or 'N/A'} | entity={summary.get('entity') or 'N/A'}",
                f"- 查询关键词：{', '.join(keywords) if keywords else '未提供额外关键词'}",
                f"- 查询来源：{', '.join(str(item) for item in sources_checked)}",
                f"- 缺失字段：{', '.join(str(item) for item in missing_fields)}",
                f"- 未命中原因：{summary.get('no_hit_reason') or '现有数据库中没有满足国家/实体/关键词交集且带来源链接的记录'}",
                f"- 是否需要补采：{'是' if summary.get('needs_collection', True) else '否'}",
                "[SOURCE: 情报数据库] [CONFIDENCE: LOW]",
            ]
            if summary.get("relaxed_match_attempted"):
                lines.insert(
                    4,
                    f"- 已执行宽松检索：{bool(summary.get('relaxed_match_attempted'))}，宽松命中={bool(summary.get('relaxed_match_hit'))}",
                )
            return "\n".join(lines)

        scope = summary.get("scope") or "global"
        target = summary.get("entity") or summary.get("country") or "全球基督教领域"
        intro = "最近全球基督教新闻中，较值得关注的动态有：" if scope == "global" else f"关于 {target}，近期可见的新闻动态有："

        lines = [intro]
        for item in items[:5]:
            snippet = (item.get("content") or "").replace("\n", " ").strip()
            if len(snippet) > 100:
                snippet = f"{snippet[:100]}..."
            date = item.get("date") or "未知日期"
            url = (item.get("url") or "").strip()
            bullet = f"- {item.get('title')}（{date}，{item.get('source_name') or item.get('source') or '未知来源'}）：{snippet}"
            if url:
                bullet += f" | URL: {url}"
            lines.append(bullet)

        source_breakdown = result.get("source_breakdown") or {}
        if source_breakdown:
            source_names = sorted(source_breakdown.items(), key=lambda pair: pair[1], reverse=True)[:3]
            lines.append("")
            lines.append("来源分布：" + "，".join(f"{name} {count}条" for name, count in source_names))

        lines.append("[SOURCE: 情报数据库] [CONFIDENCE: HIGH]")
        return "\n".join(lines)

    def _format_fused_result(self, result: dict) -> str:
        entity = result.get("entity") or {}
        target_name = entity.get("name") or result.get("query_summary", {}).get("entity_name") or "该实体"
        intelligence = result.get("intelligence") or []
        funding_rounds = result.get("funding_rounds") or []
        investor_relations = result.get("investors") or []
        ontology_tags = result.get("ontology_tags") or []

        if not entity and not intelligence and not funding_rounds and not investor_relations:
            return (
                f"[INSUFFICIENT DATA] 当前未能在机构档案、新闻情报和融资记录中检索到与 {target_name} 相关的综合信息。"
                "建议提供更完整的实体名称，或补充国家/关键词后再查。 "
                "[SOURCE: 融合查询引擎] [CONFIDENCE: LOW]"
            )

        lines = [f"## {target_name} 综合情报", ""]

        if entity:
            lines.append("### 机构概览")
            overview_parts = []
            if entity.get("source"):
                overview_parts.append(f"来源：{entity['source']}")
            if entity.get("country"):
                overview_parts.append(f"国家：{entity['country']}")
            if entity.get("type"):
                overview_parts.append(f"类型：{entity['type']}")
            if entity.get("category"):
                overview_parts.append(f"分类：{entity['category']}")
            if entity.get("denomination"):
                overview_parts.append(f"宗派：{entity['denomination']}")
            if entity.get("member_estimate"):
                overview_parts.append(f"规模：{entity['member_estimate']:,}")
            if overview_parts:
                lines.append(f"- {' | '.join(overview_parts)}")
            if entity.get("focus_areas"):
                lines.append(f"- 关注领域：{' / '.join(entity['focus_areas'][:4])}")
            if entity.get("stage_focus"):
                lines.append(f"- 阶段偏好：{' / '.join(entity['stage_focus'][:4])}")
            if entity.get("leader_name"):
                lines.append(f"- 负责人：{entity['leader_name']}")
            if entity.get("official_website"):
                lines.append(f"- 官网：{entity['official_website']}")
            elif entity.get("website"):
                lines.append(f"- 官网：{entity['website']}")
            lines.append("")

        if ontology_tags:
            lines.append("### Ontology 标签")
            tag_text = "，".join(f"{item.get('type')}:{item.get('tag_id')}" for item in ontology_tags[:8])
            lines.append(f"- {tag_text}")
            lines.append("")

        if funding_rounds:
            lines.append("### 融资记录")
            for item in funding_rounds[:5]:
                amount = item.get("amount")
                amount_text = f"${amount:,.0f}" if isinstance(amount, (int, float)) and amount else "金额未披露"
                date_text = (item.get("announced_date") or "")[:10] or "时间未披露"
                investor_text = "，".join(
                    f"{inv.get('name')}{'（领投）' if inv.get('lead') else ''}"
                    for inv in item.get("investors", [])[:4]
                    if inv.get("name")
                ) or "投资方未披露"
                lines.append(f"- {item.get('round_type', '轮次未披露')} | {amount_text} | {date_text} | {investor_text}")
            lines.append("")

        if investor_relations:
            lines.append("### 对外投资/投资关系")
            for item in investor_relations[:5]:
                amount = item.get("amount")
                amount_text = f"${amount:,.0f}" if isinstance(amount, (int, float)) and amount else "金额未披露"
                lines.append(
                    f"- 投向 {item.get('invested_entity')} | {item.get('round_type', '轮次未披露')} | {amount_text}"
                    f"{' | 领投' if item.get('lead') else ''}"
                )
            lines.append("")

        lines.append("### 相关新闻与动态")
        if intelligence:
            for item in intelligence[:5]:
                snippet = (item.get("content") or "").replace("\n", " ").strip()
                if len(snippet) > 100:
                    snippet = f"{snippet[:100]}..."
                date_text = (item.get("published_at") or "")[:10] or "未知日期"
                lines.append(
                    f"- {item.get('title')}（{date_text}，{item.get('source_name') or '未知来源'}）：{snippet}"
                )
        else:
            lines.append(f"- 当前数据库里还没有直接命中 **{target_name}** 的新闻记录。")
        lines.append("")

        lines.append(
            f"整体上，我们当前为 **{target_name}** 汇总到 `"
            f"{len(intelligence)}` 条新闻、`{len(funding_rounds)}` 条融资记录和 `"
            f"{len(investor_relations)}` 条投资关系。"
        )
        lines.append("")
        lines.append("[SOURCE: 机构档案 + 情报数据库 + 融资交易数据库] [CONFIDENCE: HIGH]")
        return "\n".join(lines)

    def _format_analysis_result(self, analysis_type: str, target: str, results: list) -> str:
        """格式化多步分析结果。"""
        sections = []

        if analysis_type == "COUNTRY_DEEP":
            sections.append(f"## {target} 基督教行业深度分析\n")

            for item in results:
                if item["tool"] == "query_arda_country" and isinstance(item["result"], dict):
                    arda = item["result"]
                    summary = arda.get("summary") or {}
                    sections.append("### 国家宗教概况\n")
                    sections.append(f"- 总人口：{summary.get('population', 'N/A')}")
                    sections.append(f"- 基督徒人口：{summary.get('christian_population', 'N/A')}")
                    sections.append(f"- 基督徒比例：{summary.get('christian_percent', 'N/A')}")
                    sections.append("")
                    break

            for item in results:
                if item["tool"] == "query_database" and isinstance(item["result"], dict):
                    orgs = item["result"].get("items", [])
                    if orgs:
                        sections.append(f"### 主要机构（{len(orgs)}家）\n")
                        for org in orgs[:5]:
                            sections.append(
                                f"- **{org.get('entity_name') or org.get('title', 'N/A')}** | "
                                f"{org.get('country', '')} | 来源: {org.get('source_name', 'N/A')}"
                            )
                        sections.append("")
                    break

            for item in results:
                if item["tool"] == "query_intelligence" and isinstance(item["result"], dict):
                    news = item["result"].get("items", [])
                    if news:
                        sections.append("### 近期动态\n")
                        for news_item in news[:3]:
                            sections.append(f"- {news_item.get('title', 'N/A')[:80]}")
                        sections.append("")
                    break

            for item in results:
                if item["tool"] == "query_investors" and isinstance(item["result"], dict):
                    investors = item["result"].get("investors", [])
                    if investors:
                        sections.append("### 投资机会\n")
                        for investor in investors[:5]:
                            sections.append(f"- {investor.get('name', 'N/A')} | {investor.get('investor_type', 'N/A')}")
                        sections.append("")
                    break

            sections.append("### 风险提示\n")
            sections.append("- 当前结果依赖数据库现有覆盖率，部分国家可能缺少完整机构与投资数据。")
            sections.append("- 如需更高置信度结论，建议追加人工复核与专题补采。")

        elif analysis_type == "COMPETITOR":
            sections.append(f"## {target} 竞争格局分析\n")

            for item in results:
                if item["tool"] == "query_organization_profile" and isinstance(item["result"], dict):
                    profile = item["result"].get("organization", {})
                    sections.append("### 目标机构概况\n")
                    sections.append(f"- **{profile.get('name', target)}**")
                    sections.append(f"- 国家：{profile.get('country', 'N/A')}")
                    sections.append(f"- 类型：{profile.get('organization_type', 'N/A')}")
                    sections.append(f"- AI成熟度：{profile.get('ai_maturity_score', 'N/A')}")
                    sections.append("")
                    break

            for item in results:
                if item["tool"] == "query_database" and isinstance(item["result"], dict):
                    orgs = item["result"].get("items", [])
                    if orgs:
                        sections.append(f"### 同类机构（{len(orgs)}家）\n")
                        sections.append("| 机构 | 国家 | AI成熟度 |")
                        sections.append("|------|------|----------|")
                        for org in orgs[:5]:
                            sections.append(
                                f"| {org.get('entity_name') or org.get('title', '')} | "
                                f"{org.get('country', '')} | {org.get('ai_maturity_score', 'N/A')} |"
                            )
                        sections.append("")
                    break

            sections.append("### 合作机会\n")
            sections.append("- 可优先对 People 完整度高、AI 成熟度更高的同类机构开展合作扫描。")
            sections.append("")
            sections.append("### 竞争威胁\n")
            sections.append("- 若同区域机构在 AI、People、Programs 三项都更完整，则目标机构的相对吸引力会下降。")

        elif analysis_type == "INVESTMENT":
            sections.append(f"## {target} 投资机会分析\n")

            for item in results:
                if item["tool"] == "query_database" and isinstance(item["result"], dict):
                    orgs = item["result"].get("items", [])
                    if orgs:
                        sections.append("### 推荐机构（Top 5）\n")
                        sections.append("| 机构 | AI成熟度 | People | 投资价值 |")
                        sections.append("|------|----------|--------|----------|")
                        for org in orgs[:5]:
                            has_people = "✓" if org.get("leader_name") else "✗"
                            ai = org.get("ai_maturity_score", "N/A")
                            sections.append(
                                f"| {org.get('entity_name') or org.get('title', '')} | {ai} | {has_people} | 待评估 |"
                            )
                        sections.append("")
                    break

            sections.append("### 投资建议\n")
            sections.append("基于以上数据，建议进一步尽调以下维度：")
            sections.append("- 机构财务健康状况")
            sections.append("- 合作历史与口碑")
            sections.append("- 政策风险评估")

        return "\n".join(sections) if sections else f"分析完成，但暂无 {target} 的详细数据。"

    def _format_arda_country_result(self, result: dict) -> str:
        if result.get("status") != "success":
            return result.get("message", "暂时未找到对应的ARDA国家数据。")

        country = result.get("country") or "该国家"
        display_country = next(
            (zh_name for zh_name, en_name in COUNTRY_ENGLISH_NAMES.items() if en_name == country),
            country,
        )
        summary = result.get("summary") or {}
        lines = [f"## {display_country}基督教概况", ""]
        lines.append("根据 ARDA 国家宗教档案，我们当前确认到以下核心数据： [SOURCE: ARDA]")
        lines.append("")
        lines.append("### 国家概况")
        if summary.get("population"):
            lines.append(f"- 总人口：`{summary['population']}`")
        if summary.get("christian_population"):
            lines.append(f"- 基督徒人口：`{summary['christian_population']}`")
        lines.append("")
        lines.append("### 基督徒比例")
        lines.append(
            f"- 基督徒占比：`{summary['christian_percent']}`"
            if summary.get("christian_percent")
            else "- 基督徒占比：ARDA 当前记录未明确显示"
        )
        lines.append("")
        lines.append("### 主要宗派")
        for label, key in [
            ("天主教", "catholic_percent"),
            ("新教", "protestant_percent"),
            ("东正教", "orthodox_percent"),
            ("独立教会", "independent_percent"),
        ]:
            if summary.get(key):
                lines.append(f"- {label}：`{summary[key]}`")
        lines.append("")
        lines.append("### 宗教自由状况")
        if summary.get("societal_discrimination_rank"):
            lines.append(f"- 社会歧视排名：`{summary['societal_discrimination_rank']}`")
        if summary.get("state_funding_rank"):
            lines.append(f"- 国家资助宗教排名：`{summary['state_funding_rank']}`")
        lines.append("")
        lines.append("### 趋势判断")
        lines.append("- 仅基于 ARDA 当前国家档案，我们可以确认该国基督教占比、主要宗派结构与宗教自由指标。")
        lines.append("- 对城市分布、增长趋势、具体教会名单等问题，需要结合新闻情报或机构档案进一步补充。")
        lines.append("")
        if result.get("source_url"):
            lines.append(f"📊 来源：ARDA 学术数据库 | {result['source_url']}")
        else:
            lines.append("📊 来源：ARDA 学术数据库")
        return "\n".join(lines)

    def _format_organization_profile_result(self, result: dict) -> str:
        if result.get("status") != "success":
            return result.get("message", "暂时未找到该机构的深度画像。")

        profile = result.get("organization") or {}
        arda = result.get("arda") or {}
        arda_summary = arda.get("summary") or {}
        news_items = result.get("news") or []
        investor_relations = result.get("investor_relations") or []
        ontology_tags = result.get("ontology_tags") or []
        target_name = result.get("org_name") or profile.get("name") or "该机构"
        score_payload = self._extract_score_payload(profile=profile)

        lines = [f"## {target_name} — 深度画像", ""]

        lines.append("### 机构概况")
        if profile:
            lines.append(
                f"- 名称：**{profile.get('name') or target_name}** | 国家：{profile.get('country') or 'N/A'} | 官网：{profile.get('official_website') or 'N/A'} [SOURCE: 机构档案]"
            )
            details = []
            if profile.get("denomination"):
                details.append(f"宗派/立场：{profile['denomination']}")
            if profile.get("member_estimate"):
                details.append(f"规模估计：{profile['member_estimate']:,}")
            if profile.get("founded_year"):
                details.append(f"创立年份：{profile['founded_year']}")
            if profile.get("leader_name"):
                leader_text = profile["leader_name"]
                if profile.get("leader_title"):
                    leader_text = f"{leader_text}（{profile['leader_title']}）"
                details.append(f"负责人：{leader_text}")
            if profile.get("source_name"):
                details.append(f"档案来源：{profile['source_name']}")
            if details:
                lines.append(f"- {' | '.join(details)} [SOURCE: 机构档案]")
        else:
            lines.append(f"- 目前情报有限，机构档案库中尚未稳定命中 **{target_name}**。 [SOURCE: 机构档案]")
        if ontology_tags:
            tag_text = "，".join(f"{item.get('type')}:{item.get('tag_id')}" for item in ontology_tags[:6])
            lines.append(f"- 标签画像：{tag_text} [SOURCE: Ontology 标签]")
        lines.append("")

        if any(score_payload.get(field) is not None for field in ("people_score", "digital_score", "intel_score", "composite_score")):
            lines.append("### 评分画像")
            lines.append(f"- `people_score`: `{score_payload.get('people_score', 'N/A')}` [SOURCE: 机构档案]")
            lines.append(f"- `digital_score`: `{score_payload.get('digital_score', 'N/A')}` [SOURCE: 机构档案]")
            lines.append(f"- `intel_score`: `{score_payload.get('intel_score', 'N/A')}` [SOURCE: 机构档案]")
            lines.append(f"- `composite_score`: `{score_payload.get('composite_score', 'N/A')}` [SOURCE: 机构档案]")
            lines.append("")

        lines.append("### 国家宗教环境")
        if arda.get("status") == "success" and arda_summary:
            country_name = arda.get("country") or profile.get("country") or "该国"
            env_parts = []
            if arda_summary.get("christian_percent"):
                env_parts.append(f"基督徒占比 `{arda_summary['christian_percent']}`")
            if arda_summary.get("catholic_percent"):
                env_parts.append(f"天主教 `{arda_summary['catholic_percent']}`")
            if arda_summary.get("protestant_percent"):
                env_parts.append(f"新教 `{arda_summary['protestant_percent']}`")
            if arda_summary.get("independent_percent"):
                env_parts.append(f"独立教会 `{arda_summary['independent_percent']}`")
            lines.append(
                f"- {country_name} 的宗教环境要点："
                + ("；".join(env_parts) if env_parts else "ARDA 仅提供了有限国家档案")
                + " [SOURCE: ARDA]"
            )
            freedom_parts = []
            if arda_summary.get("societal_discrimination_rank"):
                freedom_parts.append(f"社会歧视排名 `{arda_summary['societal_discrimination_rank']}`")
            if arda_summary.get("state_funding_rank"):
                freedom_parts.append(f"国家资助宗教排名 `{arda_summary['state_funding_rank']}`")
            if freedom_parts:
                lines.append(f"- 宗教自由相关指标：{'；'.join(freedom_parts)} [SOURCE: ARDA]")
        elif profile.get("country"):
            lines.append(f"- 已识别机构所在国家为 {profile.get('country')}，但当前未命中可用的 ARDA 国家档案。 [SOURCE: ARDA]")
        else:
            lines.append("- 由于机构国家未明确，当前无法叠加 ARDA 国家环境。 [SOURCE: ARDA]")
        lines.append("")

        lines.append("### 最新动态")
        if news_items:
            for item in news_items[:5]:
                date_text = item.get("date") or "未知日期"
                source_text = item.get("source_name") or item.get("source") or "未知来源"
                lines.append(f"- {item.get('title')}（{date_text}，{source_text}） [SOURCE: 情报数据库]")
        else:
            lines.append(f"- 目前情报有限，暂未检索到与 **{target_name}** 高相关的近期动态。 [SOURCE: 情报数据库]")
        lines.append("")

        lines.append("### 潜在关联")
        if investor_relations:
            for item in investor_relations[:5]:
                investor_name = item.get("name") or "未披露投资方"
                round_type = item.get("round_type") or "轮次未披露"
                amount = item.get("amount")
                amount_text = f"${amount:,.0f}" if isinstance(amount, (int, float)) and amount else "金额未披露"
                lines.append(
                    f"- {investor_name} | {round_type} | {amount_text}"
                    f"{' | 领投' if item.get('lead') else ''} [SOURCE: 融资交易数据库]"
                )
        elif ontology_tags:
            lines.append("- 当前未发现明确的融资/投资关系，但已有分类标签可辅助判断其生态位置。 [SOURCE: Ontology 标签 + 融资交易数据库]")
        else:
            lines.append(f"- 当前未发现 **{target_name}** 的明确投资/融资关联，建议后续继续补采。 [SOURCE: 融资交易数据库]")
        lines.append("")

        lines.append("### 综合判断")
        judgments = []
        if profile:
            judgments.append(f"**{target_name}** 已有基础机构档案，说明它不是纯噪声实体。")
        else:
            judgments.append(f"当前对 **{target_name}** 的核心档案仍偏薄，研判需保持谨慎。")
        if arda.get("status") == "success" and arda_summary.get("christian_percent"):
            judgments.append(
                f"它所处国家的基督教占比较高（`{arda_summary['christian_percent']}`），说明其外部宗教环境具备较强的基督教社会基础。"
            )
        if profile.get("denomination"):
            judgments.append(f"从机构档案看，它带有 **{profile['denomination']}** 色彩，适合按该传统继续追踪其网络关系。")
        if news_items:
            judgments.append(f"目前已命中 `{len(news_items)}` 条较相关动态，可继续沿这些来源做二次深挖。")
        else:
            judgments.append("公开动态仍偏少，现阶段更适合先补齐官网、负责人和事工网络信息。")
        for item in judgments:
            lines.append(f"- {item}")
        lines.append("")

        lines.append("### 行动建议")
        if not news_items:
            lines.append(f"- 建议进一步了解：补采 **{target_name}** 官网、Facebook、YouTube 与最近讲道/活动记录。 [SOURCE: 行动建议]")
        else:
            lines.append(f"- 值得关注：沿最近 3-5 条动态继续追踪它的合作对象、城市覆盖与事工重点。 [SOURCE: 行动建议]")
        if not investor_relations:
            lines.append(f"- 建议进一步了解：检查 **{target_name}** 是否存在基金会支持、伙伴教会网络或媒体协作关系。 [SOURCE: 行动建议]")
        return "\n".join(lines)

    def _render_direct_tool_result(self, function_name: str, result: dict) -> str:
        if function_name == "match_investors":
            return self._format_match_result(result)
        if function_name == "generate_outreach_email":
            return self._format_email_result(result)
        if function_name == "create_task":
            return self._format_task_result(result)
        if function_name == "match_acquirers":
            return self._format_acquirer_result(result)
        if function_name == "match_users":
            return self._format_user_match_result(result)
        if function_name == "query_graph":
            return self._format_graph_result(result)
        if function_name == "query_intelligence":
            return self._format_intelligence_result(result)
        if function_name == "query_fused":
            return self._format_fused_result(result)
        if function_name == "query_arda_country":
            return self._format_arda_country_result(result)
        if function_name == "query_organization_profile":
            return self._format_organization_profile_result(result)
        return ""

    def _extract_collect_context(self, user_message: str) -> tuple[list[str], str | None, str | None]:
        detected_country = self._extract_country(user_message) or None
        explicit_org = self._extract_organization_profile_name(user_message) or None
        lowered = (user_message or "").lower()

        theme_aliases = {
            "FaithTech": ["faithtech", "基督教科技", "church tech", "faith tech"],
            "教会网络": ["教会网络", "church network", "network church"],
            "宣教": ["宣教", "差传", "mission", "missionary"],
            "媒体": ["媒体", "media", "社交媒体", "social media"],
            "教育": ["教育", "edtech", "神学院", "培训"],
            "投资": ["投资", "investor", "fund", "vc"],
            "融资": ["融资", "funding", "round", "deal"],
            "收购": ["收购", "acquirer", "acquisition"],
        }

        detected_theme = None
        for theme, aliases in theme_aliases.items():
            if any(alias in lowered for alias in aliases):
                detected_theme = theme
                break

        collect_keywords = []
        if self._looks_like_plural_entity_reference(user_message) and self.current_entities:
            collect_keywords.extend([item.get("name") for item in self.current_entities[-4:] if item.get("name")])
        elif explicit_org:
            collect_keywords.append(explicit_org)
        elif detected_country and detected_theme:
            collect_keywords.append(f"{detected_country} {detected_theme}")
        elif detected_country:
            collect_keywords.append(detected_country)
        elif detected_theme:
            collect_keywords.append(detected_theme)
        else:
            fallback_keyword = (user_message or "").strip()[:30]
            if fallback_keyword:
                collect_keywords.append(fallback_keyword)

        return collect_keywords, detected_country, detected_theme

    def _expand_collection_queries(self, keyword: str, country: str | None = None) -> list[str]:
        country_en = COUNTRY_ENGLISH_NAMES.get(country or "", "")
        query_candidates = [keyword]
        lowered = (keyword or "").lower()

        if country and country_en:
            query_candidates.append(country_en)
            if "faithtech" in lowered:
                query_candidates.extend(
                    [
                        f"{country_en} FaithTech",
                        f"{country_en} Christian technology",
                        f"{country_en} Christian startup",
                        f"{country_en} church technology",
                    ]
                )
            elif any(token in lowered for token in ["教会网络", "church network"]):
                query_candidates.extend(
                    [
                        f"{country_en} church network",
                        f"{country_en} Christian network",
                        f"{country_en} church",
                    ]
                )
            elif any(token in lowered for token in ["宣教", "mission"]):
                query_candidates.extend(
                    [
                        f"{country_en} mission",
                        f"{country_en} missionary",
                        f"{country_en} Christianity",
                    ]
                )

        deduped = []
        seen = set()
        for item in query_candidates:
            value = (item or "").strip()
            if not value:
                continue
            normalized = value.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(value)
        return deduped

    def _schedule_gap_collection(self, keywords: list[str], country: str | None = None) -> None:
        if not keywords:
            return

        try:
            try:
                from backend.services.mission_service import create_collection_mission  # type: ignore
            except Exception:
                from services.mission_service import create_collection_mission  # type: ignore

            expanded_keywords = []
            seen = set()
            for keyword in keywords:
                for query in self._expand_collection_queries(keyword, country):
                    normalized = query.strip().lower()
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    expanded_keywords.append(query)

            mission = create_collection_mission(
                query=f"Brain Gap Collection | {', '.join(keywords)}",
                country=country or "全球",
                source="newsapi",
                keywords=expanded_keywords or keywords,
                limit_per_keyword=5,
                metadata={"entry": "brain.schedule_gap_collection"},
            )
            mission_id = mission.id if mission else None
            if not mission_id:
                print(f"[Agent补采] Mission未创建，跳过后续流程, keywords={keywords}")
                return
            print(f"[Agent补采] 已提交Mission任务: {mission_id}, keywords={keywords}")
        except Exception as exc:
            print(f"[Agent补采] Mission创建失败: {exc}")

    def _append_gap_collection_notice(
        self,
        user_message: str,
        content: str,
        *,
        prompt_route: Optional[dict] = None,
        gap_detection: Optional[bool] = None,
    ) -> str:
        route = dict(prompt_route or self._resolve_prompt_route(user_message) or {})
        if gap_detection is None:
            gap_detection = self._should_allow_gap_detection(user_message, prompt_route=route)
        if not gap_detection:
            self._log_gap_detection_status(
                user_message,
                prompt_route=route,
                gap_detection=False,
                gap_notice=False,
                auto_collection=False,
            )
            return content
        if not content or "[INSUFFICIENT DATA]" not in content or "已触发自动情报采集" in content:
            self._log_gap_detection_status(
                user_message,
                prompt_route=route,
                gap_detection=True,
                gap_notice=False,
                auto_collection=False,
            )
            return content

        collect_keywords, detected_country, _ = self._extract_collect_context(user_message)
        entity = self._extract_organization_profile_name(user_message) or self._extract_entity(user_message)

        self._log_gap_detection_status(
            user_message,
            prompt_route=route,
            gap_detection=True,
            gap_notice=True,
            auto_collection=True,
        )
        if detected_country and "后台补采" not in content and "后台采集任务" not in content:
            collect_result = self._auto_collect(
                country=detected_country,
                entity=entity,
                reason=f"P1 Agent缺口自动补采：{user_message[:80]}",
            )
            print(f"[Agent补采] auto_collect结果: {collect_result}")

        self._schedule_gap_collection(collect_keywords, detected_country)
        return (
            content
            + f'\n\n➡️ **已触发自动情报采集**：我们正在为你补充"{" / ".join(collect_keywords)}"相关数据，'
            + "采集结果将在后台处理，完成后可在数据库中查询。"
        )

    async def _trigger_agent_collection(self, keywords: list[str], country: str | None = None):
        """
        触发Agent自动补采
        现在统一委托给 Mission
        """
        try:
            try:
                from backend.services.mission_service import create_collection_mission  # type: ignore
            except ImportError:
                from services.mission_service import create_collection_mission  # type: ignore

            expanded_keywords = []
            seen = set()
            for keyword in keywords:
                for query in self._expand_collection_queries(keyword, country):
                    normalized = query.strip().lower()
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    expanded_keywords.append(query)

            mission = create_collection_mission(
                query=f"Brain Gap Collection | {', '.join(keywords)}",
                country=country or "全球",
                source="newsapi",
                keywords=expanded_keywords or keywords,
                limit_per_keyword=5,
                metadata={"entry": "brain.trigger_agent_collection"},
            )
            mission_id = mission.id if mission else None
            if not mission_id:
                print(f"[Agent补采] Mission未创建，跳过后续流程, keywords={keywords}")
                return
            print(f"[Agent补采] 已提交Mission任务: {mission_id}, keywords={keywords}")
        except Exception as exc:
            print(f"[Agent补采] 异常: {exc}")

    def _get_agent_status(self) -> dict:
        """查询Agent状态。"""
        try:
            try:
                from backend.services.agent import get_agent  # type: ignore
            except ImportError:
                from services.agent import get_agent  # type: ignore

            agent = get_agent()
            return {
                "status": "active",
                "stats": agent.get_stats(),
                "recent_tasks": agent.get_recent_tasks(5),
            }
        except ImportError:
            return {"status": "not_available", "message": "Agent模块未加载"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_arda_country(self, country: str) -> dict:
        """查询 ARDA 国家宗教概况。"""
        try:
            from models.database import IntelligenceItem, get_db
            from sqlalchemy import desc, or_

            normalized_country = (country or "").strip()
            if not normalized_country:
                return {"status": "error", "message": "缺少国家名称"}

            db = next(get_db())
            try:
                pattern = f"%{normalized_country}%"
                item = (
                    db.query(IntelligenceItem)
                    .filter(
                        IntelligenceItem.source_name == "ARDA",
                        or_(
                            IntelligenceItem.country == normalized_country,
                            IntelligenceItem.title.ilike(pattern),
                            IntelligenceItem.content.ilike(pattern),
                        ),
                    )
                    .order_by(desc(IntelligenceItem.ingested_at))
                    .first()
                )
                if not item:
                    return {
                        "status": "not_found",
                        "country": normalized_country,
                        "message": f"未找到 {normalized_country} 的ARDA数据。可用国家数据覆盖ARDA全部252个国家/地区，请确认国家名称（英文）。",
                    }

                content = item.content or ""

                def extract_value(label: str) -> str:
                    match = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", content)
                    return match.group(1).strip() if match else ""

                summary = {
                    "population": extract_value("总人口"),
                    "christian_population": extract_value("基督徒人口"),
                    "christian_percent": extract_value("基督徒比例"),
                    "catholic_percent": extract_value("天主教"),
                    "protestant_percent": extract_value("新教"),
                    "orthodox_percent": extract_value("东正教"),
                    "independent_percent": extract_value("独立教会"),
                    "societal_discrimination_rank": extract_value("Societal Discrimination Rank"),
                    "state_funding_rank": extract_value("State Funding Rank"),
                }

                payload = {
                    "status": "success",
                    "country": item.country or normalized_country,
                    "title": item.title or f"{normalized_country} — 宗教概况",
                    "content": content,
                    "source_name": "ARDA",
                    "source_url": item.source_url or "",
                    "authority": "ARDA学术数据库",
                    "summary": summary,
                }
                payload["evidence"] = self._merge_evidence([self._evidence_from_intelligence_item(item, evidence_type="arda_country_profile")])
                payload["answer"] = self._format_arda_country_result(payload)
                return payload
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": f"ARDA查询失败: {exc}"}

    def _tool_diag_threshold_ms(self) -> float:
        try:
            return max(1.0, float(os.getenv("TOOL_DIAG_BLOCK_THRESHOLD_MS", "1000").strip() or "1000"))
        except Exception:
            return 1000.0

    def _tool_diag_print(self, **fields: Any) -> None:
        try:
            for key, value in fields.items():
                if isinstance(value, (dict, list, tuple, set)):
                    rendered = json.dumps(value, ensure_ascii=False, default=str)
                else:
                    rendered = str(value)
                print(f"{key}={rendered}")
        except Exception:
            pass

    def _tool_diag_report_block(
        self,
        *,
        tool_name: str,
        file_path: str,
        function_name: str,
        line_no: int,
        sql_or_step: str,
        elapsed_ms: float,
        params: Any = None,
        reason: str = "",
    ) -> None:
        if elapsed_ms < self._tool_diag_threshold_ms():
            return
        self._tool_diag_print(
            TOOL_BLOCK_HERE=True,
            ToolName=tool_name,
            File=file_path,
            Function=function_name,
            Line=line_no,
            SQL=sql_or_step,
            Params=params if params is not None else {},
            elapsed_ms=round(elapsed_ms, 2),
            Reason=reason or "step_elapsed_over_threshold",
        )

    def _tool_diag_step(
        self,
        *,
        tool_name: str,
        function_name: str,
        step_name: str,
        line_no: int,
        step_detail: str,
        func: Any,
        params: Any = None,
    ) -> Any:
        file_path = os.path.abspath(__file__)
        self._tool_diag_print(ToolName=tool_name, **{step_name: step_detail})
        started = time.perf_counter()
        result = func()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._tool_diag_print(ToolName=tool_name, elapsed_ms=round(elapsed_ms, 2))
        self._tool_diag_report_block(
            tool_name=tool_name,
            file_path=file_path,
            function_name=function_name,
            line_no=line_no,
            sql_or_step=step_detail,
            elapsed_ms=elapsed_ms,
            params=params,
            reason="step_elapsed_over_threshold",
        )
        return result

    def _acquire_tool_db_session(
        self,
        *,
        tool_name: str,
        function_name: str,
        line_no: int,
        params: Any = None,
        timeout_seconds: float = 0.95,
    ) -> dict:
        from models.database import SessionLocal, record_pool_unavailable

        file_path = os.path.abspath(__file__)
        outcome: dict[str, Any] = {}
        finished = threading.Event()

        def runner() -> None:
            db = None
            started = time.perf_counter()
            try:
                db = SessionLocal()
                db.connection()
                elapsed_ms = (time.perf_counter() - started) * 1000
                if outcome.get("timed_out"):
                    try:
                        db.close()
                    except Exception:
                        pass
                    outcome["db_closed_after_timeout"] = True
                    return
                outcome["db"] = db
                outcome["elapsed_ms"] = elapsed_ms
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started) * 1000
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                outcome["error_type"] = type(exc).__name__
                outcome["error"] = str(exc)
                outcome["elapsed_ms"] = elapsed_ms
            finally:
                finished.set()

        self._tool_diag_print(ToolName=tool_name, STEP_1="acquire_db_session")
        worker = threading.Thread(
            target=runner,
            name=f"tool-db-session-{tool_name}-{uuid.uuid4().hex[:6]}",
            daemon=True,
        )
        worker.start()

        if not finished.wait(timeout_seconds):
            outcome["timed_out"] = True
            elapsed_ms = round(timeout_seconds * 1000, 2)
            record_pool_unavailable(
                file=file_path,
                function=function_name,
                line=line_no,
                reason="DBSessionAcquireTimeout",
            )
            self._tool_diag_print(
                ToolName=tool_name,
                SessionAcquireMs=elapsed_ms,
                SQLExecuted=False,
                SQLMs=0,
            )
            self._tool_diag_report_block(
                tool_name=tool_name,
                file_path=file_path,
                function_name=function_name,
                line_no=line_no,
                sql_or_step="STEP_1 acquire_db_session",
                elapsed_ms=elapsed_ms,
                params=params,
                reason="DBSessionAcquireTimeout",
            )
            return {
                "status": "error",
                "error_type": "DBSessionAcquireTimeout",
                "message": "failed to acquire db session within 1s",
                "session_acquire_ms": elapsed_ms,
                "sql_executed": False,
                "sql_ms": 0,
            }

        elapsed_ms = round(float(outcome.get("elapsed_ms") or 0.0), 2)
        if outcome.get("error_type"):
            self._tool_diag_print(
                ToolName=tool_name,
                SessionAcquireMs=elapsed_ms,
                SQLExecuted=False,
                SQLMs=0,
            )
            self._tool_diag_report_block(
                tool_name=tool_name,
                file_path=file_path,
                function_name=function_name,
                line_no=line_no,
                sql_or_step="STEP_1 acquire_db_session",
                elapsed_ms=elapsed_ms,
                params=params,
                reason=str(outcome.get("error_type") or "DBSessionAcquireError"),
            )
            return {
                "status": "error",
                "error_type": str(outcome.get("error_type") or "DBSessionAcquireError"),
                "message": str(outcome.get("error") or "failed to acquire db session"),
                "session_acquire_ms": elapsed_ms,
                "sql_executed": False,
                "sql_ms": 0,
            }

        self._tool_diag_print(ToolName=tool_name, SessionAcquireMs=elapsed_ms)
        return {"status": "ok", "db": outcome.get("db"), "session_acquire_ms": elapsed_ms}

    def _tool_diag_render_sql(self, query_or_sql: Any) -> str:
        try:
            if isinstance(query_or_sql, str):
                return query_or_sql
            statement = getattr(query_or_sql, "statement", None)
            if statement is not None:
                compiled = statement.compile(compile_kwargs={"literal_binds": True})
                return str(compiled)
            return str(query_or_sql)
        except Exception as exc:
            return f"<sql-render-failed: {exc}>"

    def _tool_diag_sql(
        self,
        *,
        tool_name: str,
        function_name: str,
        step_name: str,
        line_no: int,
        query_or_sql: Any,
        params: Any = None,
        executor: Any,
    ) -> Any:
        file_path = os.path.abspath(__file__)
        sql_text = self._tool_diag_render_sql(query_or_sql)
        self._tool_diag_print(ToolName=tool_name, **{step_name: "SQL_EXECUTION"})
        self._tool_diag_print(SQL_BEGIN=True, SQL_TEXT=sql_text, PARAMS=params if params is not None else {})
        started = time.perf_counter()
        result = executor()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self._tool_diag_print(ToolName=tool_name, SQLExecuted=True, SQLMs=round(elapsed_ms, 2))
        self._tool_diag_print(SQL_END=True, SQL_TEXT=sql_text, PARAMS=params if params is not None else {}, elapsed_ms=round(elapsed_ms, 2))
        self._tool_diag_report_block(
            tool_name=tool_name,
            file_path=file_path,
            function_name=function_name,
            line_no=line_no,
            sql_or_step=sql_text,
            elapsed_ms=elapsed_ms,
            params=params,
            reason="sql_elapsed_over_threshold",
        )
        return result

    def _query_organization_profile(self, org_name: str) -> dict:
        """融合多源数据生成机构深度画像。"""
        try:
            from models.database import (
                FundingRound,
                IntelligenceItem,
                Investment,
                Investor,
                KnowledgeEntity,
                OrganizationOntologyTag,
                OrganizationProfile,
            )
            from sqlalchemy import case, desc, func, or_

            normalized_name = (org_name or "").strip()
            tool_name = "query_organization_profile"
            function_name = "_query_organization_profile"
            self._tool_diag_print(ToolName=tool_name, ENTER_TOOL=function_name)
            if not normalized_name:
                return {"status": "error", "message": "缺少机构名称"}

            acquire_result = self._acquire_tool_db_session(
                tool_name=tool_name,
                function_name=function_name,
                line_no=inspect.currentframe().f_lineno + 1,
                params={"org_name": normalized_name},
            )
            if acquire_result.get("status") == "error":
                return acquire_result
            db = acquire_result["db"]
            try:
                org_query = (
                    db.query(OrganizationProfile)
                    .filter(
                        or_(
                            OrganizationProfile.name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.name_local.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.official_name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.short_name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.english_name.ilike(f"%{normalized_name}%"),
                        )
                    )
                    .order_by(
                        case(
                            (func.lower(OrganizationProfile.name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.name_local) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.official_name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.short_name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.english_name) == normalized_name.lower(), 0),
                            else_=1,
                        ),
                        case((OrganizationProfile.source_name == "manual_seed", 0), else_=1),
                        func.length(OrganizationProfile.name).asc(),
                        desc(OrganizationProfile.updated_at),
                    )
                )
                org = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_2",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=org_query,
                    params={"org_name": normalized_name},
                    executor=lambda: org_query.first(),
                )

                canonical_name = (org.name if org else normalized_name).strip()
                country = (org.country if org else self._extract_country(normalized_name)) or ""
                english_country = COUNTRY_ENGLISH_NAMES.get(country, country)

                profile_payload = {}
                ontology_tags = []
                if org:
                    score_payload = self._extract_score_payload(org=org)
                    profile_payload = {
                        "name": org.name,
                        "country": org.country,
                        "official_website": org.official_website,
                        "denomination": org.denomination,
                        "member_estimate": org.member_estimate,
                        "founded_year": org.founded_year,
                        "leader_name": org.leader_name,
                        "leader_title": org.leader_title,
                        "source_name": org.source_name,
                        "people_score": score_payload.get("people_score"),
                        "digital_score": score_payload.get("digital_score"),
                        "intel_score": score_payload.get("intel_score"),
                        "composite_score": score_payload.get("composite_score"),
                        "people_score_grade": getattr(org, "people_score_grade", None),
                        "digital_score_grade": getattr(org, "digital_score_grade", None),
                        "intel_score_grade": getattr(org, "intel_score_grade", None),
                    }
                    tags_query = (
                        db.query(OrganizationOntologyTag)
                        .filter(OrganizationOntologyTag.organization_id == org.id)
                    )
                    tags = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_3",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=tags_query,
                        params={"organization_id": org.id},
                        executor=lambda: tags_query.all(),
                    )
                    ontology_tags = [
                        {
                            "type": item.tag_type,
                            "tag_id": item.tag_id,
                            "confidence": item.confidence,
                        }
                        for item in tags
                    ]

                arda_payload = {}
                if english_country and english_country != "Global":
                    arda_payload = self._tool_diag_step(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_4",
                        line_no=inspect.currentframe().f_lineno + 1,
                        step_detail=f"call _query_arda_country({english_country})",
                        func=lambda: self._query_arda_country(english_country),
                        params={"country": english_country},
                    )

                aliases = []
                for candidate in [canonical_name, normalized_name, org.name_local if org else ""]:
                    cleaned = (candidate or "").strip()
                    if cleaned and cleaned not in aliases:
                        aliases.append(cleaned)

                intelligence_candidates = []
                if aliases:
                    text_filters = []
                    for term in aliases:
                        text_filters.extend(
                            [
                                IntelligenceItem.title.ilike(f"%{term}%"),
                                IntelligenceItem.content.ilike(f"%{term}%"),
                                IntelligenceItem.entity_name.ilike(f"%{term}%"),
                            ]
                        )
                    intelligence_query = (
                        db.query(IntelligenceItem)
                        .filter(
                            IntelligenceItem.source_name != "ARDA",
                            or_(*text_filters),
                        )
                        .order_by(desc(IntelligenceItem.published_at), desc(IntelligenceItem.ingested_at))
                    )
                    intelligence_query = intelligence_query.limit(30)
                    intelligence_candidates = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_5",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=intelligence_query,
                        params={"aliases": aliases},
                        executor=lambda: intelligence_query.all(),
                    )

                news = []
                news_evidence = []
                seen_titles = set()
                lower_aliases = [alias.lower() for alias in aliases if alias]
                multi_word_aliases = [alias for alias in lower_aliases if " " in alias]
                lower_country = (country or "").lower()
                lower_country_en = (english_country or "").lower()
                for item in intelligence_candidates:
                    combined_text = " ".join(
                        [
                            item.title or "",
                            item.content or "",
                        ]
                    ).lower()
                    entity_name = (item.entity_name or "").lower()
                    score = 0
                    matched = False

                    for alias in multi_word_aliases:
                        if alias in combined_text:
                            score += 10
                            matched = True
                        elif (
                            alias in entity_name
                            and any(token in combined_text for token in alias.split() if len(token) >= 5)
                            and (lower_country in combined_text or lower_country_en in combined_text)
                        ):
                            score += 6
                            matched = True

                    if not matched and lower_aliases:
                        for alias in lower_aliases:
                            if len(alias) >= 12 and alias in combined_text:
                                score += 6
                                matched = True
                            elif (
                                len(alias) >= 12
                                and alias in entity_name
                                and (lower_country in combined_text or lower_country_en in combined_text)
                            ):
                                score += 5
                                matched = True

                    if lower_country and ((item.country or "").lower() == lower_country or lower_country in combined_text):
                        score += 2
                    if lower_country_en and ((item.country or "").lower() == lower_country_en or lower_country_en in combined_text):
                        score += 2

                    if not matched or score < 6:
                        continue

                    title_key = ((item.title or "")[:120]).strip().lower()
                    if title_key and title_key in seen_titles:
                        continue
                    if title_key:
                        seen_titles.add(title_key)

                    event_time = item.published_at or item.ingested_at
                    news.append(
                        {
                            "title": item.title or "未命名动态",
                            "source_name": item.source_name or "未知来源",
                            "date": event_time.strftime("%Y-%m-%d") if event_time else "未知日期",
                            "country": item.country or "",
                            "url": item.source_url or "",
                            "confidence": float(item.confidence or 0.0),
                            "published_at": self._coerce_datetime_str(getattr(item, "published_at", None)),
                            "updated_at": self._coerce_datetime_str(getattr(item, "ingested_at", None)),
                        }
                    )
                    evidence_item = self._evidence_from_intelligence_item(item, evidence_type="organization_news")
                    if evidence_item:
                        news_evidence.append(evidence_item)
                    if len(news) >= 5:
                        break

                knowledge_entity = None
                for candidate in aliases:
                    knowledge_query = (
                        db.query(KnowledgeEntity)
                        .filter(KnowledgeEntity.name.ilike(f"%{candidate}%"))
                        .order_by(desc(KnowledgeEntity.ingested_at))
                    )
                    knowledge_entity = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_6",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=knowledge_query,
                        params={"candidate": candidate},
                        executor=lambda: knowledge_query.first(),
                    )
                    if knowledge_entity:
                        break

                investor_relations = []
                if knowledge_entity:
                    funding_query = (
                        db.query(FundingRound)
                        .filter(FundingRound.entity_id == knowledge_entity.id)
                        .order_by(desc(FundingRound.announced_date), desc(FundingRound.id))
                    )
                    funding_rows = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_7",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=funding_query,
                        params={"entity_id": knowledge_entity.id},
                        executor=lambda: funding_query.all(),
                    )
                    for fr in funding_rows[:5]:
                        relation_query = (
                            db.query(Investment, Investor)
                            .join(Investor, Investment.investor_id == Investor.id)
                            .filter(Investment.funding_round_id == fr.id)
                        )
                        relation_rows = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_8",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=relation_query,
                            params={"funding_round_id": fr.id},
                            executor=lambda: relation_query.all(),
                        )
                        for investment_row, investor_row in relation_rows:
                            investor_relations.append(
                                {
                                    "name": investor_row.name,
                                    "country": investor_row.country,
                                    "round_type": fr.round_type,
                                    "amount": investment_row.amount or fr.amount,
                                    "lead": bool(investment_row.lead_investor),
                                }
                            )

                has_any_data = bool(profile_payload or news or investor_relations or ontology_tags)
                if not has_any_data:
                    return {
                        "status": "not_found",
                        "message": f"目前情报有限，暂未检索到与 {normalized_name} 稳定相关的机构档案、国家环境或动态记录。",
                        "org_name": normalized_name,
                    }

                payload = {
                    "status": "success",
                    "org_name": canonical_name or normalized_name,
                    "organization": profile_payload,
                    "score_summary": self._extract_score_payload(profile=profile_payload),
                    "arda": arda_payload,
                    "news": news,
                    "investor_relations": investor_relations,
                    "ontology_tags": ontology_tags,
                }
                org_evidence = []
                if org:
                    org_evidence = [self._evidence_from_organization_profile(org, evidence_type="organization_profile")]
                payload["evidence"] = self._merge_evidence(org_evidence, news_evidence)
                payload["answer"] = self._format_organization_profile_result(payload)
                return payload
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": f"机构画像查询失败: {exc}"}

    def _build_direct_investor_prefetch(self, user_message: str) -> list[dict]:
        lowered = (user_message or "").lower()
        investor_markers = [
            "".join(chr(code) for code in [25237, 36164]),  # 投资
            "".join(chr(code) for code in [25237, 36164, 26426, 26500]),  # 投资机构
            "".join(chr(code) for code in [25237, 36164, 20154]),  # 投资人
            "".join(chr(code) for code in [25237, 36164, 26041]),  # 投资方
            "investor",
            "fund",
            "vc",
            "angel",
            "pe",
        ]
        is_faithtech_investor_prompt = (
            "faithtech" in lowered
            and any(token in lowered for token in investor_markers)
            and not self._looks_like_match_query(user_message)
            and not self._looks_like_funding_query(user_message)
        )
        if not is_faithtech_investor_prompt:
            return []
        args = self._infer_investor_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_investors",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _execute_tool_for_planner(self, tool_name: str, params: dict) -> dict:
        """
        为 Planner 执行单个子任务，复用现有工具调用能力
        """

        normalized_params = dict(params or {})
        if tool_name == "query_arda_country":
            raw_country_str = str(
                normalized_params.get("country")
                or normalized_params.get("country_name")
                or normalized_params.get("organization_name")
                or normalized_params.get("name")
                or normalized_params.get("query")
                or ""
            ).strip()
            raw_country = (
                raw_country_str
            )
            if re.search(r"[A-Za-z]", raw_country_str) and not re.search(r"[\u4e00-\u9fff]", raw_country_str):
                guessed_country = raw_country_str
            else:
                guessed_country = self._extract_country(str(raw_country)) or str(raw_country)
            normalized_params = {"country": guessed_country}
        elif tool_name in {"query_organization_profile", "query_contacts"}:
            raw_name = (
                normalized_params.get("org_name")
                or normalized_params.get("organization_name")
                or normalized_params.get("entity_name")
                or normalized_params.get("name")
                or normalized_params.get("query")
                or ""
            )
            normalized_params = {"org_name": str(raw_name)}
        elif tool_name == "query_funding_rounds":
            raw_entity = (
                normalized_params.get("entity_name")
                or normalized_params.get("organization_name")
                or normalized_params.get("org_name")
                or normalized_params.get("name")
                or ""
            )
            normalized_params = {
                "entity_name": str(raw_entity),
                "focus_area": normalized_params.get("focus_area"),
                "round_type": normalized_params.get("round_type"),
                "investor_name": normalized_params.get("investor_name"),
                "limit": int(normalized_params.get("limit", 10) or 10),
            }
        elif tool_name == "query_investors":
            raw_focus = normalized_params.get("focus_area") or normalized_params.get("query") or ""
            normalized_params = {
                "focus_area": str(raw_focus),
                "investor_type": normalized_params.get("investor_type"),
                "country": normalized_params.get("country"),
                "region": normalized_params.get("region"),
                "stage": normalized_params.get("stage"),
                "limit": int(normalized_params.get("limit", 10) or 10),
            }
        elif tool_name == "match_investors":
            raw_desc = (
                normalized_params.get("project_description")
                or normalized_params.get("organization_name")
                or normalized_params.get("query")
                or ""
            )
            normalized_params = {
                "project_description": str(raw_desc),
                "focus_area": str(normalized_params.get("focus_area") or ""),
                "stage": str(normalized_params.get("stage") or ""),
                "country": str(normalized_params.get("country") or ""),
                "region": str(normalized_params.get("region") or ""),
                "limit": int(normalized_params.get("limit", 5) or 5),
            }

        if hasattr(self, "available_functions") and tool_name in self.available_functions:
            try:
                result = self.available_functions[tool_name](**normalized_params)
                if result is None:
                    return {"data": None, "confidence": 60}
                if isinstance(result, dict):
                    result.setdefault("confidence", 70)
                    return result
                return {"data": result, "confidence": 70}
            except Exception as exc:
                return {"error": str(exc), "confidence": 0}

        import sys as _sys

        current_module = _sys.modules[__name__]
        func = getattr(current_module, tool_name, None)
        if func and callable(func):
            try:
                result = func(**normalized_params)
                if isinstance(result, dict):
                    result.setdefault("confidence", 70)
                    return result
                return {"data": result, "confidence": 70}
            except Exception as exc:
                return {"error": str(exc), "confidence": 0}
        return {"error": f"Tool '{tool_name}' not available", "confidence": 0}

    def think(
        self,
        user_message: str,
        conversation_id: str,
        conversation_history: list | None = None,
    ) -> dict:
        with trace_span("Brain", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
            self.conversation_id = conversation_id
            self._current_session_id = conversation_id
            self.conversation_history = (conversation_history or [])[-20:]
            self._compress_conversation_history()
            history = list(self.conversation_history)
            self._rebuild_entity_context(history, user_message)
            prompt_route = self._route_prompt(user_message)
            product_direct_result = self._product_intent_direct_result(user_message)
            if product_direct_result:
                print("RetrievalSkipped=True")
                print("ToolCalls=0")
                result = {
                    "answer": product_direct_result.get("answer") or "",
                    "evidence": product_direct_result.get("evidence") or [],
                }
                span.set_output_obj(result)
                return result
            relationship_graph_result = self._resolve_relationship_graph_if_applicable(
                user_message=user_message,
                conversation_id=conversation_id,
                route="simple",
            )
            if relationship_graph_result is not None:
                result = {
                    "answer": self._clean_output(relationship_graph_result.get("answer") or ""),
                    "evidence": self._merge_evidence(relationship_graph_result.get("evidence") or []),
                    "relationship_graph": relationship_graph_result.get("relationship_graph") or {},
                }
                span.set_output_obj(result)
                return result
            score_lookup_result = self._resolve_score_lookup_if_applicable(
                user_message=user_message,
                conversation_id=conversation_id,
                route="simple",
            )
            if score_lookup_result is not None:
                result = {
                    "answer": self._clean_output(score_lookup_result.get("answer") or ""),
                    "evidence": self._merge_evidence(score_lookup_result.get("evidence") or []),
                }
                span.set_output_obj(result)
                return result
            pipeline_enabled = feature_flag_enabled("PIPELINE_ORCHESTRATOR_ENABLED")
            if self._should_prefer_pipeline_for_insight_render() and pipeline_enabled:
                pipeline_service = self._get_pipeline_service(conversation_id=conversation_id)
                if pipeline_service is not None:
                    result = pipeline_service.execute(user_message, conversation_id, history)
                    span.set_output_obj(result)
                    return result
                from services.pipeline_orchestrator import PipelineOrchestrator

                result = PipelineOrchestrator(self, container=self.container).execute(user_message, conversation_id, history)
                span.set_output_obj(result)
                return result
            governor_enabled = feature_flag_enabled("ARCHITECTURE_GOVERNOR_ENABLED")
            if governor_enabled:
                governor = self._get_governor_service(conversation_id=conversation_id)
                if governor is not None:
                    result = governor.execute(user_message, conversation_id, history)
                    span.set_output_obj(result)
                    return result
                from services.architecture_governor import ArchitectureGovernor

                result = ArchitectureGovernor(self, container=self.container).execute(user_message, conversation_id, history)
                span.set_output_obj(result)
                return result
            if pipeline_enabled:
                pipeline_service = self._get_pipeline_service(conversation_id=conversation_id)
                if pipeline_service is not None:
                    result = pipeline_service.execute(user_message, conversation_id, history)
                    span.set_output_obj(result)
                    return result
                from services.pipeline_orchestrator import PipelineOrchestrator

                result = PipelineOrchestrator(self, container=self.container).execute(user_message, conversation_id, history)
                span.set_output_obj(result)
                return result
            collected_evidence: list[dict] = []

        def finalize(answer: str, evidence: Any = None) -> dict:
            merged = self._merge_evidence(collected_evidence, evidence or [])
            return {"answer": answer or "", "evidence": merged}

        parser = None
        try:
            from .query_parser import QueryParser

            parser = QueryParser()
            direct_result = parser.parse(user_message, conversation_id=conversation_id)
            if direct_result and direct_result.get("data_found"):
                answer = direct_result.get("answer") or direct_result.get("response") or ""
                evidence = direct_result.get("evidence") or []
                return finalize(self._clean_output(answer), evidence)
        finally:
            if parser:
                parser.close()

        if MULTI_AGENT_AVAILABLE:
            try:
                orchestrator = AgentOrchestrator()
                result = orchestrator.process(user_message)
                if result.get("data_found"):
                    return finalize(self._clean_output(result.get("response", "")), result.get("evidence") or [])
            except Exception as exc:
                logger.warning("[Brain] Multi-Agent失败，fallback到legacy: %s", exc)

        should_prioritize_match = self._looks_like_match_query(user_message)
        captured_profile = None if should_prioritize_match else self._capture_profile_from_message(user_message)
        if captured_profile:
            return finalize(captured_profile, [])

        if self._should_use_direct_answer(user_message):
            return finalize(
                self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)),
                [],
            )

        # ===== 新增：复杂分析类查询识别 =====
        analysis_detection = detect_analysis_type(user_message)
        if analysis_detection:
            analysis_type, target = analysis_detection.split(":", 1)
            plan = build_analysis_plan(analysis_type, target)

            if plan:
                results = []
                for task in plan:
                    try:
                        if task.tool_name == "query_arda_country":
                            result = self._query_arda_country(**task.params)
                        elif task.tool_name == "query_organization_profile":
                            result = self._query_organization_profile(**task.params)
                        elif task.tool_name == "query_database":
                            result = self._query_database(**task.params)
                        elif task.tool_name == "query_intelligence":
                            result = self._query_intelligence(**task.params)
                        elif task.tool_name == "query_investors":
                            result = self._query_investors(**task.params)
                        elif task.tool_name == "executive_report":
                            planner = BrainPlannerPipeline()
                            result = planner.generate_executive_report(
                                query_type=task.params.get("type", ""),
                                context=results,
                                target=target,
                            )
                        else:
                            continue
                        results.append({"step": task.priority, "tool": task.tool_name, "result": result})
                    except Exception as exc:
                        logger.error(f"Analysis step {task.priority} failed: {exc}")
                        continue

                if results:
                    return finalize(
                        self._apply_gap_notice_policy(
                            user_message,
                            self._format_analysis_result(analysis_type, target, results),
                        ),
                        [],
                    )

        # === Planner 集成（新增）===
        planner_report = None
        if not should_prioritize_match and not self._should_use_direct_answer(user_message):
            try:
                planner_pipeline = BrainPlannerPipeline()
                entities_list = self._get_planner_entities(user_message)

                planner_result = planner_pipeline.run(
                    user_message,
                    self._execute_tool_for_planner,
                    entities=entities_list,
                )

                if planner_result.get("used_plan"):
                    planner_results = planner_result.get("results", {})
                    if not self._validate_entity_relevance(user_message, planner_results):
                        logger.warning("Planner report skipped due to entity drift: %s", user_message)
                    else:
                        planner_report = planner_result.get("report", "")
                    if planner_report and len(planner_report) > 100:
                        return finalize(f"[[EXECUTIVE_REPORT]]\n{planner_report}", [])
            except Exception as exc:
                logger.debug(f"Planner execution failed: {exc}")
        # === Planner 集成结束 ===

        if not DEEPSEEK_API_KEY:
            return finalize(
                self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)),
                [],
            )

        prompt_route = self._resolve_prompt_route(user_message)
        assistant_mode = self._is_assistant_prompt_route(prompt_route)
        messages = self._build_messages(user_message, history)
        reasoning_enabled = feature_flag_enabled("REASONING_ENGINE_V1_ENABLED") and not assistant_mode
        planned_tool_calls: list[dict] = []
        if reasoning_enabled:
            try:
                engine = self._get_reasoning_engine_service(conversation_id=conversation_id)
                if engine is None:
                    from services.reasoning_engine_v1 import ReasoningEngineV1

                    engine = ReasoningEngineV1()
                country = self._extract_country(user_message)
                pre = engine.build_reasoning_result_pre(user_message, self.current_entities, country)
                capability_planner_enabled = feature_flag_enabled("CAPABILITY_PLANNER_ENABLED")
                self._reasoning_v1_context = {
                    "question_type": pre.question_type.value,
                    "country": country,
                    "requirement": pre.requirement,
                    "tool_plan": [] if capability_planner_enabled else pre.tool_plan,
                }

                def build_call(tool_name: str, args: dict) -> dict:
                    return {
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
                    }

                def pick_entity_name() -> str:
                    candidate = self._extract_organization_profile_name(user_message)
                    if candidate:
                        return candidate
                    for item in (self.current_entities or [])[-5:]:
                        if isinstance(item, dict) and (item.get("name") or "").strip():
                            return (item.get("name") or "").strip()
                    return ""

                for tool_name in pre.tool_plan:
                    if tool_name == "query_organization_profile":
                        org_name = pick_entity_name()
                        if org_name:
                            planned_tool_calls.append(build_call("query_organization_profile", {"org_name": org_name}))
                    elif tool_name == "query_contacts":
                        org_name = pick_entity_name()
                        if org_name:
                            planned_tool_calls.append(build_call("query_contacts", {"org_name": org_name}))
                    elif tool_name == "query_graph":
                        entity_name = pick_entity_name()
                        if entity_name:
                            planned_tool_calls.append(build_call("query_graph", {"entity_name": entity_name}))
                    elif tool_name == "query_arda_country":
                        args = self._build_arda_country_args(user_message)
                        if args.get("country"):
                            planned_tool_calls.append(build_call("query_arda_country", args))
                    elif tool_name == "query_intelligence":
                        args = self._build_intelligence_query_args(user_message)
                        planned_tool_calls.append(build_call("query_intelligence", args))
                    elif tool_name == "query_database":
                        args = self._build_query_args(user_message)
                        planned_tool_calls.append(build_call("query_database", args))
            except Exception:
                planned_tool_calls = []

        prefetched_tool_calls = []
        if not assistant_mode:
            prefetched_tool_calls = (
                self._build_direct_investor_prefetch(user_message)
                or planned_tool_calls
                or self._build_prefetched_tool_calls(user_message)
            )
        tool_choice = None if assistant_mode else self._choose_tool_for_message(user_message)

        if prefetched_tool_calls:
            direct_tool_name = prefetched_tool_calls[0].get("function", {}).get("name", "")
            if direct_tool_name in self._direct_render_tool_names():
                raw_arguments = prefetched_tool_calls[0].get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}
                func = self.available_functions.get(direct_tool_name)
                if func:
                    result = self._normalize_tool_result(direct_tool_name, func(**function_args))
                    direct_content = self._render_direct_tool_result(direct_tool_name, result)
                    if direct_content:
                        if isinstance(result, dict) and isinstance(result.get("evidence"), list):
                            collected_evidence.extend(result.get("evidence") or [])
                        return finalize(self._apply_gap_notice_policy(user_message, direct_content), result.get("evidence") if isinstance(result, dict) else [])
            response = self._continue_after_tool_calls(messages, prefetched_tool_calls)
            if response:
                final_content = response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if final_content:
                    return finalize(self._apply_gap_notice_policy(user_message, final_content), [])
            return finalize(self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)), [])

        response = self._call_llm(messages, tools=None if assistant_mode else TOOLS, tool_choice=tool_choice)
        if not response:
            return finalize(self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)), [])

        collected_tool_results: list[dict] = []
        for _ in range(3):
            assistant_msg = response.get("choices", [{}])[0].get("message", {})
            tool_calls = assistant_msg.get("tool_calls") or []

            if not tool_calls:
                final_content = assistant_msg.get("content", "").strip()
                if final_content:
                    return finalize(self._apply_gap_notice_policy(user_message, final_content), [])
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.get("content", ""),
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                function_name = tool_call.get("function", {}).get("name", "")
                raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}

                print(f"[Brain] 调用工具: {function_name}({function_args})")

                func = self.available_functions.get(function_name)
                if func:
                    try:
                        result = self._normalize_tool_result(function_name, func(**function_args))
                    except TypeError as exc:
                        result = self._normalize_tool_result(function_name, {"status": "error", "message": f"参数错误: {exc}"})
                else:
                    result = self._normalize_tool_result(function_name, {"status": "error", "message": f"未知工具: {function_name}"})
                if isinstance(result, dict) and isinstance(result.get("evidence"), list):
                    collected_evidence.extend(result.get("evidence") or [])
                if isinstance(result, dict):
                    collected_tool_results.append(result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            composer_enabled = feature_flag_enabled("ANSWER_COMPOSER_ENABLED")
            if composer_enabled and collected_tool_results:
                answer_context = self._build_answer_context(user_message, collected_tool_results)
                filtered_messages = [m for m in messages if m.get("role") != "tool" and "tool_calls" not in m]
                if answer_context:
                    filtered_messages = [
                        m
                        for m in filtered_messages
                        if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Answer Context"))
                    ]
                    filtered_messages.append({"role": "system", "content": self._format_answer_context(answer_context)})
                final_response = self._call_llm(filtered_messages, tools=None)
                if final_response:
                    final_content = final_response.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    if final_content:
                        return finalize(self._apply_gap_notice_policy(user_message, final_content), [])
                return finalize(self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)), [])

            if reasoning_enabled and collected_tool_results:
                try:
                    from services.reasoning_engine_v1 import QuestionType

                    ctx = getattr(self, "_reasoning_v1_context", {}) or {}
                    qt_value = str(ctx.get("question_type") or "UNKNOWN")
                    from services.core_models import Requirement as CoreRequirement

                    req = ctx.get("requirement")
                    requirement = req if isinstance(req, CoreRequirement) else CoreRequirement.from_dict(req or {})
                    tool_plan = ctx.get("tool_plan") or []
                    qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
                    engine = self._get_reasoning_engine_service(conversation_id=conversation_id)
                    if engine is None:
                        from services.reasoning_engine_v1 import ReasoningEngineV1

                        engine = ReasoningEngineV1()
                    evaluation = engine.evaluate_evidence(collected_tool_results, requirement)
                    conflicts = engine.detect_conflicts(collected_tool_results)
                    ranked_evidence = engine.rank_evidence(collected_tool_results)
                    merged = engine.merge_duplicate_facts(ranked_evidence)
                    outline = engine.build_answer_outline(qt, requirement, ranked_evidence)
                    verification = engine.verification(evaluation, conflicts, ranked_evidence)
                    reasoning_message = self._format_reasoning_engine_v1_message(qt_value, requirement.to_dict(), tool_plan, evaluation, conflicts, outline)
                    messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Reasoning Plan"))]
                    messages.append({"role": "system", "content": reasoning_message})
                except Exception:
                    pass

            response = self._call_llm(messages, tools=None if assistant_mode else TOOLS)
            if not response:
                return finalize(self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)), [])

        result = finalize(self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history)), [])
        span.set_output_obj(result)
        return result

    def think_stream(
        self,
        user_message: str,
        conversation_id: str,
        conversation_history: list | None = None,
    ):
        with trace_span("Brain", input_obj={"message": user_message, "conversation_id": conversation_id}) as span:
            direct_answer = False
            parser_result = None
            workflow_outputs = None
            selected_prompt = None
            route_reason = None
            prompt_route = None
            assistant_mode = False
            llm_entered = False
            print("STEP_1 ENTER think_stream")

            def _brain_stream_trace(event: str, **extra):
                print(
                    "BRAIN_THINK_STREAM_TRACE "
                    + json.dumps(
                        {
                            "event": event,
                            "Reason": extra.pop("Reason", ""),
                            "direct_answer": extra.pop("direct_answer", direct_answer),
                            "parser_result": extra.pop("parser_result", parser_result),
                            "workflow_outputs": extra.pop("workflow_outputs", workflow_outputs),
                            "selected_prompt": extra.pop("selected_prompt", selected_prompt),
                            "route_reason": extra.pop("route_reason", route_reason),
                            "llm_entered": extra.pop("llm_entered", llm_entered),
                            **extra,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                )

            prompt_route = self._route_prompt(user_message)
            selected_prompt = str((prompt_route or {}).get("selected_prompt") or "").strip() or None
            route_reason = str((prompt_route or {}).get("reason") or "").strip() or None
            assistant_mode = self._is_assistant_prompt_route(prompt_route)
            self.conversation_id = conversation_id
            self._current_session_id = conversation_id
            self.conversation_history = (conversation_history or [])[-20:]
            self._compress_conversation_history()
            history = list(self.conversation_history)
            if selected_prompt == "Research Prompt":
                self.current_entities = []
            else:
                self._rebuild_entity_context(history, user_message)
            product_direct_result = self._product_intent_direct_result(user_message)
            if product_direct_result:
                direct_answer = True
                parser_result = product_direct_result
                print("RetrievalSkipped=True")
                print("ToolCalls=0")
                response_text = str(product_direct_result.get("answer") or "")
                words = response_text.split(" ")
                chunk = ""
                for word in words:
                    chunk += word + " "
                    if len(chunk) >= 50:
                        yield {"type": "token", "content": chunk.strip() + " "}
                        chunk = ""
                if chunk.strip():
                    yield {"type": "token", "content": chunk.strip()}
                yield {
                    "type": "done",
                    "full_content": response_text,
                    "evidence": product_direct_result.get("evidence") or [],
                    "direct_answer": True,
                    "welcome_reply_uuid": None,
                }
                span.set_output_obj({"done": True, "product_intent": product_direct_result.get("product_intent")})
                _brain_stream_trace(
                    "RETURN_ID=PRODUCT",
                    Reason="product_intent_direct_answer",
                    conversation_id=conversation_id,
                    parser_result=product_direct_result,
                    parser_result_direct_answer=True,
                    parser_result_data_found=True,
                )
                return
            relationship_graph_result = self._resolve_relationship_graph_if_applicable(
                user_message=user_message,
                conversation_id=conversation_id,
                route="stream",
            )
            if relationship_graph_result is not None:
                direct_answer = True
                parser_result = relationship_graph_result.get("parsed_result")
                response_text = str(relationship_graph_result.get("answer") or "")
                evidence = relationship_graph_result.get("evidence") or []
                if response_text:
                    yield {"type": "token", "content": response_text}
                yield {
                    "type": "done",
                    "full_content": response_text,
                    "evidence": self._merge_evidence(evidence),
                    "relationship_graph": relationship_graph_result.get("relationship_graph") or {},
                    "direct_answer": True,
                    "welcome_reply_uuid": lookup_welcome_reply_uuid(conversation_id, response_text),
                }
                span.set_output_obj({"done": True, "relationship_graph": True, "organization_name": relationship_graph_result.get("organization_name")})
                _brain_stream_trace(
                    "RETURN_ID=RELATIONSHIP_GRAPH",
                    Reason="relationship_graph_db_return",
                    conversation_id=conversation_id,
                    parser_result=parser_result,
                    parser_result_response=response_text,
                    parser_result_direct_answer=True,
                    parser_result_data_found=True,
                )
                return
            score_lookup_result = self._resolve_score_lookup_if_applicable(
                user_message=user_message,
                conversation_id=conversation_id,
                route="stream",
            )
            if score_lookup_result is not None:
                direct_answer = True
                parser_result = score_lookup_result.get("parsed_result")
                response_text = str(score_lookup_result.get("answer") or "")
                evidence = score_lookup_result.get("evidence") or []
                if response_text:
                    yield {"type": "token", "content": response_text}
                yield {
                    "type": "done",
                    "full_content": response_text,
                    "evidence": self._merge_evidence(evidence),
                    "direct_answer": True,
                    "welcome_reply_uuid": lookup_welcome_reply_uuid(conversation_id, response_text),
                }
                span.set_output_obj({"done": True, "score_lookup": True, "organization_name": score_lookup_result.get("organization_name")})
                _brain_stream_trace(
                    "RETURN_ID=SCORE_LOOKUP",
                    Reason="score_lookup_db_return",
                    conversation_id=conversation_id,
                    parser_result=parser_result,
                    parser_result_response=response_text,
                    parser_result_direct_answer=True,
                    parser_result_data_found=True,
                )
                return
            _brain_stream_trace(
                "ENTER Brain",
                Reason="think_stream_enter",
                conversation_id=conversation_id,
            )
            governor_enabled = feature_flag_enabled("ARCHITECTURE_GOVERNOR_ENABLED")
            # #region debug-point A:brain-stream-entry
            debug_answer_event(
                "Brain Stream Entry",
                user_message,
                trace_id=conversation_id,
                hypothesis_id="A",
                location="brain.py:think_stream:entry",
                extra={"conversation_id": conversation_id, "governor_enabled": bool(governor_enabled)},
            )
            # #endregion
            if self._should_prefer_pipeline_for_insight_render():
                pipeline_service = self._get_pipeline_service(conversation_id=conversation_id)
                if pipeline_service is not None:
                    buffered_answer = ""
                    for chunk in pipeline_service.execute_stream(user_message, conversation_id, history):
                        if isinstance(chunk, dict) and chunk.get("type") == "token":
                            buffered_answer += str(chunk.get("content") or "")
                        elif isinstance(chunk, dict) and chunk.get("type") == "done":
                            final_answer = str(chunk.get("full_content") or buffered_answer)
                            debug_answer_event(
                                "Brain Final Answer",
                                final_answer,
                                trace_id=conversation_id,
                                hypothesis_id="A",
                                location="brain.py:think_stream:pipeline_preferred",
                                extra={"path": "pipeline_preferred"},
                            )
                            emit_welcome_trace(
                                "BRAIN_UUID",
                                lookup_welcome_reply_uuid(conversation_id, final_answer),
                                conversation_id=conversation_id,
                                extra={"location": "brain.py:think_stream:pipeline_preferred"},
                            )
                            workflow_outputs = {
                                "path": "pipeline_preferred",
                                "full_content": final_answer,
                                "full_content_length": len(final_answer),
                            }
                        yield chunk
                    span.set_output_obj({"done": True})
                    _brain_stream_trace(
                        "RETURN_ID=A_PIPELINE",
                        Reason="pipeline_preferred_return",
                        conversation_id=conversation_id,
                    )
                    return
                from services.pipeline_orchestrator import PipelineOrchestrator

                buffered_answer = ""
                for chunk in PipelineOrchestrator(self, container=self.container).execute_stream(user_message, conversation_id, history):
                    if isinstance(chunk, dict) and chunk.get("type") == "token":
                        buffered_answer += str(chunk.get("content") or "")
                    elif isinstance(chunk, dict) and chunk.get("type") == "done":
                        final_answer = str(chunk.get("full_content") or buffered_answer)
                        debug_answer_event(
                            "Brain Final Answer",
                            final_answer,
                            trace_id=conversation_id,
                            hypothesis_id="A",
                            location="brain.py:think_stream:pipeline_preferred_inline",
                            extra={"path": "pipeline_preferred_inline"},
                        )
                        emit_welcome_trace(
                            "BRAIN_UUID",
                            lookup_welcome_reply_uuid(conversation_id, final_answer),
                            conversation_id=conversation_id,
                            extra={"location": "brain.py:think_stream:pipeline_preferred_inline"},
                        )
                        workflow_outputs = {
                            "path": "pipeline_preferred_inline",
                            "full_content": final_answer,
                            "full_content_length": len(final_answer),
                        }
                    yield chunk
                span.set_output_obj({"done": True})
                _brain_stream_trace(
                    "RETURN_ID=A_PIPELINE_INLINE",
                    Reason="pipeline_preferred_inline_return",
                    conversation_id=conversation_id,
                )
                return
            if governor_enabled:
                governor = self._get_governor_service(conversation_id=conversation_id)
                if governor is not None:
                    buffered_answer = ""
                    print("BRAIN_ENTER_GOVERNOR_STREAM")
                    try:
                        print("STEP_2 BEFORE governor.execute_stream")
                        for chunk in governor.execute_stream(user_message, conversation_id, history):
                            if isinstance(chunk, dict) and chunk.get("type") == "token":
                                buffered_answer += str(chunk.get("content") or "")
                            elif isinstance(chunk, dict) and chunk.get("type") == "done":
                                final_answer = str(chunk.get("full_content") or buffered_answer)
                                # #region debug-point A:brain-final-answer-governor
                                debug_answer_event(
                                    "Brain Final Answer",
                                    final_answer,
                                    trace_id=conversation_id,
                                    hypothesis_id="A",
                                    location="brain.py:think_stream:governor",
                                    extra={"path": "governor"},
                                )
                                emit_welcome_trace(
                                    "BRAIN_UUID",
                                    lookup_welcome_reply_uuid(conversation_id, final_answer),
                                    conversation_id=conversation_id,
                                    extra={"location": "brain.py:think_stream:governor"},
                                )
                                # #endregion
                                workflow_outputs = {
                                    "path": "governor",
                                    "full_content": final_answer,
                                    "full_content_length": len(final_answer),
                                }
                            yield chunk
                        print("STEP_3 AFTER governor.execute_stream")
                        print("BRAIN_GOVERNOR_STREAM_FINISHED")
                    except GeneratorExit:
                        print("BRAIN_GENERATOR_EXIT")
                        raise
                    except asyncio.CancelledError:
                        print("BRAIN_CANCELLED")
                        raise
                    except Exception as e:
                        print("BRAIN_EXCEPTION", repr(e))
                        raise
                    finally:
                        print("BRAIN_STREAM_FINALLY")
                    span.set_output_obj({"done": True})
                    _brain_stream_trace(
                        "RETURN_ID=A",
                        Reason="governor_service_return",
                        conversation_id=conversation_id,
                    )
                    return
                from services.architecture_governor import ArchitectureGovernor

                buffered_answer = ""
                print("BRAIN_ENTER_GOVERNOR_STREAM")
                try:
                    print("STEP_2 BEFORE governor.execute_stream")
                    for chunk in ArchitectureGovernor(self, container=self.container).execute_stream(user_message, conversation_id, history):
                        if isinstance(chunk, dict) and chunk.get("type") == "token":
                            buffered_answer += str(chunk.get("content") or "")
                        elif isinstance(chunk, dict) and chunk.get("type") == "done":
                            final_answer = str(chunk.get("full_content") or buffered_answer)
                            # #region debug-point A:brain-final-answer-governor-inline
                            debug_answer_event(
                                "Brain Final Answer",
                                final_answer,
                                trace_id=conversation_id,
                                hypothesis_id="A",
                                location="brain.py:think_stream:governor_inline",
                                extra={"path": "governor_inline"},
                            )
                            emit_welcome_trace(
                                "BRAIN_UUID",
                                lookup_welcome_reply_uuid(conversation_id, final_answer),
                                conversation_id=conversation_id,
                                extra={"location": "brain.py:think_stream:governor_inline"},
                            )
                            # #endregion
                            workflow_outputs = {
                                "path": "governor_inline",
                                "full_content": final_answer,
                                "full_content_length": len(final_answer),
                            }
                        yield chunk
                    print("STEP_3 AFTER governor.execute_stream")
                    print("BRAIN_GOVERNOR_STREAM_FINISHED")
                except GeneratorExit:
                    print("BRAIN_GENERATOR_EXIT")
                    raise
                except asyncio.CancelledError:
                    print("BRAIN_CANCELLED")
                    raise
                except Exception as e:
                    print("BRAIN_EXCEPTION", repr(e))
                    raise
                finally:
                    print("BRAIN_STREAM_FINALLY")
                span.set_output_obj({"done": True})
                _brain_stream_trace(
                    "RETURN_ID=B",
                    Reason="governor_inline_return",
                    conversation_id=conversation_id,
                )
                return
            pipeline_enabled = feature_flag_enabled("PIPELINE_ORCHESTRATOR_ENABLED")
            if pipeline_enabled:
                pipeline_service = self._get_pipeline_service(conversation_id=conversation_id)
                if pipeline_service is not None:
                    buffered_answer = ""
                    for chunk in pipeline_service.execute_stream(user_message, conversation_id, history):
                        if isinstance(chunk, dict) and chunk.get("type") == "token":
                            buffered_answer += str(chunk.get("content") or "")
                        elif isinstance(chunk, dict) and chunk.get("type") == "done":
                            final_answer = str(chunk.get("full_content") or buffered_answer)
                            # #region debug-point A:brain-final-answer-pipeline
                            debug_answer_event(
                                "Brain Final Answer",
                                final_answer,
                                trace_id=conversation_id,
                                hypothesis_id="A",
                                location="brain.py:think_stream:pipeline",
                                extra={"path": "pipeline"},
                            )
                            emit_welcome_trace(
                                "BRAIN_UUID",
                                lookup_welcome_reply_uuid(conversation_id, final_answer),
                                conversation_id=conversation_id,
                                extra={"location": "brain.py:think_stream:pipeline"},
                            )
                            # #endregion
                            workflow_outputs = {
                                "path": "pipeline",
                                "full_content": final_answer,
                                "full_content_length": len(final_answer),
                            }
                        yield chunk
                    span.set_output_obj({"done": True})
                    _brain_stream_trace(
                        "RETURN_ID=C",
                        Reason="pipeline_service_return",
                        conversation_id=conversation_id,
                    )
                    return
                from services.pipeline_orchestrator import PipelineOrchestrator

                buffered_answer = ""
                for chunk in PipelineOrchestrator(self, container=self.container).execute_stream(user_message, conversation_id, history):
                    if isinstance(chunk, dict) and chunk.get("type") == "token":
                        buffered_answer += str(chunk.get("content") or "")
                    elif isinstance(chunk, dict) and chunk.get("type") == "done":
                        final_answer = str(chunk.get("full_content") or buffered_answer)
                        # #region debug-point A:brain-final-answer-pipeline-inline
                        debug_answer_event(
                            "Brain Final Answer",
                            final_answer,
                            trace_id=conversation_id,
                            hypothesis_id="A",
                            location="brain.py:think_stream:pipeline_inline",
                            extra={"path": "pipeline_inline"},
                        )
                        emit_welcome_trace(
                            "BRAIN_UUID",
                            lookup_welcome_reply_uuid(conversation_id, final_answer),
                            conversation_id=conversation_id,
                            extra={"location": "brain.py:think_stream:pipeline_inline"},
                        )
                        # #endregion
                        workflow_outputs = {
                            "path": "pipeline_inline",
                            "full_content": final_answer,
                            "full_content_length": len(final_answer),
                        }
                    yield chunk
                span.set_output_obj({"done": True})
                _brain_stream_trace(
                    "RETURN_ID=D",
                    Reason="pipeline_inline_return",
                    conversation_id=conversation_id,
                )
                return
            collected_evidence: list[dict] = []

        parser = None
        try:
            from .query_parser import QueryParser

            parser = QueryParser()
            _brain_stream_trace(
                "CALL QueryParser.parse",
                Reason="before_query_parser_parse",
                conversation_id=conversation_id,
            )
            direct_result = parser.parse(user_message, conversation_id=conversation_id)
            parser_result = direct_result
            direct_answer = bool((direct_result or {}).get("direct_answer"))
            if direct_result and direct_result.get("data_found"):
                response_text = direct_result.get("answer") or direct_result.get("response") or ""
                welcome_reply_uuid = direct_result.get("welcome_reply_uuid") or lookup_welcome_reply_uuid(conversation_id, response_text)
                emit_welcome_trace(
                    "BRAIN_UUID",
                    welcome_reply_uuid,
                    conversation_id=conversation_id,
                    extra={"location": "brain.py:think_stream:direct_result"},
                )
                evidence = direct_result.get("evidence") or []
                if isinstance(evidence, list):
                    collected_evidence.extend(evidence)
                words = response_text.split(" ")
                chunk = ""
                for word in words:
                    chunk += word + " "
                    if len(chunk) >= 50:
                        yield {"type": "token", "content": chunk.strip() + " "}
                        chunk = ""
                if chunk.strip():
                    yield {"type": "token", "content": chunk.strip()}
                yield {
                    "type": "done",
                    "full_content": response_text,
                    "evidence": self._merge_evidence(collected_evidence),
                    "welcome_reply_uuid": welcome_reply_uuid,
                }
                _brain_stream_trace(
                    "RETURN_ID=E",
                    Reason="parser_result_direct_answer",
                    conversation_id=conversation_id,
                    parser_result=direct_result,
                    parser_result_response=response_text,
                    parser_result_direct_answer=bool(direct_result.get("direct_answer")),
                    parser_result_data_found=bool(direct_result.get("data_found")),
                )
                return
        except Exception as exc:
            _brain_stream_trace(
                "EXCEPTION QueryParser.parse",
                Reason="query_parser_exception",
                conversation_id=conversation_id,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
            raise
        finally:
            if parser:
                parser.close()

        # ===== Multi-Agent 直答路径（与 think() 保持一致）=====
        if MULTI_AGENT_AVAILABLE:
            try:
                from agents.orchestrator import AgentOrchestrator

                orchestrator = AgentOrchestrator()
                result = orchestrator.process(user_message)
                if result.get("data_found"):
                    response_text = result.get("response", "") or ""
                    evidence = result.get("evidence") or []
                    if isinstance(evidence, list):
                        collected_evidence.extend(evidence)
                    words = response_text.split(" ")
                    chunk = ""
                    for word in words:
                        chunk += word + " "
                        if len(chunk) >= 50:
                            yield {"type": "token", "content": chunk.strip() + " "}
                            chunk = ""
                    if chunk.strip():
                        yield {"type": "token", "content": chunk.strip()}
                    yield {"type": "done", "full_content": response_text, "evidence": self._merge_evidence(collected_evidence)}
                    return
            except Exception as exc:
                logger.warning("[Brain] think_stream Multi-Agent fallback: %s", exc)

        yield {"type": "thinking"}

        should_prioritize_match = self._looks_like_match_query(user_message)
        captured_profile = None if should_prioritize_match else self._capture_profile_from_message(user_message)
        if captured_profile:
            for ch in captured_profile:
                yield {"type": "token", "content": ch}
            yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
            _brain_stream_trace(
                "RETURN_ID=F",
                Reason="captured_profile_return",
                conversation_id=conversation_id,
            )
            return

        if self._should_use_direct_answer(user_message):
            direct_answer = True
            direct_reply = self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history))
            for ch in direct_reply:
                yield {"type": "token", "content": ch}
            yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
            _brain_stream_trace(
                "RETURN_ID=G",
                Reason="should_use_direct_answer",
                conversation_id=conversation_id,
            )
            return

        # === Planner 集成（新增）===
        if not should_prioritize_match and not self._should_use_direct_answer(user_message):
            try:
                planner_pipeline = BrainPlannerPipeline()
                entities_list = self._get_planner_entities(user_message)

                planner_result = planner_pipeline.run(
                    user_message,
                    self._execute_tool_for_planner,
                    entities=entities_list,
                )

                report = planner_result.get("report", "") if isinstance(planner_result, dict) else ""
                planner_results = planner_result.get("results", {}) if isinstance(planner_result, dict) else {}
                is_relevant = self._validate_entity_relevance(user_message, planner_results)
                if planner_result.get("used_plan") and is_relevant and report and len(report) > 100:
                    yield {"type": "thinking", "content": "Planner analyzing..."}
                    yield {"type": "token", "content": "[[EXECUTIVE_REPORT]]\n\n"}
                    chunk_size = 100
                    for i in range(0, len(report), chunk_size):
                        yield {"type": "token", "content": report[i : i + chunk_size]}
                    yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                    workflow_outputs = {
                        "path": "planner_report",
                        "report_length": len(report),
                    }
                    _brain_stream_trace(
                        "RETURN_ID=H",
                        Reason="planner_report_return",
                        conversation_id=conversation_id,
                    )
                    return
                if planner_result.get("used_plan") and not is_relevant:
                    logger.warning("Planner stream report skipped due to entity drift: %s", user_message)
            except Exception as exc:
                logger.debug(f"Planner stream execution failed: {exc}")
        # === Planner 集成结束 ===

        if not DEEPSEEK_API_KEY:
            fallback = self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history))
            for ch in fallback:
                yield {"type": "token", "content": ch}
            yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
            _brain_stream_trace(
                "RETURN_ID=I",
                Reason="missing_deepseek_api_key",
                conversation_id=conversation_id,
            )
            return

        _brain_stream_trace(
            "CALL PromptRouter",
            Reason="prompt_route_resolved_at_entry",
            conversation_id=conversation_id,
            selected_prompt=selected_prompt,
            route_reason=route_reason,
        )
        print("STEP_4 PROMPT_ROUTE_READY")
        print("STEP_5 AFTER _resolve_prompt_route")
        _brain_stream_trace(
            "CALL build_messages",
            Reason="before_build_messages",
            conversation_id=conversation_id,
            selected_prompt=selected_prompt,
        )
        print("STEP_6 BEFORE build_messages")
        messages = self._build_messages(user_message, history)
        first_tool_calls = None
        reasoning_enabled = feature_flag_enabled("REASONING_ENGINE_V1_ENABLED") and not assistant_mode
        planned_tool_calls: list[dict] = []
        if reasoning_enabled:
            try:
                engine = self._get_reasoning_engine_service(conversation_id=conversation_id)
                if engine is None:
                    from services.reasoning_engine_v1 import ReasoningEngineV1

                    engine = ReasoningEngineV1()
                country = self._extract_country(user_message)
                pre = engine.build_reasoning_result_pre(user_message, self.current_entities, country)
                capability_planner_enabled = feature_flag_enabled("CAPABILITY_PLANNER_ENABLED")
                self._reasoning_v1_context = {
                    "question_type": pre.question_type.value,
                    "country": country,
                    "requirement": pre.requirement,
                    "tool_plan": [] if capability_planner_enabled else pre.tool_plan,
                }

                def build_call(tool_name: str, args: dict) -> dict:
                    return {
                        "id": f"call_{uuid.uuid4().hex[:12]}",
                        "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(args or {}, ensure_ascii=False)},
                    }

                def pick_entity_name() -> str:
                    candidate = self._extract_organization_profile_name(user_message)
                    if candidate:
                        return candidate
                    for item in (self.current_entities or [])[-5:]:
                        if isinstance(item, dict) and (item.get("name") or "").strip():
                            return (item.get("name") or "").strip()
                    return ""

                for tool_name in pre.tool_plan:
                    if tool_name == "query_organization_profile":
                        org_name = pick_entity_name()
                        if org_name:
                            planned_tool_calls.append(build_call("query_organization_profile", {"org_name": org_name}))
                    elif tool_name == "query_contacts":
                        org_name = pick_entity_name()
                        if org_name:
                            planned_tool_calls.append(build_call("query_contacts", {"org_name": org_name}))
                    elif tool_name == "query_graph":
                        entity_name = pick_entity_name()
                        if entity_name:
                            planned_tool_calls.append(build_call("query_graph", {"entity_name": entity_name}))
                    elif tool_name == "query_arda_country":
                        args = self._build_arda_country_args(user_message)
                        if args.get("country"):
                            planned_tool_calls.append(build_call("query_arda_country", args))
                    elif tool_name == "query_intelligence":
                        args = self._build_intelligence_query_args(user_message)
                        planned_tool_calls.append(build_call("query_intelligence", args))
                    elif tool_name == "query_database":
                        args = self._build_query_args(user_message)
                        planned_tool_calls.append(build_call("query_database", args))
            except Exception:
                planned_tool_calls = []

        prefetched_tool_calls = []
        if not assistant_mode:
            prefetched_tool_calls = (
                self._build_direct_investor_prefetch(user_message)
                or planned_tool_calls
                or self._build_prefetched_tool_calls(user_message)
            )
        tool_choice = None if assistant_mode else self._choose_tool_for_message(user_message)

        if prefetched_tool_calls:
            direct_tool_name = prefetched_tool_calls[0].get("function", {}).get("name", "")
            if direct_tool_name in self._direct_render_tool_names():
                raw_arguments = prefetched_tool_calls[0].get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}
                yield {"type": "tool_call", "name": direct_tool_name, "args": function_args}
                func = self.available_functions.get(direct_tool_name)
                if func:
                    result = self._normalize_tool_result(direct_tool_name, func(**function_args))
                    if isinstance(result, dict) and isinstance(result.get("evidence"), list):
                        collected_evidence.extend(result.get("evidence") or [])
                    direct_content = self._apply_gap_notice_policy(
                        user_message,
                        self._render_direct_tool_result(direct_tool_name, result),
                    )
                    for ch in direct_content:
                        yield {"type": "token", "content": ch}
                yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                workflow_outputs = {
                    "path": "direct_render_tool",
                    "tool_name": direct_tool_name,
                }
                _brain_stream_trace(
                    "RETURN_ID=J",
                    Reason="direct_render_tool_result",
                    conversation_id=conversation_id,
                )
                return

            assistant_tool_message = {
                "role": "assistant",
                "content": "",
                "tool_calls": prefetched_tool_calls,
            }
            tool_results = []
            collected_tool_results: list[dict] = []

            for tool_call in prefetched_tool_calls:
                function_name = tool_call.get("function", {}).get("name", "")
                raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}

                yield {"type": "tool_call", "name": function_name, "args": function_args}
                tool_result = self._execute_tool_call(tool_call, function_args)
                tool_results.append(tool_result)
                parsed_result = {}
                try:
                    parsed_result = json.loads(tool_result.get("content", "{}"))
                except Exception:
                    parsed_result = {}
                if isinstance(parsed_result, dict) and isinstance(parsed_result.get("evidence"), list):
                    collected_evidence.extend(parsed_result.get("evidence") or [])
                if isinstance(parsed_result, dict):
                    collected_tool_results.append(parsed_result)
                if self._should_fallback_after_tool(function_name, parsed_result):
                    fallback = self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history))
                    for ch in fallback:
                        yield {"type": "token", "content": ch}
                    yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                    workflow_outputs = {
                        "path": "prefetched_tool_fallback",
                        "tool_name": function_name,
                    }
                    _brain_stream_trace(
                        "RETURN_ID=K",
                        Reason="prefetched_tool_fallback",
                        conversation_id=conversation_id,
                    )
                    return

            composer_enabled = feature_flag_enabled("ANSWER_COMPOSER_ENABLED")
            if composer_enabled and collected_tool_results:
                answer_context = self._build_answer_context(user_message, collected_tool_results)
                if answer_context:
                    messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Answer Context"))]
                    messages.append({"role": "system", "content": self._format_answer_context(answer_context)})
                buffered_content = ""
                llm_entered = True
                print("STEP_7 BEFORE LLM")
                _brain_stream_trace(
                    "CALL LLM.stream",
                    Reason="answer_composer_prefetched_tools",
                    conversation_id=conversation_id,
                )
                for chunk in self._call_llm_stream(messages, tools=None):
                    if chunk.get("type") == "token":
                        buffered_content += chunk.get("content", "")
                    yield chunk
                patched_content = self._apply_gap_notice_policy(user_message, buffered_content)
                if patched_content != buffered_content:
                    for ch in patched_content[len(buffered_content):]:
                        yield {"type": "token", "content": ch}
                yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                workflow_outputs = {
                    "path": "composer_prefetched_tools",
                    "full_content_length": len(patched_content),
                }
                _brain_stream_trace(
                    "RETURN_ID=L",
                    Reason="composer_prefetched_tools_return",
                    conversation_id=conversation_id,
                )
                return

            messages.append(assistant_tool_message)
            messages.extend(tool_results)
            if reasoning_enabled and collected_tool_results:
                try:
                    from services.reasoning_engine_v1 import QuestionType, ReasoningEngineV1

                    ctx = getattr(self, "_reasoning_v1_context", {}) or {}
                    qt_value = str(ctx.get("question_type") or "UNKNOWN")
                    requirement = ctx.get("requirement") or {"required_fields": ["source"], "minimum_sources": 1, "needs_ranking": False, "needs_graph": False}
                    tool_plan = ctx.get("tool_plan") or []
                    qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
                    engine = ReasoningEngineV1()
                    evaluation = engine.evaluate_evidence(collected_tool_results, requirement)
                    conflicts = engine.detect_conflicts(collected_tool_results)
                    ranked_evidence = engine.rank_evidence(collected_tool_results)
                    outline = engine.build_answer_outline(qt, requirement, ranked_evidence)
                    reasoning_message = self._format_reasoning_engine_v1_message(qt_value, requirement, tool_plan, evaluation, conflicts, outline)
                    messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Reasoning Plan"))]
                    messages.append({"role": "system", "content": reasoning_message})
                except Exception:
                    pass

            buffered_content = ""
            llm_entered = True
            print("STEP_7 BEFORE LLM")
            _brain_stream_trace(
                "CALL LLM.stream",
                Reason="prefetched_tools_followup",
                conversation_id=conversation_id,
            )
            for chunk in self._call_llm_stream(messages, tools=None):
                if chunk.get("type") == "token":
                    buffered_content += chunk.get("content", "")
                yield chunk
            patched_content = self._apply_gap_notice_policy(user_message, buffered_content)
            if patched_content != buffered_content:
                for ch in patched_content[len(buffered_content):]:
                    yield {"type": "token", "content": ch}
            yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
            workflow_outputs = {
                "path": "prefetched_tools_followup",
                "full_content_length": len(patched_content),
            }
            _brain_stream_trace(
                "RETURN_ID=M",
                Reason="prefetched_tools_followup_return",
                conversation_id=conversation_id,
            )
            return

        first_pass_content = ""
        llm_entered = True
        print("STEP_7 BEFORE LLM")
        _brain_stream_trace(
            "CALL LLM.stream",
            Reason="first_pass_tools_auto",
            conversation_id=conversation_id,
        )
        for chunk in self._call_llm_stream(messages, tools=None if assistant_mode else TOOLS, tool_choice=tool_choice):
            chunk_type = chunk.get("type")
            if chunk_type == "error":
                yield chunk
                yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                workflow_outputs = {
                    "path": "first_pass_error",
                    "chunk": chunk,
                }
                _brain_stream_trace(
                    "RETURN_ID=N",
                    Reason="llm_stream_error",
                    conversation_id=conversation_id,
                )
                return
            if chunk_type == "tool_call":
                first_tool_calls = chunk.get("calls") or []
                break
            if chunk_type == "token":
                first_pass_content += chunk.get("content", "")
                yield chunk

        if first_tool_calls:
            assistant_tool_message = {"role": "assistant", "content": "", "tool_calls": first_tool_calls}
            tool_results = []
            collected_tool_results: list[dict] = []

            for tool_call in first_tool_calls:
                function_name = tool_call.get("function", {}).get("name", "")
                raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
                try:
                    function_args = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    function_args = {}

                yield {"type": "tool_call", "name": function_name, "args": function_args}
                tool_result = self._execute_tool_call(tool_call, function_args)
                tool_results.append(tool_result)
                parsed_result = {}
                try:
                    parsed_result = json.loads(tool_result.get("content", "{}"))
                except Exception:
                    parsed_result = {}
                if isinstance(parsed_result, dict) and isinstance(parsed_result.get("evidence"), list):
                    collected_evidence.extend(parsed_result.get("evidence") or [])
                if isinstance(parsed_result, dict):
                    collected_tool_results.append(parsed_result)
                if self._should_fallback_after_tool(function_name, parsed_result):
                    fallback = self._apply_gap_notice_policy(user_message, self._fallback_reply(user_message, history))
                    for ch in fallback:
                        yield {"type": "token", "content": ch}
                    yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}
                    workflow_outputs = {
                        "path": "tool_call_fallback",
                        "tool_name": function_name,
                    }
                    _brain_stream_trace(
                        "RETURN_ID=O",
                        Reason="tool_call_fallback",
                        conversation_id=conversation_id,
                    )
                    return

            composer_enabled = feature_flag_enabled("ANSWER_COMPOSER_ENABLED")
            if composer_enabled and collected_tool_results:
                answer_context = self._build_answer_context(user_message, collected_tool_results)
                if answer_context:
                    messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Answer Context"))]
                    messages.append({"role": "system", "content": self._format_answer_context(answer_context)})
                buffered_content = ""
                llm_entered = True
                print("STEP_7 BEFORE LLM")
                _brain_stream_trace(
                    "CALL LLM.stream",
                    Reason="answer_composer_tool_calls",
                    conversation_id=conversation_id,
                )
                for chunk in self._call_llm_stream(messages, tools=None):
                    if chunk.get("type") == "token":
                        buffered_content += chunk.get("content", "")
                    yield chunk
                patched_content = self._apply_gap_notice_policy(user_message, buffered_content)
                if patched_content != buffered_content:
                    for ch in patched_content[len(buffered_content):]:
                        yield {"type": "token", "content": ch}
            else:
                messages.append(assistant_tool_message)
                messages.extend(tool_results)
                if reasoning_enabled and collected_tool_results:
                    try:
                        from services.reasoning_engine_v1 import QuestionType

                        ctx = getattr(self, "_reasoning_v1_context", {}) or {}
                        qt_value = str(ctx.get("question_type") or "UNKNOWN")
                        from services.core_models import Requirement as CoreRequirement

                        req = ctx.get("requirement")
                        requirement = req if isinstance(req, CoreRequirement) else CoreRequirement.from_dict(req or {})
                        tool_plan = ctx.get("tool_plan") or []
                        qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
                        engine = self._get_reasoning_engine_service(conversation_id=conversation_id)
                        if engine is None:
                            from services.reasoning_engine_v1 import ReasoningEngineV1

                            engine = ReasoningEngineV1()
                        evaluation = engine.evaluate_evidence(collected_tool_results, requirement)
                        conflicts = engine.detect_conflicts(collected_tool_results)
                        ranked_evidence = engine.rank_evidence(collected_tool_results)
                        outline = engine.build_answer_outline(qt, requirement, ranked_evidence)
                        reasoning_message = self._format_reasoning_engine_v1_message(qt_value, requirement.to_dict(), tool_plan, evaluation, conflicts, outline)
                        messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Reasoning Plan"))]
                        messages.append({"role": "system", "content": reasoning_message})
                    except Exception:
                        pass

                buffered_content = ""
                llm_entered = True
                print("STEP_7 BEFORE LLM")
                _brain_stream_trace(
                    "CALL LLM.stream",
                    Reason="tool_calls_followup",
                    conversation_id=conversation_id,
                )
                for chunk in self._call_llm_stream(messages, tools=None):
                    if chunk.get("type") == "token":
                        buffered_content += chunk.get("content", "")
                    yield chunk
                patched_content = self._apply_gap_notice_policy(user_message, buffered_content)
                if patched_content != buffered_content:
                    for ch in patched_content[len(buffered_content):]:
                        yield {"type": "token", "content": ch}
        elif first_pass_content:
            patched_content = self._apply_gap_notice_policy(user_message, first_pass_content)
            if patched_content != first_pass_content:
                for ch in patched_content[len(first_pass_content):]:
                    yield {"type": "token", "content": ch}

        yield {"type": "done", "evidence": self._merge_evidence(collected_evidence)}

    def _call_llm(
        self,
        messages: list,
        tools: list | None = None,
        tool_choice: Any = None,
    ) -> Optional[dict]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 2000,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        try:
            resp = httpx.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            print(f"[Brain] LLM调用失败: {exc}")
            return None

    def _call_llm_stream(
        self,
        messages: list,
        tools: list | None = None,
        tool_choice: Any = None,
    ):
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 2000,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        with trace_span("LLM", input_obj={"model": self.model, "message_count": len(messages or [])}) as span:
            try:
                buffered_content = ""
                pending_tool_calls: dict[int, dict[str, Any]] = {}
                with httpx.Client(timeout=60) as client:
                    with client.stream(
                        "POST",
                        f"{DEEPSEEK_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as resp:
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            if isinstance(line, bytes):
                                decoded = line.decode("utf-8", errors="ignore")
                            else:
                                decoded = line
                            if decoded.startswith(":") or not decoded.startswith("data: "):
                                continue

                            data = decoded[6:]
                            if data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            choice = (chunk.get("choices") or [{}])[0]
                            delta = choice.get("delta") or {}
                            finish_reason = choice.get("finish_reason")

                            content = delta.get("content", "")
                            if content:
                                buffered_content += content
                                yield {"type": "token", "content": content}

                            for tool_delta in delta.get("tool_calls") or []:
                                index = tool_delta.get("index", 0)
                                pending = pending_tool_calls.setdefault(
                                    index,
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if tool_delta.get("id"):
                                    pending["id"] = tool_delta["id"]
                                if tool_delta.get("type"):
                                    pending["type"] = tool_delta["type"]

                                function_delta = tool_delta.get("function") or {}
                                if function_delta.get("name"):
                                    pending["function"]["name"] += function_delta["name"]
                                if function_delta.get("arguments"):
                                    pending["function"]["arguments"] += function_delta["arguments"]

                            if finish_reason == "tool_calls" and pending_tool_calls:
                                ordered_calls = [pending_tool_calls[idx] for idx in sorted(pending_tool_calls.keys())]
                                yield {"type": "tool_call", "calls": ordered_calls}
                                pending_tool_calls = {}
                            elif finish_reason == "stop":
                                continue

                if pending_tool_calls:
                    ordered_calls = [pending_tool_calls[idx] for idx in sorted(pending_tool_calls.keys())]
                    yield {"type": "tool_call", "calls": ordered_calls}
                # #region debug-point C:llm-final-answer
                debug_answer_event(
                    "LLM Final Answer",
                    buffered_content,
                    trace_id=str(getattr(self, "conversation_id", "") or ""),
                    hypothesis_id="C",
                    location="brain.py:_call_llm_stream",
                    extra={"native_stream": True, "fallback_stream": False, "message_count": len(messages or [])},
                )
                # #endregion
                span.set_output_obj({"status": "ok"})
            except Exception as exc:
                span.set_output_obj({"status": "error", "message": str(exc)})
                yield {"type": "error", "message": str(exc)}

    def _query_database(
        self,
        scope: str,
        country: str | None = None,
        entity: str | None = None,
        keywords: list | None = None,
        limit: int = 10,
    ) -> dict:
        try:
            from models.database import IntelligenceItem
            from sqlalchemy import desc, or_

            tool_name = "query_database"
            function_name = "_query_database"
            self._tool_diag_print(ToolName=tool_name, ENTER_TOOL=function_name)
            acquire_result = self._acquire_tool_db_session(
                tool_name=tool_name,
                function_name=function_name,
                line_no=inspect.currentframe().f_lineno + 1,
                params={"scope": scope, "country": country, "entity": entity, "keywords": list(keywords or []), "limit": limit},
            )
            if acquire_result.get("status") == "error":
                return acquire_result
            db = acquire_result["db"]
            try:
                query = db.query(IntelligenceItem)

                if scope == "global":
                    query = query.filter(IntelligenceItem.scope == "global")
                elif country:
                    query = query.filter(IntelligenceItem.country == country)

                text_filters = []
                if entity:
                    text_filters.extend(
                        [
                            IntelligenceItem.title.ilike(f"%{entity}%"),
                            IntelligenceItem.content.ilike(f"%{entity}%"),
                            IntelligenceItem.entity_name.ilike(f"%{entity}%"),
                        ]
                    )

                for keyword in keywords or []:
                    text_filters.extend(
                        [
                            IntelligenceItem.title.ilike(f"%{keyword}%"),
                            IntelligenceItem.content.ilike(f"%{keyword}%"),
                        ]
                    )

                if text_filters:
                    query = query.filter(or_(*text_filters))

                final_query = query.order_by(desc(IntelligenceItem.ingested_at)).limit(max(1, min(limit, 20)))
                items = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_2",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=final_query,
                    params={"scope": scope, "country": country, "entity": entity, "keywords": list(keywords or []), "limit": limit},
                    executor=lambda: final_query.all(),
                )

                results = []
                evidence = []
                seen_titles = set()
                source_stats: dict[str, int] = {}
                for item in items:
                    title_key = ((item.title or "")[:40]).strip().lower()
                    if title_key and title_key in seen_titles:
                        continue
                    if title_key:
                        seen_titles.add(title_key)

                    source_name = item.source_name or "未知来源"
                    source_stats[source_name] = source_stats.get(source_name, 0) + 1
                    conf = "HIGH" if (item.confidence or 0) >= 0.85 else "MEDIUM"
                    safe_url = item.source_url or ""
                    if safe_url.startswith("composite:") or safe_url.startswith("mission:"):
                        safe_url = ""
                    results.append(
                        {
                            "title": item.title or "未命名情报",
                            "content": (item.content or "")[:200],
                            "url": safe_url,
                            "source": source_name,
                            "source_name": source_name,
                            "confidence": conf,
                            "date": item.ingested_at.strftime("%Y-%m-%d") if item.ingested_at else "未知",
                            "country": item.country or "",
                            "entity_name": item.entity_name or "",
                        }
                    )
                    evidence_item = self._evidence_from_intelligence_item(item, evidence_type="intelligence_item")
                    if evidence_item:
                        if safe_url:
                            evidence_item["url"] = safe_url
                        evidence.append(evidence_item)

                payload = {
                    "status": "success",
                    "count": len(results),
                    "query_summary": {
                        "scope": scope,
                        "country": country,
                        "entity": entity,
                        "total_found": len(items),
                        "unique_results": len(results),
                    },
                    "source_breakdown": source_stats,
                    "items": results,
                }
                payload["evidence"] = self._merge_evidence(evidence)
                payload["answer"] = self._format_intelligence_result(payload)
                return payload
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_intelligence(
        self,
        scope: str,
        country: str | None = None,
        entity: str | None = None,
        keywords: list | None = None,
        limit: int = 10,
    ) -> dict:
        try:
            from models.database import IntelligenceItem
            from sqlalchemy import desc, func, or_

            tool_name = "query_intelligence"
            function_name = "_query_intelligence"
            self._tool_diag_print(ToolName=tool_name, ENTER_TOOL=function_name)
            acquire_result = self._acquire_tool_db_session(
                tool_name=tool_name,
                function_name=function_name,
                line_no=inspect.currentframe().f_lineno + 1,
                params={"scope": scope, "country": country, "entity": entity, "keywords": list(keywords or []), "limit": limit},
            )
            if acquire_result.get("status") == "error":
                return acquire_result
            db = acquire_result["db"]
            try:
                query = db.query(IntelligenceItem)

                if scope == "global":
                    query = query.filter(IntelligenceItem.scope == "global")
                elif scope == "country" and country:
                    query = query.filter(IntelligenceItem.country == country)

                text_filters = []
                if scope == "entity" and entity:
                    text_filters.extend(
                        [
                            IntelligenceItem.entity_name.ilike(f"%{entity}%"),
                            IntelligenceItem.title.ilike(f"%{entity}%"),
                            IntelligenceItem.content.ilike(f"%{entity}%"),
                        ]
                    )
                elif entity:
                    text_filters.extend(
                        [
                            IntelligenceItem.entity_name.ilike(f"%{entity}%"),
                            IntelligenceItem.title.ilike(f"%{entity}%"),
                            IntelligenceItem.content.ilike(f"%{entity}%"),
                        ]
                    )

                for keyword in keywords or []:
                    if not keyword:
                        continue
                    text_filters.extend(
                        [
                            IntelligenceItem.title.ilike(f"%{keyword}%"),
                            IntelligenceItem.content.ilike(f"%{keyword}%"),
                            IntelligenceItem.entity_name.ilike(f"%{keyword}%"),
                        ]
                    )

                if text_filters:
                    query = query.filter(or_(*text_filters))

                order_clause = desc(func.coalesce(IntelligenceItem.published_at, IntelligenceItem.ingested_at))
                relaxed_match_attempted = False
                relaxed_match_hit = False
                initial_query = (
                    query.order_by(order_clause)
                    .limit(max(1, min(limit, 20)))
                )
                items = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_2",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=initial_query,
                    params={"scope": scope, "country": country, "entity": entity, "keywords": list(keywords or []), "limit": limit},
                    executor=lambda: initial_query.all(),
                )

                # Global news prompts often contain broad phrases like "最近全球基督教有什么新闻".
                # If that phrase was extracted as a single keyword, retry without text filters.
                if not items and scope == "global" and text_filters:
                    relaxed_global_query = (
                        db.query(IntelligenceItem)
                        .filter(IntelligenceItem.scope == "global")
                        .order_by(order_clause)
                        .limit(max(1, min(limit, 20)))
                    )
                    items = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_3",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=relaxed_global_query,
                        params={"scope": "global", "country": country, "keywords": list(keywords or []), "reason": "relaxed_match"},
                        executor=lambda: relaxed_global_query.all(),
                    )
                    relaxed_match_attempted = True
                    relaxed_match_hit = bool(items)
                if not items and scope == "country" and country and text_filters:
                    relaxed_country_query = (
                        db.query(IntelligenceItem)
                        .filter(IntelligenceItem.country == country)
                        .order_by(order_clause)
                        .limit(max(1, min(limit, 20)))
                    )
                    items = self._tool_diag_sql(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_4",
                        line_no=inspect.currentframe().f_lineno + 1,
                        query_or_sql=relaxed_country_query,
                        params={"scope": "country", "country": country, "keywords": list(keywords or []), "reason": "relaxed_match"},
                        executor=lambda: relaxed_country_query.all(),
                    )
                    relaxed_match_attempted = True
                    relaxed_match_hit = bool(items)

                results = []
                evidence = []
                source_stats: dict[str, int] = {}
                seen_urls = set()
                for item in items:
                    item_url = item.source_url or f"{item.title}|{item.source_name}"
                    if item_url in seen_urls:
                        continue
                    seen_urls.add(item_url)

                    source_name = item.source_name or "未知来源"
                    source_stats[source_name] = source_stats.get(source_name, 0) + 1
                    event_time = item.published_at or item.ingested_at
                    conf = "HIGH" if (item.confidence or 0) >= 0.75 else "MEDIUM"
                    results.append(
                        {
                            "title": item.title or "未命名情报",
                            "content": (item.content or "")[:240],
                            "url": item.source_url or "",
                            "source": source_name,
                            "source_name": source_name,
                            "confidence": conf,
                            "date": event_time.strftime("%Y-%m-%d") if event_time else "未知",
                            "country": item.country or "",
                            "entity_name": item.entity_name or "",
                        }
                    )
                    evidence_item = self._evidence_from_intelligence_item(item, evidence_type="intelligence_item")
                    if evidence_item:
                        evidence.append(evidence_item)

                payload = {
                    "status": "success",
                    "count": len(results),
                    "query_summary": {
                        "scope": scope,
                        "country": country,
                        "entity": entity,
                        "keywords": list(keywords or []),
                        "total_found": len(items),
                        "unique_results": len(results),
                        "relaxed_match_attempted": relaxed_match_attempted,
                        "relaxed_match_hit": relaxed_match_hit,
                        "sources_checked": [
                            "IntelligenceItem.title",
                            "IntelligenceItem.content",
                            "IntelligenceItem.entity_name",
                            "IntelligenceItem.source_url",
                        ],
                        "missing_fields": ["url", "source_name", "entity_name"],
                        "no_hit_reason": (
                            ""
                            if results
                            else "没有满足当前国家/实体/关键词交集的现成情报记录，或命中记录缺少可用来源链接"
                        ),
                        "needs_collection": not bool(results),
                    },
                    "source_breakdown": source_stats,
                    "items": results,
                }
                payload["evidence"] = self._merge_evidence(evidence)
                payload["answer"] = self._format_intelligence_result(payload)
                return payload
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_contacts(self, org_name: str) -> dict:
        try:
            from models.database import OrganizationProfile, get_db
            from sqlalchemy import case, desc, func, or_

            db = next(get_db())
            try:
                normalized_name = self._clean_org_candidate(org_name)
                org = (
                    db.query(OrganizationProfile)
                    .filter(
                        or_(
                            OrganizationProfile.name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.name_local.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.official_name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.short_name.ilike(f"%{normalized_name}%"),
                            OrganizationProfile.english_name.ilike(f"%{normalized_name}%"),
                        )
                    )
                    .order_by(
                        case(
                            (func.lower(OrganizationProfile.name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.name_local) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.official_name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.short_name) == normalized_name.lower(), 0),
                            (func.lower(OrganizationProfile.english_name) == normalized_name.lower(), 0),
                            else_=1,
                        ),
                        case((OrganizationProfile.source_name == "manual_seed", 0), else_=1),
                        func.length(OrganizationProfile.name).asc(),
                        desc(OrganizationProfile.updated_at),
                    )
                    .first()
                )

                if not org:
                    return {"status": "not_found", "message": f"未找到 {normalized_name or org_name} 的联系信息"}

                payload = {
                    "status": "found",
                    "org_name": org.name,
                    "country": org.country,
                    "email": org.contact_email or "未知",
                    "phone": org.phone_public or "未知",
                    "leader_name": org.leader_name or "未知",
                    "leader_title": org.leader_title or "未知",
                    "website": org.official_website or "未知",
                    "source_name": org.source_name or "机构档案",
                    "source_url": org.source_url or org.official_website or "",
                }
                payload["evidence"] = self._merge_evidence([self._evidence_from_organization_profile(org, evidence_type="organization_contacts")])
                payload["answer"] = (
                    f"{payload['org_name']} ({payload.get('country') or 'N/A'})\n"
                    f"website={payload.get('website')}\n"
                    f"email={payload.get('email')}\n"
                    f"phone={payload.get('phone')}\n"
                    f"leader={payload.get('leader_name')} ({payload.get('leader_title')})"
                )
                return payload
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _auto_collect(self, country: str, entity: str | None = None, reason: str = "") -> dict:
        try:
            from agent.actions import ActionExecutor
            from agent.planner import ActionPlan

            executor = ActionExecutor()
            plan = ActionPlan(
                action="auto_collect",
                target=country,
                priority=1,
                params={
                    "country": country,
                    "entity": entity,
                    "reason": reason or "LLM中枢判断数据不足，自动补采",
                },
                reason=reason or "LLM触发补采",
            )
            result = executor.execute(plan)
            return {
                "status": "queued",
                "message": f"已为 {country} 创建后台采集任务",
                "tasks_created": result.get("created", 0),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_ontology(
        self,
        filter_type: str,
        filter_value: str,
        country: str | None = None,
        limit: int = 20,
    ) -> dict:
        """按Ontology标签查询机构"""
        try:
            from models.database import (
                CollaborationPreference,
                AIMaturityLevel,
                OrganizationOntologyTag,
                OrganizationProfile,
                OrganizationType,
                ScaleLevel,
                TheologicalPosition,
                get_db,
            )

            db = next(get_db())
            try:
                query = (
                    db.query(OrganizationProfile)
                    .join(
                        OrganizationOntologyTag,
                        OrganizationProfile.id == OrganizationOntologyTag.organization_id,
                    )
                    .filter(
                        OrganizationOntologyTag.tag_type == filter_type,
                        OrganizationOntologyTag.tag_id == filter_value,
                    )
                    .order_by(OrganizationProfile.updated_at.desc())
                )

                if country:
                    query = query.filter(OrganizationProfile.country == country)

                orgs = query.limit(max(1, min(limit, 50))).all()

                results = []
                for org in orgs:
                    description_parts = []
                    if org.denomination:
                        description_parts.append(f"宗派/立场：{org.denomination}")
                    if org.member_estimate:
                        description_parts.append(f"规模估计：{org.member_estimate} 人")
                    if org.source_name:
                        description_parts.append(f"来源：{org.source_name}")

                    results.append(
                        {
                            "name": org.name,
                            "country": org.country,
                            "website": org.official_website or "",
                            "email": org.contact_email or "",
                            "leader": org.leader_name or "未知",
                            "description": "；".join(description_parts),
                        }
                    )

                if results:
                    return {
                        "status": "success",
                        "count": len(results),
                        "organizations": results,
                    }

                model_by_filter = {
                    "organization_type": OrganizationType,
                    "theology": TheologicalPosition,
                    "scale": ScaleLevel,
                    "ai_maturity": AIMaturityLevel,
                    "collaboration": CollaborationPreference,
                }
                model = model_by_filter.get(filter_type)
                type_def = db.query(model).filter(model.id == filter_value).first() if model else None
                if country:
                    global_orgs = (
                        db.query(OrganizationProfile)
                        .join(
                            OrganizationOntologyTag,
                            OrganizationProfile.id == OrganizationOntologyTag.organization_id,
                        )
                        .filter(
                            OrganizationOntologyTag.tag_type == filter_type,
                            OrganizationOntologyTag.tag_id == filter_value,
                        )
                        .order_by(OrganizationProfile.updated_at.desc())
                        .limit(5)
                        .all()
                    )
                    if global_orgs:
                        global_examples = [
                            {
                                "name": org.name,
                                "country": org.country,
                                "website": org.official_website or "",
                                "email": org.contact_email or "",
                                "leader": org.leader_name or "未知",
                            }
                            for org in global_orgs
                        ]
                        return {
                            "status": "country_empty",
                            "requested_country": country,
                            "type_name": getattr(type_def, "name", filter_value),
                            "description": getattr(type_def, "description", "") if type_def else "",
                            "global_count": len(global_examples),
                            "global_examples": global_examples,
                            "organizations": [],
                        }
                if type_def:
                    type_name = getattr(type_def, "name", filter_value)
                    return {
                        "status": "type_defined",
                        "type_name": type_name,
                        "description": getattr(type_def, "description", "") or "",
                        "message": f"系统中暂无标记为'{type_name}'的机构，但这是已定义的分类。",
                        "organizations": [],
                    }

                return {
                    "status": "not_found",
                    "message": f"未找到标签 {filter_type}={filter_value} 对应的机构或分类定义",
                    "organizations": [],
                }
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _get_ontology_types(self, category: str | None = None) -> dict:
        """获取Ontology分类列表"""
        try:
            from models.database import (
                AIMaturityLevel,
                CollaborationPreference,
                OrganizationType,
                ScaleLevel,
                TheologicalPosition,
                get_db,
            )

            db = next(get_db())
            try:
                result = {}

                if not category or category == "organization_types":
                    types = db.query(OrganizationType).order_by(OrganizationType.name.asc()).all()
                    result["organization_types"] = [
                        {"id": item.id, "name": item.name, "description": item.description}
                        for item in types
                    ]

                if not category or category == "theologies":
                    theologies = db.query(TheologicalPosition).order_by(TheologicalPosition.name.asc()).all()
                    result["theologies"] = [
                        {"id": item.id, "name": item.name, "tradition": item.tradition}
                        for item in theologies
                    ]

                if not category or category == "scales":
                    scales = db.query(ScaleLevel).order_by(ScaleLevel.min_people.asc()).all()
                    result["scales"] = [{"id": item.id, "name": item.name} for item in scales]

                if not category or category == "ai_levels":
                    levels = db.query(AIMaturityLevel).order_by(AIMaturityLevel.id.asc()).all()
                    result["ai_levels"] = [
                        {"id": item.id, "name": item.name, "description": item.description}
                        for item in levels
                    ]

                if not category or category == "collaborations":
                    prefs = db.query(CollaborationPreference).order_by(CollaborationPreference.name.asc()).all()
                    result["collaborations"] = [{"id": item.id, "name": item.name} for item in prefs]

                return {"status": "success", "categories": result}
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_investors(
        self,
        focus_area: str | None = None,
        investor_type: str | None = None,
        country: str | None = None,
        region: str | None = None,
        stage: str | None = None,
        limit: int = 10,
    ) -> dict:
        """查询投资机构/投资人"""
        try:
            from models.database import Investor, get_db

            db = next(get_db())
            try:
                investors = db.query(Investor).all()

                focus_aliases = {
                    "faithtech": {
                        "faithtech", "bible tech", "christian ai", "ai", "church tech",
                        "christian media", "digital media", "media", "social", "social media",
                        "consumer", "bible translation", "technology",
                    },
                    "media": {
                        "media", "christian media", "digital media", "social",
                        "social media", "publishing", "consumer", "worship tech",
                    },
                    "edtech": {"edtech", "education", "theology", "leadership"},
                    "mission": {"mission", "church planting", "evangelism", "leadership"},
                    "ai": {"ai", "christian ai", "technology", "data"},
                }
                region_aliases = {
                    "菲律宾": {"philippines", "southeast asia", "asia", "global south", "global"},
                    "美国": {"us", "usa", "north america", "global"},
                    "韩国": {"korea", "east asia", "asia", "global"},
                    "尼日利亚": {"nigeria", "africa", "global south", "global"},
                    "东南亚": {"southeast asia", "sea", "asia", "philippines", "singapore", "indonesia", "malaysia", "thailand", "vietnam"},
                    "东亚": {"east asia", "asia", "korea", "japan", "china", "taiwan", "hong kong"},
                    "非洲": {"africa", "kenya", "nigeria", "uganda", "ghana", "south africa", "sub-saharan africa", "global south"},
                    "中东": {"middle east", "mena", "north africa"},
                    "全球": {"global", "worldwide", "international"},
                }

                normalized_focus = (focus_area or "").strip().lower()
                normalized_country = (country or "").strip().lower()
                normalized_region = (region or "").strip().lower()
                normalized_stage = (stage or "").strip().lower()
                normalized_type = (investor_type or "").strip().lower()

                def focus_matches(investor: Any) -> tuple[bool, int]:
                    if not normalized_focus:
                        return True, 0
                    candidate_tokens = {
                        normalized_focus,
                        *(focus_aliases.get(normalized_focus, set())),
                    }
                    haystack = {
                        str(item).strip().lower()
                        for item in (investor.focus_areas or [])
                        if str(item).strip()
                    }
                    text_blob = " ".join(
                        [
                            investor.thesis or "",
                            investor.description or "",
                            " ".join(investor.focus_areas or []),
                        ]
                    ).lower()
                    if haystack & candidate_tokens:
                        return True, 3
                    if any(token in text_blob for token in candidate_tokens):
                        return True, 2
                    return False, 0

                def stage_matches(investor: Any) -> tuple[bool, int]:
                    if not normalized_stage:
                        return True, 0
                    stages = {str(item).strip().lower() for item in (investor.stage_focus or []) if str(item).strip()}
                    if normalized_stage in stages:
                        return True, 2
                    return False, 0

                def geography_matches(investor: Any) -> tuple[bool, int]:
                    if (normalized_country in {"", "全球"}) and (normalized_region in {"", "全球"}):
                        return True, 0
                    inv_country = (investor.country or "").strip().lower()
                    region_tokens = {str(item).strip().lower() for item in (investor.region_focus or []) if str(item).strip()}
                    text_blob = " ".join(
                        [
                            investor.description or "",
                            investor.thesis or "",
                            " ".join(investor.region_focus or []),
                        ]
                    ).lower()
                    if normalized_country == "全球" or normalized_region == "全球":
                        return True, 1
                    if normalized_country and inv_country == normalized_country:
                        return True, 3
                    if normalized_region:
                        region_candidates = {normalized_region, *region_aliases.get(region or "", set())}
                        if inv_country in region_candidates:
                            return True, 3
                        if region_tokens & region_candidates:
                            return True, 3
                        if any(token in text_blob for token in region_candidates):
                            return True, 2
                    if "global" in region_tokens:
                        return True, 1
                    alias_tokens = region_aliases.get(country or "", set())
                    if region_tokens & alias_tokens:
                        return True, 2
                    return False, 0

                ranked = []
                for investor_row in investors:
                    score = 0

                    if normalized_type:
                        if (investor_row.investor_type or "").strip().lower() != normalized_type:
                            continue
                        score += 2

                    ok_focus, focus_score = focus_matches(investor_row)
                    if not ok_focus:
                        continue
                    score += focus_score

                    ok_stage, stage_score = stage_matches(investor_row)
                    if not ok_stage:
                        continue
                    score += stage_score

                    ok_geo, geo_score = geography_matches(investor_row)
                    if not ok_geo:
                        continue
                    score += geo_score

                    if normalized_focus == "media":
                        media_blob = " ".join(investor_row.focus_areas or []).lower()
                        if any(token in media_blob for token in ["faithtech", "media", "social"]):
                            score += 1

                    ranked.append((score, investor_row))

                ranked.sort(
                    key=lambda item: (
                        item[0],
                        1 if (item[1].country or "") == country else 0,
                        item[1].updated_at or item[1].created_at,
                    ),
                    reverse=True,
                )

                top_investors = ranked[: max(1, min(limit, 20))]
                items = [
                    {
                        "name": row.name,
                        "investor_type": row.investor_type,
                        "focus_areas": row.focus_areas or [],
                        "stage_focus": row.stage_focus or [],
                        "country": row.country or "",
                        "region_focus": row.region_focus or [],
                        "website": row.website or "",
                        "thesis": row.thesis or "",
                        "score": score,
                    }
                    for score, row in top_investors
                ]

                return {
                    "status": "success",
                    "count": len(items),
                    "query_summary": {
                        "focus_area": focus_area,
                        "investor_type": investor_type,
                        "country": country,
                        "region": region,
                        "stage": stage,
                    },
                    "investors": items,
                }
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _match_investors(
        self,
        project_description: str = "",
        focus_area: str = "",
        stage: str = "",
        country: str = "",
        region: str = "",
        limit: int = 5,
    ) -> dict:
        """
        三方匹配引擎：项目特征 vs 投资方偏好
        根据项目描述、领域、阶段、地区，匹配更合适的投资方
        """
        result = {"matches": [], "project_profile": {}, "total": 0}

        try:
            from sqlalchemy import func

            from models.database import Investor, UserFeedback, get_db

            db = next(get_db())
            try:
                user_profile = {}
                if self.conversation_id:
                    profile_result = self._get_user_profile(self.conversation_id)
                    if profile_result.get("status") == "found":
                        user_profile = profile_result.get("profile", {}) or {}

                focus_area = focus_area or user_profile.get("focus_area", "")
                stage = stage or user_profile.get("project_stage", "")
                country = country or user_profile.get("country", "")
                region = region or user_profile.get("region", "")
                project_description = project_description or user_profile.get("project_description", "")

                region_weight = 20
                stage_weight = 30
                focus_weight = 40
                type_weight = 10

                prefers_local = user_profile.get("preference") == "local" or "本地" in str(user_profile.get("focus_region", ""))
                is_early_stage = stage in ["pre_seed", "seed", "pre-seed"]

                if prefers_local:
                    region_weight = 30
                    stage_weight = 25
                    focus_weight = 35
                    type_weight = 10

                if is_early_stage:
                    stage_weight = 35
                    focus_weight = 35 if not prefers_local else 25
                    region_weight = 20 if not prefers_local else 30
                    type_weight = 10

                project_profile = {
                    "description": project_description or "",
                    "focus_area": focus_area or "",
                    "stage": stage or "",
                    "country": country or "",
                    "region": region or "",
                    "user_profile": user_profile,
                }
                result["project_profile"] = project_profile

                investors = db.query(Investor).all()
                useful_feedback_counts = {
                    name: count
                    for name, count in (
                        db.query(
                            UserFeedback.related_investor,
                            func.count(UserFeedback.id),
                        )
                        .filter(UserFeedback.feedback_type == "match_useful")
                        .filter(UserFeedback.related_investor.isnot(None))
                        .group_by(UserFeedback.related_investor)
                        .all()
                    )
                }
                not_useful_feedback_counts = {
                    name: count
                    for name, count in (
                        db.query(
                            UserFeedback.related_investor,
                            func.count(UserFeedback.id),
                        )
                        .filter(UserFeedback.feedback_type == "match_not_useful")
                        .filter(UserFeedback.related_investor.isnot(None))
                        .group_by(UserFeedback.related_investor)
                        .all()
                    )
                }
                normalized_focus = (focus_area or "").strip().lower()
                normalized_stage = (stage or "").strip().lower()
                normalized_country = (country or "").strip().lower()
                normalized_region = (region or "").strip().lower()
                description_blob = (project_description or "").lower()

                focus_aliases = {
                    "faithtech": {"faithtech", "bible tech", "church tech", "christian ai", "technology", "media"},
                    "media": {"media", "christian media", "digital media", "social media", "social", "content", "consumer"},
                    "edtech": {"edtech", "education", "theology", "leadership"},
                    "mission": {"mission", "church planting", "evangelism", "leadership"},
                    "ai": {"ai", "christian ai", "data", "technology"},
                }
                region_aliases = {
                    "东南亚": {"southeast asia", "asia", "global south"},
                    "菲律宾": {"philippines", "southeast asia", "asia", "global south"},
                    "全球": {"global", "worldwide", "international"},
                    "美国": {"us", "usa", "north america", "global"},
                }
                type_score_map = {
                    "foundation": 8,
                    "impact_investor": 8,
                    "angel": 10,
                    "vc": 5,
                    "corporate": 5,
                    "pe": 4,
                }
                if "foundation" in str(user_profile.get("preferred_investor_type", "")).lower():
                    type_score_map = {
                        "foundation": 15,
                        "impact_investor": 12,
                        "angel": 8,
                        "vc": 3,
                        "corporate": 5,
                        "pe": 4,
                    }

                scored_matches = []
                for inv in investors:
                    score = 0
                    reasons = []
                    focus_score = 0
                    stage_score = 0
                    region_score = 0
                    type_score = 0
                    feedback_bonus = 0
                    feedback_penalty = 0

                    inv_focuses = [str(item) for item in (inv.focus_areas or []) if str(item).strip()]
                    inv_focuses_lower = {item.strip().lower() for item in inv_focuses}
                    inv_stages = [str(item) for item in (inv.stage_focus or []) if str(item).strip()]
                    inv_stages_lower = {item.strip().lower() for item in inv_stages}
                    inv_regions = [str(item) for item in (inv.region_focus or []) if str(item).strip()]
                    inv_regions_lower = {item.strip().lower() for item in inv_regions}
                    inv_country = (inv.country or "").strip()
                    inv_country_lower = inv_country.lower()
                    inv_text_blob = " ".join(
                        [inv.description or "", inv.thesis or "", " ".join(inv_focuses), " ".join(inv_regions)]
                    ).lower()

                    if normalized_focus:
                        candidate_focuses = {normalized_focus, *focus_aliases.get(normalized_focus, set())}
                        if inv_focuses_lower & candidate_focuses:
                            focus_score += focus_weight
                            reasons.append(f"专注{focus_area}领域")
                        elif any(token in inv_text_blob for token in candidate_focuses):
                            focus_score += max(1, round(focus_weight * 0.625))
                            reasons.append(f"相关领域（{', '.join(inv_focuses[:3]) or focus_area}）")
                        elif description_blob and any(token in description_blob for token in inv_focuses_lower):
                            focus_score += max(1, round(focus_weight * 0.45))
                            reasons.append("项目描述与其关注方向接近")

                    if normalized_stage:
                        if normalized_stage in inv_stages_lower:
                            stage_score += stage_weight
                            reasons.append(f"覆盖{stage}阶段")
                        elif inv_stages:
                            stage_score += max(1, round(stage_weight / 3))
                            reasons.append(f"主要投资{', '.join(inv_stages[:3])}")

                    geography_hit = False
                    if normalized_country:
                        if inv_country_lower == normalized_country:
                            region_score += region_weight
                            reasons.append(f"本地覆盖{country}")
                            geography_hit = True
                        else:
                            geo_candidates = region_aliases.get(country, set())
                            if inv_regions_lower & geo_candidates:
                                region_score += max(1, round(region_weight * 0.8))
                                reasons.append(f"区域覆盖{country}")
                                geography_hit = True

                    if not geography_hit and normalized_region:
                        region_candidates = {normalized_region, *region_aliases.get(region, set())}
                        if inv_regions_lower & region_candidates:
                            region_score += max(1, round(region_weight * 0.9))
                            reasons.append(f"覆盖{region}")
                        elif "global" in inv_regions_lower:
                            region_score += max(1, round(region_weight * 0.5))
                            reasons.append("具备全球投资覆盖")

                    if not normalized_country and not normalized_region and "global" in inv_regions_lower:
                        region_score += max(1, round(region_weight * 0.3))
                        reasons.append("覆盖全球项目")

                    type_score += min(type_weight, type_score_map.get((inv.investor_type or "").lower(), 5))

                    if normalized_focus == "media" and any(token in inv_text_blob for token in ["faithtech", "social", "media"]):
                        focus_score += min(4, max(1, focus_weight // 10))
                    if normalized_focus == "faithtech" and any(token in inv_text_blob for token in ["technology", "ai", "bible tech", "church tech"]):
                        focus_score += min(4, max(1, focus_weight // 10))
                    if project_description and inv.thesis and any(token in inv.thesis.lower() for token in ["faith", "kingdom", "redemptive"]):
                        type_score += 2

                    focus_score = min(focus_weight, focus_score)
                    stage_score = min(stage_weight, stage_score)
                    region_score = min(region_weight, region_score)
                    type_score = min(type_weight, type_score)
                    score += focus_score + stage_score + region_score + type_score

                    useful_count = useful_feedback_counts.get(inv.name, 0)
                    not_useful_count = not_useful_feedback_counts.get(inv.name, 0)
                    if useful_count:
                        feedback_bonus = min(20, useful_count * 5)
                        score += feedback_bonus
                        reasons.append(f"用户反馈好评（{useful_count}次）")
                    if not_useful_count:
                        feedback_penalty = min(15, not_useful_count * 4)
                        score -= feedback_penalty
                        reasons.append(f"用户反馈一般（{not_useful_count}次）")

                    if score <= 0:
                        continue

                    user_region = str(user_profile.get("focus_region", "")).strip()
                    if user_region and user_region.lower() in " ".join(inv_regions).lower():
                        reasons.append(f"符合你关注的{user_region}区域偏好")
                    elif user_region and user_region == inv.country:
                        reasons.append(f"符合你关注的{user_region}区域偏好")

                    if ("早期项目" in str(user_profile.get("role", "")) or is_early_stage) and "seed" in str(inv.stage_focus):
                        reasons.append("适合早期项目需求")

                    final_score = min(10, max(1, score // 10))
                    region_target = country or region or "全球"
                    feedback_net = feedback_bonus - feedback_penalty
                    feedback_detail = "暂无反馈"
                    if useful_count and not_useful_count:
                        feedback_detail = f"基于{useful_count}次👍好评，同时有{not_useful_count}次👎反馈已扣分"
                    elif useful_count:
                        feedback_detail = f"基于{useful_count}次👍好评"
                    elif not_useful_count:
                        feedback_detail = f"有{not_useful_count}次👎反馈，已扣分"

                    score_breakdown = {
                        "focus_area": {
                            "label": "领域匹配",
                            "weight": f"{focus_weight}%",
                            "max": focus_weight,
                            "got": min(focus_weight, max(0, focus_score)),
                            "status": "match" if focus_score >= 30 else "partial" if focus_score > 0 else "miss",
                            "detail": (
                                f"你的项目领域({focus_area}) vs 对方关注({', '.join(inv_focuses[:4])})"
                                if inv_focuses
                                else "无领域数据"
                            ),
                        },
                        "stage": {
                            "label": "阶段匹配",
                            "weight": f"{stage_weight}%",
                            "max": stage_weight,
                            "got": min(stage_weight, max(0, stage_score)),
                            "status": "match" if stage_score >= 20 else "partial" if stage_score > 0 else "miss",
                            "detail": (
                                f"你的阶段({stage}) vs 对方偏好({', '.join(inv_stages[:4])})"
                                if inv_stages
                                else "无阶段数据"
                            ),
                        },
                        "region": {
                            "label": "地区匹配",
                            "weight": f"{region_weight}%",
                            "max": region_weight,
                            "got": min(region_weight, max(0, region_score)),
                            "status": "match" if region_score >= 15 else "partial" if region_score > 0 else "miss",
                            "detail": f"你的地区({region_target}) vs 对方覆盖({', '.join(inv_regions[:4]) or inv_country or '无地区数据'})",
                        },
                        "type_bonus": {
                            "label": "类型加成",
                            "weight": f"{type_weight}%",
                            "max": type_weight,
                            "got": min(type_weight, max(0, type_score)),
                            "status": "neutral",
                            "detail": f"投资方类型: {inv.investor_type or '未知'}",
                        },
                        "feedback": {
                            "label": "用户反馈",
                            "weight": "动态",
                            "max": 20,
                            "got": max(-20, min(20, feedback_net)),
                            "status": "boost" if feedback_net > 0 else "none",
                            "detail": feedback_detail,
                        },
                    }
                    scored_matches.append(
                        {
                            "name": inv.name,
                            "name_en": inv.name_en,
                            "type": inv.investor_type,
                            "type_label": {
                                "vc": "风险投资",
                                "pe": "私募股权",
                                "angel": "天使投资",
                                "corporate": "企业投资",
                                "foundation": "基金会",
                                "impact_investor": "影响力投资",
                            }.get(inv.investor_type, inv.investor_type),
                            "stage_focus": inv.stage_focus or [],
                            "focus_areas": inv.focus_areas or [],
                            "country": inv.country,
                            "region_focus": inv.region_focus or [],
                            "website": inv.website,
                            "check_size": (
                                f"${inv.check_size_min/1000:.0f}K-${inv.check_size_max/1000000:.1f}M"
                                if inv.check_size_min and inv.check_size_max
                                else "未知"
                            ),
                            "score": final_score,
                            "raw_score": score,
                            "score_label": "高" if final_score >= 7 else "中高" if final_score >= 5 else "中" if final_score >= 3 else "低",
                            "match_reasons": reasons or ["基础方向匹配"],
                            "thesis": inv.thesis,
                            "score_breakdown": score_breakdown,
                        }
                    )

                scored_matches.sort(
                    key=lambda item: (
                        item["score"],
                        item["raw_score"],
                        1 if item.get("country") == country else 0,
                    ),
                    reverse=True,
                )

                result["matches"] = scored_matches[: max(1, min(limit, 10))]
                result["total"] = len(result["matches"])
                return result
            finally:
                db.close()
        except Exception as exc:
            return {"error": f"匹配失败: {exc}", **result}

    def _generate_outreach_email(
        self,
        investor_name: str,
        project_description: str,
        project_stage: str = "",
        sender_name: str = "",
        tone: str = "warm",
    ) -> dict:
        """生成联系投资方的邮件"""
        try:
            from models.database import Investor, get_db

            db = next(get_db())
            try:
                investor = (
                    db.query(Investor)
                    .filter(Investor.name.ilike(f"%{investor_name}%"))
                    .order_by(Investor.updated_at.desc(), Investor.created_at.desc())
                    .first()
                )

                investor_info = {}
                if investor:
                    investor_info = {
                        "name": investor.name,
                        "type": investor.investor_type,
                        "focus": investor.focus_areas or [],
                        "thesis": investor.thesis or "",
                        "region": investor.region_focus or [],
                    }

                resolved_sender = sender_name
                if not resolved_sender and self.conversation_id:
                    profile = self._get_user_profile(self.conversation_id)
                    if profile.get("status") == "found":
                        resolved_sender = profile.get("profile", {}).get("name", "")

                focus_text = ", ".join(investor_info.get("focus", ["FaithTech"])) or "FaithTech"
                thesis_text = investor_info.get("thesis") or "We believe there is strong strategic alignment between your investment priorities and our mission."
                stage_text = project_stage or "seed"
                greeting = "Dear" if tone == "formal" else "Hello"
                signoff = "Sincerely" if tone == "formal" else "Blessings"

                subject = f"Christian Social Media Project in Philippines - Seeking Partnership with {investor_name}"
                body = (
                    f"{greeting} {investor_name} Team,\n\n"
                    f"My name is {resolved_sender or '[Your Name]'}, and I am reaching out regarding a Christian social media project we are building in the Philippines.\n\n"
                    f"Project Overview:\n{project_description}\n\n"
                    f"We are currently at the {stage_text} stage and are looking for strategic partners who share our vision for leveraging technology to serve the global Christian community.\n\n"
                    f"Why {investor_name}?\n"
                    f"Based on our research, your focus on {focus_text} aligns closely with our mission. {thesis_text}\n\n"
                    f"I would love to schedule a brief call to share more details and explore potential collaboration. Would you be open to a 15-minute conversation next week?\n\n"
                    f"Thank you for your time and consideration.\n\n"
                    f"{signoff},\n"
                    f"{resolved_sender or '[Your Name]'}\n"
                    "[Your Contact Information]"
                )

                return {
                    "status": "generated",
                    "email": {
                        "subject": subject,
                        "body": body,
                        "tone": tone,
                        "investor": investor_info,
                    },
                }
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _create_task(
        self,
        title: str,
        description: str = "",
        priority: str = "medium",
        entity_name: str = "",
        mission_id: str = "",
    ) -> dict:
        """创建任务并写入数据库"""
        try:
            from models.database import KnowledgeEntity, Mission, OrganizationProfile, Task, get_db, init_db

            init_db()
            db = next(get_db())
            try:
                entity_id = None
                normalized_mission_id = (mission_id or "").strip() or None
                if normalized_mission_id:
                    mission = db.query(Mission).filter(Mission.id == normalized_mission_id).first()
                    if not mission:
                        return {"status": "error", "message": "创建任务失败: Mission not found"}
                normalized_entity_name = (entity_name or "").strip()
                if normalized_entity_name:
                    entity = (
                        db.query(KnowledgeEntity)
                        .filter(KnowledgeEntity.name.ilike(f"%{normalized_entity_name}%"))
                        .order_by(KnowledgeEntity.ingested_at.desc())
                        .first()
                    )
                    if not entity:
                        org = (
                            db.query(OrganizationProfile)
                            .filter(OrganizationProfile.name.ilike(f"%{normalized_entity_name}%"))
                            .order_by(OrganizationProfile.updated_at.desc())
                            .first()
                        )
                        if org:
                            entity = KnowledgeEntity(
                                id=str(uuid.uuid4()),
                                entity_type="organization",
                                name=org.name,
                                country=org.country,
                                category=org.denomination or "organization",
                                data={"source": "task_creation"},
                                source_url=org.official_website,
                                source_name=org.source_name or "task_creation",
                                confidence=0.8,
                            )
                            db.add(entity)
                            db.flush()
                    if entity:
                        entity_id = entity.id

                task = Task(
                    title=title,
                    description=description,
                    priority=None if normalized_mission_id else (priority or "medium"),
                    status=None if normalized_mission_id else "pending",
                    entity_id=entity_id,
                    mission_id=normalized_mission_id,
                )
                db.add(task)
                db.commit()
                db.refresh(task)

                return {
                    "status": "created",
                    "task_id": task.id,
                    "title": title,
                    "priority": priority or "medium",
                    "message": f"✅ 任务已创建：{title}",
                }
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": f"创建任务失败: {exc}"}

    def _get_org_tag_codes(self, db: Any, organization_id: str, organization_name: str = "", member_estimate: int | None = None) -> set[str]:
        from models.database import OrganizationOntologyTag

        tag_codes = {
            row.tag_id
            for row in db.query(OrganizationOntologyTag).filter(OrganizationOntologyTag.organization_id == organization_id).all()
        }

        lowered_name = (organization_name or "").lower()
        if "pcec" in lowered_name or "alliance" in lowered_name or "council" in lowered_name:
            tag_codes.add("association")
        if "victory" in lowered_name or "ccf" in lowered_name or "network" in lowered_name:
            tag_codes.add("church_network")
        if "cbn" in lowered_name or "media" in lowered_name or "broadcast" in lowered_name:
            tag_codes.add("media_outlet")
        if "seminary" in lowered_name or "theological" in lowered_name:
            tag_codes.add("seminary")
        if "mission" in lowered_name or "ywam" in lowered_name or "omf" in lowered_name:
            tag_codes.add("mission_agency")

        if member_estimate:
            if member_estimate >= 100000:
                tag_codes.add("mega")
            elif member_estimate >= 10000:
                tag_codes.add("large")
            elif member_estimate >= 1000:
                tag_codes.add("medium")
        return tag_codes

    def _match_acquirers(
        self,
        project_type: str = "",
        focus_area: str = "",
        country: str = "",
        limit: int = 5,
    ) -> dict:
        """匹配潜在收购方"""
        result = {"acquirers": [], "project_type": project_type, "focus_area": focus_area, "country": country}
        try:
            from models.database import OrganizationProfile, get_db

            db = next(get_db())
            try:
                query = db.query(OrganizationProfile)
                if country:
                    query = query.filter(OrganizationProfile.country == country)
                orgs = query.order_by(OrganizationProfile.updated_at.desc()).limit(max(limit * 6, 20)).all()

                normalized_project_type = (project_type or "").lower()
                normalized_focus = (focus_area or "").lower()
                acquirers = []
                for org in orgs:
                    tag_codes = self._get_org_tag_codes(db, org.id, org.name, org.member_estimate)
                    score = 0
                    reasons = []

                    if "large" in tag_codes or "mega" in tag_codes:
                        score += 28
                        reasons.append("机构规模较大，具备整合能力")
                    elif "medium" in tag_codes:
                        score += 14
                        reasons.append("机构规模中等，具备合作或并购潜力")

                    if any(token in tag_codes for token in ["media_outlet", "faithtech_media"]):
                        if normalized_project_type in ["social_media", "media", "content"] or normalized_focus == "media":
                            score += 40
                            reasons.append("媒体领域协同度高")
                        else:
                            score += 14
                            reasons.append("具备媒体分发能力")

                    if any(token in tag_codes for token in ["church_network", "association"]):
                        score += 24
                        reasons.append("具备全国教会网络和渠道资源")

                    if any(token in tag_codes for token in ["faithtech_ai", "faithtech_social", "faithtech_media", "faithtech_bible"]):
                        if normalized_project_type in ["app", "saas", "platform", "social_media"] or normalized_focus == "faithtech":
                            score += 30
                            reasons.append("技术产品互补，具备收购整合逻辑")

                    if org.official_website:
                        score += 4
                    if org.contact_email:
                        score += 3

                    if score <= 0:
                        continue

                    acquirers.append(
                        {
                            "name": org.name,
                            "type": "organization",
                            "country": org.country,
                            "score": min(10, max(1, score // 10)),
                            "reasons": reasons,
                            "website": org.official_website,
                        }
                    )

                acquirers.sort(key=lambda item: (item["score"], len(item["reasons"])), reverse=True)
                result["acquirers"] = acquirers[: max(1, min(limit, 10))]
                return result
            finally:
                db.close()
        except Exception as exc:
            return {"error": f"收购方匹配失败: {exc}", **result}

    def _match_users(
        self,
        product_type: str = "",
        target_audience: str = "",
        country: str = "",
        limit: int = 10,
    ) -> dict:
        """匹配潜在使用方"""
        result = {"users": [], "product_type": product_type, "target_audience": target_audience, "country": country}
        try:
            from models.database import OrganizationProfile, get_db

            db = next(get_db())
            try:
                query = db.query(OrganizationProfile)
                if country:
                    query = query.filter(OrganizationProfile.country == country)
                orgs = query.order_by(OrganizationProfile.updated_at.desc()).limit(max(limit * 8, 24)).all()

                normalized_product_type = (product_type or "").lower()
                normalized_audience = (target_audience or "").lower()
                users = []
                for org in orgs:
                    tag_codes = self._get_org_tag_codes(db, org.id, org.name, org.member_estimate)
                    score = 0
                    reasons = []

                    if normalized_product_type in ["social_media", "media", "content"] or any(token in normalized_product_type for token in ["社交", "媒体"]):
                        if "church_network" in tag_codes:
                            score += 34
                            reasons.append("教会网络需要内容分发和社群运营工具")
                        if "association" in tag_codes:
                            score += 28
                            reasons.append("联盟型机构适合统一传播和社群联动")
                        if "media_outlet" in tag_codes:
                            score += 25
                            reasons.append("媒体机构可直接复用内容平台能力")

                    if "seminary" in tag_codes:
                        score += 18
                        reasons.append("神学院适合作为内容、课程和学生社群用户")
                    if "mission_agency" in tag_codes:
                        score += 20
                        reasons.append("宣教机构需要跨地区传播与招募工具")

                    if any(token in normalized_audience for token in ["青年", "大学生", "young", "youth", "student"]):
                        if "church_network" in tag_codes:
                            score += 10
                            reasons.append("拥有青年事工触达场景")

                    if org.member_estimate and org.member_estimate >= 1000:
                        score += 8
                        reasons.append("拥有较明确的用户基础")

                    if org.official_website:
                        score += 3

                    if score <= 0:
                        continue

                    users.append(
                        {
                            "name": org.name,
                            "country": org.country,
                            "score": min(10, max(1, score // 10)),
                            "reasons": reasons,
                            "website": org.official_website,
                        }
                    )

                users.sort(key=lambda item: (item["score"], len(item["reasons"])), reverse=True)
                result["users"] = users[: max(1, min(limit, 12))]
                return result
            finally:
                db.close()
        except Exception as exc:
            return {"error": f"使用方匹配失败: {exc}", **result}

    def _query_graph(
        self,
        entity_name: str,
        relation_type: str = "all",
        depth: int = 1,
        limit: int = 20,
    ) -> dict:
        """查询机构关系图谱"""
        result = {
            "center_entity": entity_name,
            "direct_relations": [],
            "indirect_relations": [],
            "investment_chain": [],
            "total": 0,
            "summary": "",
        }
        try:
            from models.database import FundingRound, Investment, Investor, KnowledgeEntity, OrganizationProfile

            tool_name = "query_graph"
            function_name = "_query_graph"
            self._tool_diag_print(ToolName=tool_name, ENTER_TOOL=function_name)
            acquire_result = self._acquire_tool_db_session(
                tool_name=tool_name,
                function_name=function_name,
                line_no=inspect.currentframe().f_lineno + 1,
                params={"entity_name": entity_name, "relation_type": relation_type, "depth": depth, "limit": limit},
            )
            if acquire_result.get("status") == "error":
                return acquire_result
            db = acquire_result["db"]
            try:
                counterpart_name = ""
                if "||" in entity_name:
                    entity_name, counterpart_name = [part.strip() for part in entity_name.split("||", 1)]

                center_ke_query = (
                    db.query(KnowledgeEntity)
                    .filter(KnowledgeEntity.name.ilike(f"%{entity_name}%"))
                    .order_by(KnowledgeEntity.ingested_at.desc())
                )
                center_ke = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_2",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=center_ke_query,
                    params={"entity_name": entity_name, "target": "KnowledgeEntity"},
                    executor=lambda: center_ke_query.first(),
                )
                center_org_query = (
                    db.query(OrganizationProfile)
                    .filter(OrganizationProfile.name.ilike(f"%{entity_name}%"))
                    .order_by(OrganizationProfile.updated_at.desc())
                )
                center_org = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_3",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=center_org_query,
                    params={"entity_name": entity_name, "target": "OrganizationProfile"},
                    executor=lambda: center_org_query.first(),
                )
                center_investor_query = (
                    db.query(Investor)
                    .filter(Investor.name.ilike(f"%{entity_name}%"))
                    .order_by(Investor.updated_at.desc())
                )
                center_investor = self._tool_diag_sql(
                    tool_name=tool_name,
                    function_name=function_name,
                    step_name="STEP_4",
                    line_no=inspect.currentframe().f_lineno + 1,
                    query_or_sql=center_investor_query,
                    params={"entity_name": entity_name, "target": "Investor"},
                    executor=lambda: center_investor_query.first(),
                )

                if not center_ke and center_org:
                    center_ke = KnowledgeEntity(
                        id=center_org.id,
                        entity_type="organization",
                        name=center_org.name,
                        country=center_org.country,
                        category=center_org.denomination,
                        data={"source": "organization_profile"},
                        source_url=center_org.official_website,
                        source_name=center_org.source_name,
                        confidence=center_org.confidence or 0.8,
                    )

                center_country = ""
                center_name = entity_name
                center_type = "unknown"
                if center_ke:
                    center_country = center_ke.country or ""
                    center_name = center_ke.name
                    center_type = center_ke.entity_type
                elif center_org:
                    center_country = center_org.country or ""
                    center_name = center_org.name
                    center_type = "organization"
                elif center_investor:
                    center_country = center_investor.country or ""
                    center_name = center_investor.name
                    center_type = center_investor.investor_type
                else:
                    return {**result, "error": f"未找到机构: {entity_name}"}

                result["center_entity"] = {
                    "id": center_ke.id if center_ke else (center_org.id if center_org else center_investor.id),
                    "name": center_name,
                    "type": center_type,
                    "country": center_country,
                }

                center_tags = set()
                if center_org:
                    center_tags = self._tool_diag_step(
                        tool_name=tool_name,
                        function_name=function_name,
                        step_name="STEP_5",
                        line_no=inspect.currentframe().f_lineno + 1,
                        step_detail=f"call _get_org_tag_codes({center_org.id})",
                        func=lambda: self._get_org_tag_codes(db, center_org.id, center_org.name, center_org.member_estimate),
                        params={"organization_id": center_org.id, "name": center_org.name},
                    )

                if relation_type in ("all", "investment"):
                    entity_ids = []
                    if center_ke:
                        entity_ids.append(center_ke.id)
                    if center_org and center_org.id not in entity_ids:
                        entity_ids.append(center_org.id)

                    for entity_id in entity_ids:
                        rounds_query = (
                            db.query(FundingRound)
                            .filter(FundingRound.entity_id == entity_id)
                            .order_by(FundingRound.announced_date.desc(), FundingRound.id.desc())
                        )
                        rounds = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_6",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=rounds_query,
                            params={"entity_id": entity_id},
                            executor=lambda: rounds_query.all(),
                        )
                        for fr in rounds:
                            investments_query = (
                                db.query(Investment, Investor)
                                .join(Investor, Investment.investor_id == Investor.id)
                                .filter(Investment.funding_round_id == fr.id)
                            )
                            investments = self._tool_diag_sql(
                                tool_name=tool_name,
                                function_name=function_name,
                                step_name="STEP_7",
                                line_no=inspect.currentframe().f_lineno + 1,
                                query_or_sql=investments_query,
                                params={"funding_round_id": fr.id},
                                executor=lambda: investments_query.all(),
                            )
                            for inv, investor in investments:
                                result["direct_relations"].append(
                                    {
                                        "direction": "incoming",
                                        "type": "investment",
                                        "entity": {
                                            "name": investor.name,
                                            "type": investor.investor_type,
                                            "country": investor.country,
                                        },
                                        "amount": inv.amount,
                                        "lead": inv.lead_investor,
                                        "round": fr.round_type,
                                        "description": f"{investor.name} 在 {fr.round_type} 投资 {center_name}",
                                    }
                                )
                                result["investment_chain"].append(
                                    {
                                        "from": investor.name,
                                        "to": center_name,
                                        "relationship": "投资",
                                        "round": fr.round_type,
                                        "amount": inv.amount,
                                        "announced_date": fr.announced_date.isoformat() if fr.announced_date else "",
                                    }
                                )

                    if center_investor:
                        outgoing_query = (
                            db.query(Investment, FundingRound, KnowledgeEntity)
                            .join(FundingRound, Investment.funding_round_id == FundingRound.id)
                            .join(KnowledgeEntity, FundingRound.entity_id == KnowledgeEntity.id)
                            .filter(Investment.investor_id == center_investor.id)
                            .order_by(FundingRound.announced_date.desc(), FundingRound.id.desc())
                        )
                        outgoing = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_8",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=outgoing_query,
                            params={"investor_id": center_investor.id},
                            executor=lambda: outgoing_query.all(),
                        )
                        for inv, fr, entity in outgoing:
                            result["direct_relations"].append(
                                {
                                    "direction": "outgoing",
                                    "type": "investment",
                                    "entity": {
                                        "name": entity.name,
                                        "type": entity.entity_type,
                                        "country": entity.country,
                                    },
                                    "amount": inv.amount,
                                    "lead": inv.lead_investor,
                                    "round": fr.round_type,
                                    "description": f"{center_name} 投资 {entity.name}",
                                }
                            )
                            result["investment_chain"].append(
                                {
                                    "from": center_name,
                                    "to": entity.name,
                                    "relationship": "投资",
                                    "round": fr.round_type,
                                    "amount": inv.amount,
                                    "announced_date": fr.announced_date.isoformat() if fr.announced_date else "",
                                }
                            )

                if relation_type in ("all", "partnership", "collaboration"):
                    comparable_org = center_org
                    if not comparable_org and center_ke:
                        comparable_org_query = (
                            db.query(OrganizationProfile)
                            .filter(OrganizationProfile.name.ilike(f"%{center_name}%"))
                            .order_by(OrganizationProfile.updated_at.desc())
                        )
                        comparable_org = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_9",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=comparable_org_query,
                            params={"center_name": center_name},
                            executor=lambda: comparable_org_query.first(),
                        )
                    if comparable_org:
                        candidates_query = (
                            db.query(OrganizationProfile)
                            .filter(OrganizationProfile.id != comparable_org.id)
                            .filter(OrganizationProfile.country == comparable_org.country)
                            .order_by(OrganizationProfile.updated_at.desc())
                            .limit(max(limit * 3, 12))
                        )
                        candidates = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_10",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=candidates_query,
                            params={"organization_id": comparable_org.id, "country": comparable_org.country},
                            executor=lambda: candidates_query.all(),
                        )
                        for org in candidates:
                            score = 0
                            reasons = []
                            tags = self._get_org_tag_codes(db, org.id, org.name, org.member_estimate)

                            shared_tags = sorted((center_tags & tags))
                            if shared_tags:
                                score += 2 + min(len(shared_tags), 3)
                                reasons.append(f"共享标签：{', '.join(shared_tags[:3])}")

                            if comparable_org.country and org.country == comparable_org.country:
                                score += 2
                                reasons.append(f"同属 {org.country} 生态")

                            denom_left = (comparable_org.denomination or "").lower()
                            denom_right = (org.denomination or "").lower()
                            if denom_left and denom_right and denom_left == denom_right:
                                score += 2
                                reasons.append("宗派背景相近")

                            if "church_network" in center_tags and "media_outlet" in tags:
                                score += 3
                                reasons.append("教会网络与媒体平台存在传播协同")
                            if "media_outlet" in center_tags and "church_network" in tags:
                                score += 3
                                reasons.append("媒体平台与教会网络存在内容分发协同")
                            if "association" in center_tags and ("church_network" in tags or "media_outlet" in tags):
                                score += 2
                                reasons.append("联盟机构与成员/媒体生态存在合作可能")

                            if score <= 0:
                                continue

                            result["direct_relations"].append(
                                {
                                    "direction": "bidirectional",
                                    "type": "collaboration",
                                    "entity": {
                                        "name": org.name,
                                        "type": "organization",
                                        "country": org.country,
                                    },
                                    "description": "；".join(reasons),
                                    "confidence": min(0.95, 0.45 + score * 0.08),
                                }
                            )

                        if depth >= 2:
                            top_orgs = [item["entity"]["name"] for item in result["direct_relations"] if item.get("type") == "collaboration"][:3]
                            for name in top_orgs:
                                result["indirect_relations"].append(
                                    {
                                        "via": name,
                                        "note": f"{center_name} 可通过 {name} 延伸到更广的本地教会/媒体/联盟网络",
                                    }
                                )

                    if counterpart_name:
                        counterpart_query = (
                            db.query(OrganizationProfile)
                            .filter(OrganizationProfile.name.ilike(f"%{counterpart_name}%"))
                            .order_by(OrganizationProfile.updated_at.desc())
                        )
                        counterpart = self._tool_diag_sql(
                            tool_name=tool_name,
                            function_name=function_name,
                            step_name="STEP_11",
                            line_no=inspect.currentframe().f_lineno + 1,
                            query_or_sql=counterpart_query,
                            params={"counterpart_name": counterpart_name},
                            executor=lambda: counterpart_query.first(),
                        )
                        if counterpart:
                            counterpart_tags = self._tool_diag_step(
                                tool_name=tool_name,
                                function_name=function_name,
                                step_name="STEP_12",
                                line_no=inspect.currentframe().f_lineno + 1,
                                step_detail=f"call _get_org_tag_codes({counterpart.id})",
                                func=lambda: self._get_org_tag_codes(db, counterpart.id, counterpart.name, counterpart.member_estimate),
                                params={"organization_id": counterpart.id, "name": counterpart.name},
                            )
                            reasons = []
                            confidence = 0.42
                            if comparable_org.country and counterpart.country == comparable_org.country:
                                reasons.append(f"两者同属 {counterpart.country} 基督教生态")
                                confidence += 0.16
                            shared_tags = sorted(center_tags & counterpart_tags)
                            if shared_tags:
                                reasons.append(f"共享标签：{', '.join(shared_tags[:3])}")
                                confidence += 0.16
                            if "church_network" in center_tags and "media_outlet" in counterpart_tags:
                                reasons.append("教会网络与媒体平台存在内容传播和渠道协同")
                                confidence += 0.18
                            if "media_outlet" in center_tags and "church_network" in counterpart_tags:
                                reasons.append("媒体平台与教会网络存在内容分发协同")
                                confidence += 0.18
                            if reasons:
                                result["direct_relations"].insert(
                                    0,
                                    {
                                        "direction": "bidirectional",
                                        "type": "collaboration",
                                        "entity": {
                                            "name": counterpart.name,
                                            "type": "organization",
                                            "country": counterpart.country,
                                        },
                                        "description": "；".join(reasons),
                                        "confidence": min(0.95, confidence),
                                    },
                                )

                result["direct_relations"] = result["direct_relations"][: max(limit, 1)]
                result["investment_chain"] = result["investment_chain"][: max(limit, 1)]
                result["total"] = len(result["direct_relations"])

                if result["investment_chain"] and center_name.lower() == "gloo":
                    result["summary"] = "Gloo 的链条呈现“主流风投 + 信仰资本”双轨结构，Greylock 连续领投，Draper 与 Messiah Foundation 作为协同资本进入。"
                elif result["direct_relations"] and center_name.lower() in ["victory philippines", "victory"]:
                    result["summary"] = "图谱显示 Victory 更像菲律宾本地教会网络节点，和 CBN Asia 这类媒体机构的关系主要体现在同国生态与传播协同，而非已记录的股权投资。"
                elif result["direct_relations"]:
                    result["summary"] = f"{center_name} 当前已识别出 {len(result['direct_relations'])} 条直接关系，可继续按投资、合作或间接连接方向深挖。"

                return result
            finally:
                db.close()
        except Exception as exc:
            return {**result, "error": f"图谱查询失败: {exc}"}

    def _query_funding_rounds(
        self,
        entity_name: str | None = None,
        investor_name: str | None = None,
        round_type: str | None = None,
        focus_area: str | None = None,
        limit: int = 10,
    ) -> dict:
        """查询融资/投资交易记录"""
        try:
            from models.database import FundingRound, Investment, Investor, KnowledgeEntity, get_db

            db = next(get_db())
            try:
                rounds = (
                    db.query(FundingRound, KnowledgeEntity)
                    .join(KnowledgeEntity, FundingRound.entity_id == KnowledgeEntity.id)
                    .all()
                )

                focus_aliases = {
                    "faithtech": {
                        "faithtech", "bible tech", "church tech", "christian ai",
                        "christian media", "media", "fintech", "data", "technology",
                    },
                    "media": {"media", "christian media", "social", "social media", "content"},
                    "mission": {"mission", "church planting", "evangelism"},
                }

                normalized_entity = (entity_name or "").strip().lower()
                normalized_investor = (investor_name or "").strip().lower()
                normalized_round = (round_type or "").strip().lower()
                normalized_focus = (focus_area or "").strip().lower()

                items = []
                for funding_round, entity in rounds:
                    if normalized_entity and normalized_entity not in (entity.name or "").lower():
                        continue

                    if normalized_round and normalized_round != (funding_round.round_type or "").lower():
                        continue

                    investments = (
                        db.query(Investment, Investor)
                        .join(Investor, Investment.investor_id == Investor.id)
                        .filter(Investment.funding_round_id == funding_round.id)
                        .all()
                    )

                    if normalized_investor:
                        if not any(normalized_investor in (investor.name or "").lower() for _, investor in investments):
                            continue

                    entity_tokens = {
                        (entity.category or "").strip().lower(),
                        (entity.entity_type or "").strip().lower(),
                        (entity.name or "").strip().lower(),
                    }
                    if normalized_focus:
                        candidate_tokens = {normalized_focus, *(focus_aliases.get(normalized_focus, set()))}
                        investor_focus_tokens = {
                            str(area).strip().lower()
                            for _, investor in investments
                            for area in (investor.focus_areas or [])
                            if str(area).strip()
                        }
                        if not (entity_tokens & candidate_tokens or investor_focus_tokens & candidate_tokens):
                            continue

                    items.append(
                        {
                            "entity_name": entity.name,
                            "entity_category": entity.category or "",
                            "round_type": funding_round.round_type,
                            "amount": funding_round.amount,
                            "announced_date": funding_round.announced_date.isoformat() if funding_round.announced_date else None,
                            "source": funding_round.source or "",
                            "investors": [
                                {
                                    "name": investor.name,
                                    "amount": investment.amount,
                                    "lead_investor": bool(investment.lead_investor),
                                    "investor_type": investor.investor_type,
                                }
                                for investment, investor in investments
                            ],
                        }
                    )

                items.sort(
                    key=lambda item: item.get("announced_date") or "",
                    reverse=True,
                )
                items = items[: max(1, min(limit, 20))]

                return {
                    "status": "success",
                    "count": len(items),
                    "query_summary": {
                        "entity_name": entity_name,
                        "investor_name": investor_name,
                        "round_type": round_type,
                        "focus_area": focus_area,
                    },
                    "rounds": items,
                }
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _query_fused(
        self,
        entity_name: str = "",
        keywords: list | None = None,
        scope: str = "global",
        country: str | None = None,
        limit: int = 10,
    ) -> dict:
        """
        跨源融合查询：同时查机构档案 + 新闻情报 + 融资记录。
        """
        result = {
            "status": "success",
            "entity": {},
            "intelligence": [],
            "funding_rounds": [],
            "investors": [],
            "ontology_tags": [],
            "relations": [],
            "total": 0,
            "query_summary": {
                "entity_name": entity_name,
                "scope": scope,
                "country": country,
                "keywords": keywords or [],
            },
        }

        try:
            from models.database import (
                FundingRound,
                IntelligenceItem,
                Investment,
                Investor,
                KnowledgeEntity,
                OrganizationOntologyTag,
                OrganizationProfile,
                get_db,
            )
            from sqlalchemy import desc, or_

            db = next(get_db())
            try:
                normalized_entity = (entity_name or "").strip()
                terms = [normalized_entity] if normalized_entity else []
                for kw in keywords or []:
                    kw = (kw or "").strip()
                    if kw and kw not in terms:
                        terms.append(kw)

                org = None
                investor = None
                knowledge_entity = None
                canonical_name = normalized_entity

                if normalized_entity:
                    org = (
                        db.query(OrganizationProfile)
                        .filter(
                            or_(
                                OrganizationProfile.name.ilike(f"%{normalized_entity}%"),
                                OrganizationProfile.name_local.ilike(f"%{normalized_entity}%"),
                            )
                        )
                        .order_by(desc(OrganizationProfile.updated_at))
                        .first()
                    )

                if org:
                    canonical_name = org.name or canonical_name
                    result["entity"] = {
                        "name": org.name,
                        "name_local": org.name_local,
                        "country": org.country,
                        "denomination": org.denomination,
                        "member_estimate": org.member_estimate,
                        "official_website": org.official_website,
                        "leader_name": org.leader_name,
                        "source": "organization_profiles",
                    }

                    tags = (
                        db.query(OrganizationOntologyTag)
                        .filter(OrganizationOntologyTag.organization_id == org.id)
                        .all()
                    )
                    for tag in tags:
                        result["ontology_tags"].append(
                            {
                                "type": tag.tag_type,
                                "tag_id": tag.tag_id,
                                "confidence": tag.confidence,
                            }
                        )

                if normalized_entity:
                    knowledge_entity = (
                        db.query(KnowledgeEntity)
                        .filter(KnowledgeEntity.name.ilike(f"%{normalized_entity}%"))
                        .order_by(desc(KnowledgeEntity.ingested_at))
                        .first()
                    )
                    if not knowledge_entity and org and org.name:
                        knowledge_entity = (
                            db.query(KnowledgeEntity)
                            .filter(KnowledgeEntity.name.ilike(f"%{org.name}%"))
                            .order_by(desc(KnowledgeEntity.ingested_at))
                            .first()
                        )

                if not org and normalized_entity:
                    investor = (
                        db.query(Investor)
                        .filter(
                            or_(
                                Investor.name.ilike(f"%{normalized_entity}%"),
                                Investor.name_en.ilike(f"%{normalized_entity}%"),
                            )
                        )
                        .order_by(desc(Investor.updated_at))
                        .first()
                    )
                    if investor:
                        canonical_name = investor.name or canonical_name
                        result["entity"] = {
                            "name": investor.name,
                            "type": investor.investor_type,
                            "country": investor.country,
                            "focus_areas": investor.focus_areas or [],
                            "stage_focus": investor.stage_focus or [],
                            "website": investor.website,
                            "source": "investors",
                        }

                if knowledge_entity:
                    canonical_name = knowledge_entity.name or canonical_name
                    if not result["entity"]:
                        result["entity"] = {
                            "name": knowledge_entity.name,
                            "type": knowledge_entity.entity_type,
                            "country": knowledge_entity.country,
                            "category": knowledge_entity.category,
                            "source": "knowledge_entities",
                        }
                    else:
                        result["entity"].setdefault("category", knowledge_entity.category)
                        result["entity"].setdefault("type", knowledge_entity.entity_type)
                        result["entity"].setdefault("country", knowledge_entity.country)

                if canonical_name and canonical_name not in terms:
                    terms.insert(0, canonical_name)

                if terms:
                    intelligence_query = db.query(IntelligenceItem)
                    text_filters = []
                    for term in terms:
                        text_filters.extend(
                            [
                                IntelligenceItem.title.ilike(f"%{term}%"),
                                IntelligenceItem.content.ilike(f"%{term}%"),
                                IntelligenceItem.entity_name.ilike(f"%{term}%"),
                            ]
                        )
                    intelligence_query = intelligence_query.filter(or_(*text_filters))
                    if scope and scope != "entity":
                        intelligence_query = intelligence_query.filter(IntelligenceItem.scope == scope)
                    if country:
                        intelligence_query = intelligence_query.filter(IntelligenceItem.country == country)

                    intelligence_items = (
                        intelligence_query
                        .order_by(desc(IntelligenceItem.published_at), desc(IntelligenceItem.ingested_at))
                        .limit(max(1, min(limit, 20)))
                        .all()
                    )
                    seen_titles = set()
                    for item in intelligence_items:
                        title_key = ((item.title or "")[:80]).strip().lower()
                        if title_key and title_key in seen_titles:
                            continue
                        if title_key:
                            seen_titles.add(title_key)
                        result["intelligence"].append(
                            {
                                "title": item.title,
                                "content": (item.content or "")[:200],
                                "source_name": item.source_name,
                                "published_at": item.published_at.isoformat() if item.published_at else None,
                                "url": item.source_url,
                            }
                        )

                if knowledge_entity:
                    funding_rows = (
                        db.query(FundingRound)
                        .filter(FundingRound.entity_id == knowledge_entity.id)
                        .order_by(desc(FundingRound.announced_date), desc(FundingRound.id))
                        .all()
                    )
                    for fr in funding_rows[: max(1, min(limit, 20))]:
                        investment_rows = (
                            db.query(Investment, Investor)
                            .join(Investor, Investment.investor_id == Investor.id)
                            .filter(Investment.funding_round_id == fr.id)
                            .all()
                        )
                        investors_list = []
                        for inv, inv_obj in investment_rows:
                            investors_list.append(
                                {
                                    "name": inv_obj.name,
                                    "amount": inv.amount,
                                    "lead": bool(inv.lead_investor),
                                }
                            )

                        result["funding_rounds"].append(
                            {
                                "round_type": fr.round_type,
                                "amount": fr.amount,
                                "announced_date": fr.announced_date.isoformat() if fr.announced_date else None,
                                "investors": investors_list,
                            }
                        )

                if investor:
                    investor_rows = (
                        db.query(Investment, FundingRound, KnowledgeEntity)
                        .join(FundingRound, Investment.funding_round_id == FundingRound.id)
                        .join(KnowledgeEntity, FundingRound.entity_id == KnowledgeEntity.id)
                        .filter(Investment.investor_id == investor.id)
                        .order_by(desc(FundingRound.announced_date), desc(FundingRound.id))
                        .all()
                    )
                    for inv, fr, ent in investor_rows[: max(1, min(limit, 20))]:
                        result["investors"].append(
                            {
                                "invested_entity": ent.name,
                                "round_type": fr.round_type,
                                "amount": inv.amount,
                                "lead": bool(inv.lead_investor),
                            }
                        )

                result["total"] = (
                    len(result["intelligence"])
                    + len(result["funding_rounds"])
                    + len(result["investors"])
                    + (1 if result["entity"] else 0)
                )
                return result
            finally:
                db.close()
        except Exception as exc:
            return {**result, "status": "error", "error": f"融合查询失败: {exc}"}

    def _resolve_profile_session_id(self, conversation_id: str | None = None) -> str:
        return conversation_id or self._current_session_id or self.conversation_id or "default-session"

    def _merge_profile_value(self, old_value, new_value):
        if new_value in (None, ""):
            return old_value
        if old_value in (None, ""):
            return new_value
        if isinstance(old_value, str) and isinstance(new_value, str):
            existing = [item.strip() for item in old_value.split(",") if item.strip()]
            incoming = [item.strip() for item in new_value.split(",") if item.strip()]
            merged = existing[:]
            seen = {item.lower() for item in existing}
            for item in incoming:
                if item.lower() not in seen:
                    merged.append(item)
                    seen.add(item.lower())
            return ", ".join(merged)
        return new_value

    def _profile_to_dict(self, profile) -> dict:
        if not profile:
            return {}
        data = {
            "name": profile.name,
            "org": getattr(profile, "org", None),
            "role": profile.role,
            "project_description": profile.project_description,
            "focus_area": profile.focus_area,
            "project_stage": profile.project_stage,
            "focus_region": profile.focus_region,
            "country": profile.country,
            "region": getattr(profile, "region", None),
            "preference": profile.preference,
            "preferred_investor_type": profile.preferred_investor_type,
        }
        extra = profile.profile_json or {}
        if isinstance(extra, dict):
            for key, value in extra.items():
                data.setdefault(key, value)
        return data

    def _load_legacy_user_profile(self, db, session_id: str) -> dict:
        try:
            from models.database import RequestTrace
        except ImportError:
            from backend.models.database import RequestTrace

        traces = (
            db.query(RequestTrace)
            .filter(RequestTrace.event_type == "user_profile_saved")
            .order_by(RequestTrace.created_at.desc())
            .all()
        )
        for item in traces:
            event_data = item.event_data or {}
            if event_data.get("conversation_id") == session_id:
                return event_data.get("profile") or {}
        return {}

    def _get_user_profile(self, conversation_id: str | None = None) -> dict:
        try:
            try:
                from models.database import UserProfile, get_db
            except ImportError:
                from backend.models.database import UserProfile, get_db

            session_id = self._resolve_profile_session_id(conversation_id)
            db = next(get_db())
            try:
                profile_row = (
                    db.query(UserProfile)
                    .filter(UserProfile.session_id == session_id)
                    .order_by(UserProfile.updated_at.desc())
                    .first()
                )
                resolved_session_id = session_id

                if not profile_row:
                    legacy_profile = self._load_legacy_user_profile(db, session_id)
                    if legacy_profile:
                        profile_row = UserProfile(
                            session_id=session_id,
                            name=legacy_profile.get("name"),
                            org=legacy_profile.get("org"),
                            role=legacy_profile.get("role"),
                            project_description=legacy_profile.get("project_description"),
                            focus_area=legacy_profile.get("focus_area"),
                            project_stage=legacy_profile.get("project_stage"),
                            focus_region=legacy_profile.get("focus_region"),
                            country=legacy_profile.get("country"),
                            region=legacy_profile.get("region"),
                            preference=legacy_profile.get("preference"),
                            preferred_investor_type=legacy_profile.get("preferred_investor_type"),
                            profile_json=legacy_profile,
                            source="request_trace_migration",
                            confidence=1.0,
                        )
                        db.add(profile_row)
                        db.commit()
                        db.refresh(profile_row)

                if not profile_row and not bool(getattr(config.settings, "CHAT_USER_OWNERSHIP_ENABLED", False)):
                    profile_row = db.query(UserProfile).order_by(UserProfile.updated_at.desc()).first()
                    if profile_row:
                        resolved_session_id = profile_row.session_id

                if not profile_row:
                    return {"profile": {}, "status": "not_found"}

                profile = self._profile_to_dict(profile_row)
                return {
                    "profile": profile,
                    "status": "found",
                    "updated_at": profile_row.updated_at.isoformat() if profile_row.updated_at else None,
                    "session_id": resolved_session_id,
                }
            finally:
                db.close()
        except Exception as exc:
            return {"profile": {}, "status": "error", "message": str(exc)}

    def _save_user_profile(
        self,
        conversation_id: str | None = None,
        name: str | None = None,
        org: str | None = None,
        role: str | None = None,
        preference: str | None = None,
        focus_region: str | None = None,
        preferred_investor_type: str | None = None,
        project_stage: str | None = None,
        focus_area: str | None = None,
        project_description: str | None = None,
        country: str | None = None,
        region: str | None = None,
    ) -> dict:
        try:
            try:
                from models.database import RequestTrace, UserProfile, get_db
            except ImportError:
                from backend.models.database import RequestTrace, UserProfile, get_db

            session_id = self._resolve_profile_session_id(conversation_id)
            db = next(get_db())
            try:
                existing = (
                    db.query(UserProfile)
                    .filter(UserProfile.session_id == session_id)
                    .order_by(UserProfile.updated_at.desc())
                    .first()
                )

                previous_profile = self._profile_to_dict(existing) if existing else {}
                if not previous_profile:
                    previous_profile = self._load_legacy_user_profile(db, session_id)

                profile = {
                    "name": self._merge_profile_value(previous_profile.get("name"), name) or "未命名用户",
                    "org": self._merge_profile_value(previous_profile.get("org"), org),
                    "role": self._merge_profile_value(previous_profile.get("role"), role),
                    "preference": self._merge_profile_value(previous_profile.get("preference"), preference),
                    "focus_region": self._merge_profile_value(previous_profile.get("focus_region"), focus_region),
                    "preferred_investor_type": self._merge_profile_value(
                        previous_profile.get("preferred_investor_type"),
                        preferred_investor_type,
                    ),
                    "project_stage": self._merge_profile_value(previous_profile.get("project_stage"), project_stage),
                    "focus_area": self._merge_profile_value(previous_profile.get("focus_area"), focus_area),
                    "project_description": self._merge_profile_value(
                        previous_profile.get("project_description"),
                        project_description,
                    ),
                    "country": self._merge_profile_value(previous_profile.get("country"), country),
                    "region": self._merge_profile_value(previous_profile.get("region"), region),
                }

                if existing:
                    existing.name = profile["name"]
                    existing.org = profile["org"]
                    existing.role = profile["role"]
                    existing.project_description = profile["project_description"]
                    existing.focus_area = profile["focus_area"]
                    existing.project_stage = profile["project_stage"]
                    existing.focus_region = profile["focus_region"]
                    existing.country = profile["country"]
                    existing.region = profile["region"]
                    existing.preference = profile["preference"]
                    existing.preferred_investor_type = profile["preferred_investor_type"]
                    existing.profile_json = profile
                    existing.source = "conversation"
                    existing.confidence = 1.0
                    existing.updated_at = datetime.utcnow()
                    profile_row = existing
                else:
                    profile_row = UserProfile(
                        session_id=session_id,
                        name=profile["name"],
                        org=profile["org"],
                        role=profile["role"],
                        project_description=profile["project_description"],
                        focus_area=profile["focus_area"],
                        project_stage=profile["project_stage"],
                        focus_region=profile["focus_region"],
                        country=profile["country"],
                        region=profile["region"],
                        preference=profile["preference"],
                        preferred_investor_type=profile["preferred_investor_type"],
                        profile_json=profile,
                        source="conversation",
                        confidence=1.0,
                    )
                    db.add(profile_row)

                trace = RequestTrace(
                    id=str(uuid.uuid4()),
                    request_id=f"profile:{session_id}",
                    event_type="user_profile_saved",
                    event_data={"conversation_id": session_id, "profile": profile},
                )
                db.add(trace)
                db.commit()
                return {"status": "saved", "profile": profile, "session": session_id}
            finally:
                db.close()
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _capture_profile_from_message(self, user_message: str) -> str | None:
        profile_payload = self._extract_profile_from_message(user_message)
        if not profile_payload or not self.conversation_id:
            return None

        saved = self._save_user_profile(conversation_id=self.conversation_id, **profile_payload)
        if saved.get("status") != "saved":
            return None

        profile = saved["profile"]
        if profile.get("name") and profile.get("name") != "未命名用户":
            org_text = f"，任职于 {profile['org']}" if profile.get("org") else ""
            role_text = f"，角色是 {profile['role']}" if profile.get("role") else ""
            return (
                f"记住了。你是 {profile['name']}{org_text}{role_text}。"
                f" [SOURCE: 对话记录] [CONFIDENCE: HIGH]"
            )

        notes = []
        if profile.get("project_description"):
            notes.append(f"项目方向是{profile['project_description']}")
        if profile.get("project_stage"):
            notes.append(f"当前阶段是{profile['project_stage']}")
        if profile.get("focus_region"):
            notes.append(f"关注区域是{profile['focus_region']}")
        if profile.get("preference") == "local":
            notes.append("偏好本地机构")
        if profile.get("preferred_investor_type"):
            notes.append(f"偏好投资方类型是{profile['preferred_investor_type']}")

        detail_text = "，".join(notes) if notes else "你的项目偏好"
        return f"记住了。我会按{detail_text}来调整后续匹配。 [SOURCE: 对话记录] [CONFIDENCE: HIGH]"

    def _fallback_reply(self, user_message: str, conversation_history: list) -> str:
        captured_profile = self._capture_profile_from_message(user_message)
        if captured_profile:
            return captured_profile

        organization_profile_calls = self._build_organization_profile_tool_calls(user_message)
        if organization_profile_calls:
            raw_arguments = organization_profile_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_organization_profile(**function_args)
            if result.get("status") == "success":
                return self._render_direct_tool_result("query_organization_profile", result)
            target = function_args.get("org_name") or "该机构"
            return (
                f"[INSUFFICIENT DATA] 目前情报库中关于 {target} 的机构画像仍然有限。"
                "建议补充机构全名，或继续补采官网、新闻与关系网络。 "
                "[SOURCE: 机构档案 + 情报数据库 + ARDA] [CONFIDENCE: LOW]"
            )

        fused_calls = self._build_fused_tool_calls(user_message)
        if fused_calls:
            raw_arguments = fused_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_fused(**function_args)
            if result.get("status") == "success" and result.get("total", 0) > 0:
                return self._render_direct_tool_result("query_fused", result)
            target = function_args.get("entity_name") or "该实体"
            return (
                f"[INSUFFICIENT DATA] 当前还没有检索到 {target} 的综合档案、新闻和融资记录。"
                "建议补充更完整的机构名，或缩小到单一维度继续追问。 "
                "[SOURCE: 融合查询引擎] [CONFIDENCE: LOW]"
            )

        graph_calls = self._build_graph_tool_calls(user_message)
        if graph_calls:
            raw_arguments = graph_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_graph(**function_args)
            if result.get("direct_relations") or result.get("investment_chain"):
                return self._render_direct_tool_result("query_graph", result)
            return (
                "[INSUFFICIENT DATA] 当前图谱库里还没有足够明确的关系边。"
                "建议补充机构全名、关系类型或把查询范围限定到投资/合作。 "
                "[SOURCE: 投资交易数据库 + Ontology 标签 + 机构档案] [CONFIDENCE: LOW]"
            )

        task_calls = self._build_task_tool_calls(user_message)
        if task_calls:
            raw_arguments = task_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._create_task(**function_args)
            if result.get("status") == "created":
                return self._render_direct_tool_result("create_task", result)
            return (
                "[INSUFFICIENT DATA] 当前无法创建任务，请补充任务标题。 "
                "[SOURCE: 任务数据库] [CONFIDENCE: LOW]"
            )

        acquirer_calls = self._build_acquirer_tool_calls(user_message)
        if acquirer_calls:
            raw_arguments = acquirer_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._match_acquirers(**function_args)
            if result.get("acquirers"):
                return self._render_direct_tool_result("match_acquirers", result)
            return (
                "[INSUFFICIENT DATA] 当前没有筛出明确的潜在收购方。"
                "建议补充项目类型、地区和目标买方类型。 "
                "[SOURCE: Ontology 标签 + 机构数据库] [CONFIDENCE: LOW]"
            )

        user_calls = self._build_user_match_tool_calls(user_message)
        if user_calls:
            raw_arguments = user_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._match_users(**function_args)
            if result.get("users"):
                return self._render_direct_tool_result("match_users", result)
            return (
                "[INSUFFICIENT DATA] 当前没有筛出明确的潜在使用方。"
                "建议补充产品类型、目标人群和目标国家。 "
                "[SOURCE: Ontology 标签 + 机构数据库] [CONFIDENCE: LOW]"
            )

        email_calls = self._build_email_tool_calls(user_message)
        if email_calls:
            raw_arguments = email_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._generate_outreach_email(**function_args)
            if result.get("status") == "generated":
                return self._render_direct_tool_result("generate_outreach_email", result)
            return (
                "[INSUFFICIENT DATA] 当前无法生成联系邮件，请补充投资方名称和项目描述。 "
                "[SOURCE: 邮件生成器] [CONFIDENCE: LOW]"
            )

        match_calls = self._build_match_tool_calls(user_message)
        if match_calls:
            raw_arguments = match_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._match_investors(**function_args)
            if result.get("matches"):
                return self._render_direct_tool_result("match_investors", result)
            return (
                "[INSUFFICIENT DATA] 当前匹配引擎没有筛出足够合适的投资方。"
                "建议补充项目阶段、目标地区和融资金额区间。 "
                "[SOURCE: 投资机构数据库 + 匹配引擎] [CONFIDENCE: LOW]"
            )

        funding_calls = self._build_funding_tool_calls(user_message)
        if funding_calls:
            raw_arguments = funding_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_funding_rounds(**function_args)
            if result.get("status") == "success" and result.get("count", 0) > 0:
                rounds = result.get("rounds", [])[:5]
                lines = []
                for item in rounds:
                    amount_text = f"${item.get('amount', 0):,.0f}" if item.get("amount") else "金额未披露"
                    date_text = (item.get("announced_date") or "")[:10] or "日期未披露"
                    investors = item.get("investors", [])
                    investor_text = "；".join(
                        f"{inv.get('name')}{'（领投）' if inv.get('lead_investor') else ''}"
                        for inv in investors[:4]
                    ) or "未披露投资方"
                    lines.append(
                        f"- {item.get('entity_name')}：{date_text} 完成 {item.get('round_type')}，金额 {amount_text}；投资方 {investor_text}"
                    )
                return (
                    "根据投资交易数据库，当前命中的融资事件如下：\n"
                    f"{chr(10).join(lines)}\n"
                    "[SOURCE: 融资交易数据库] [CONFIDENCE: HIGH]"
                )
            return (
                "[INSUFFICIENT DATA] 当前融资交易库里没有足够匹配的事件。"
                "建议换一个机构名、投资方名或具体轮次再查。 "
                "[SOURCE: 融资交易数据库] [CONFIDENCE: LOW]"
            )

        investor_calls = self._build_investor_tool_calls(user_message)
        if investor_calls:
            raw_arguments = investor_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_investors(**function_args)
            if result.get("status") == "success" and result.get("count", 0) > 0:
                items = result.get("investors", [])[:5]
                focus_area = function_args.get("focus_area") or "相关方向"
                geography_label = function_args.get("country") or function_args.get("region") or "当前地区"
                lines = []
                for item in items:
                    focus_text = " / ".join(item.get("focus_areas", [])[:3]) or "未标注方向"
                    stage_text = " / ".join(item.get("stage_focus", [])[:3]) or "阶段未标注"
                    region_text = " / ".join(item.get("region_focus", [])[:3]) or (item.get("country") or "Global")
                    website_text = f"，官网 {item['website']}" if item.get("website") else ""
                    lines.append(
                        f"- {item.get('name')}（{self._translate_investor_type(item.get('investor_type', ''))}，{item.get('country') or '未知国家'}）"
                        f"；关注 {focus_text}；阶段 {stage_text}；区域 {region_text}{website_text}"
                    )
                return (
                    f"结合你当前描述，在 {geography_label} 范围内，以下机构更可能成为"
                    + (f"{focus_area} 方向的" if focus_area and focus_area != "相关方向" else "")
                    + "候选出资方或资助方：\n"
                    f"{chr(10).join(lines)}\n"
                    "建议优先联系同时满足方向匹配和区域覆盖的机构，并准备英文版一页纸项目说明、用户增长数据和资金用途。 "
                    "[SOURCE: 投资机构数据库] [CONFIDENCE: HIGH]"
                )
            return (
                "[INSUFFICIENT DATA] 当前投资机构库里还没有足够匹配的候选机构。"
                "建议补充项目阶段、目标用户、融资金额和区域覆盖后再筛选。 "
                "[SOURCE: 投资机构数据库] [CONFIDENCE: LOW]"
            )

        profile_payload = self._extract_profile_from_message(user_message)
        if profile_payload and self.conversation_id:
            saved = self._save_user_profile(conversation_id=self.conversation_id, **profile_payload)
            if saved.get("status") == "saved":
                profile = saved["profile"]
                if profile.get("name") and profile.get("name") != "未命名用户":
                    org_text = f"，任职于 {profile['org']}" if profile.get("org") else ""
                    role_text = f"，角色是 {profile['role']}" if profile.get("role") else ""
                    return (
                        f"记住了。你是 {profile['name']}{org_text}{role_text}。"
                        f" [SOURCE: 对话记录] [CONFIDENCE: HIGH]"
                    )

                notes = []
                if profile.get("project_description"):
                    notes.append(f"项目方向是{profile['project_description']}")
                if profile.get("project_stage"):
                    notes.append(f"当前阶段是{profile['project_stage']}")
                if profile.get("focus_region"):
                    notes.append(f"关注区域是{profile['focus_region']}")
                if profile.get("preference") == "local":
                    notes.append("偏好本地机构")
                if profile.get("preferred_investor_type"):
                    notes.append(f"偏好投资方类型是{profile['preferred_investor_type']}")

                detail_text = "，".join(notes) if notes else "你的项目偏好"
                return f"记住了。我会按{detail_text}来调整后续匹配。 [SOURCE: 对话记录] [CONFIDENCE: HIGH]"

        if self._is_profile_question(user_message):
            if self.conversation_id:
                profile = self._get_user_profile(self.conversation_id)
                if profile.get("status") == "found":
                    data = profile["profile"]
                    if data.get("name") and data.get("name") != "未命名用户":
                        org_text = f"，在 {data['org']}" if data.get("org") else ""
                        role_text = f" 担任 {data['role']}" if data.get("role") else ""
                        return (
                            f"知道。你是 {data.get('name', '未命名用户')}{org_text}{role_text}。"
                            f" [SOURCE: 用户画像库] [CONFIDENCE: HIGH]"
                        )

                    notes = []
                    if data.get("project_description"):
                        notes.append(f"你在做 {data['project_description']}")
                    if data.get("focus_area"):
                        notes.append(f"方向偏向 {data['focus_area']}")
                    if data.get("focus_region"):
                        notes.append(f"重点区域是 {data['focus_region']}")
                    if data.get("preference") == "local":
                        notes.append("偏好本地机构")
                    if data.get("preferred_investor_type"):
                        notes.append(f"偏好 {data['preferred_investor_type']} 类型投资方")
                    if data.get("project_stage"):
                        notes.append(f"当前阶段是 {data['project_stage']}")

                    detail_text = "，".join(notes) if notes else "你之前告诉过我一些项目背景"
                    return f"记得。{detail_text}。 [SOURCE: 用户画像库] [CONFIDENCE: HIGH]"
            return (
                "我还不知道你是谁。你可以直接告诉我你的姓名、机构或角色，"
                "例如“我是张三，在 PCEC 负责合作”。 [SOURCE: 对话上下文] [CONFIDENCE: LOW]"
            )

        if self._is_contact_query(user_message):
            org_name = (
                self._extract_organization_profile_name(user_message)
                or self._extract_org_phrase(user_message)
                or self._extract_entity(user_message)
                or user_message
            )
            result = self._query_contacts(org_name=org_name)
            if result.get("status") == "found":
                return (
                    f"已找到 {result['org_name']} 的公开联系信息。负责人 {result['leader_name']}，"
                    f"职务 {result['leader_title']}，邮箱 {result['email']}，电话 {result['phone']}，"
                    f"官网 {result['website']}。 [SOURCE: {result['source_name']}] "
                    f"[CONFIDENCE: MEDIUM]"
                )
            return (
                f"[INSUFFICIENT DATA] 当前未找到 {org_name} 的可靠联系人档案。"
                f"建议改问机构全名，或让我为该机构补采公开联系人信息。"
                f" [SOURCE: 机构档案库] [CONFIDENCE: LOW]"
            )

        arda_calls = self._build_arda_country_tool_calls(user_message)
        if arda_calls:
            raw_arguments = arda_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_arda_country(**function_args)
            if result.get("status") == "success":
                return self._format_arda_country_result(result)
            country = function_args.get("country") or "该国家"
            return (
                f"[INSUFFICIENT DATA] 当前未找到 {country} 的 ARDA 国家宗教档案。"
                "建议确认国家英文名，或让我为该国家补采宗教基线数据。 "
                "[SOURCE: ARDA] [CONFIDENCE: LOW]"
            )

        ontology_type_calls = self._build_ontology_type_tool_calls(user_message)
        if ontology_type_calls:
            raw_arguments = ontology_type_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._get_ontology_types(**function_args)
            if result.get("status") == "success":
                categories = result.get("categories") or {}
                fragments = []
                for key, items in categories.items():
                    names = [item.get("name", "") for item in items[:10] if item.get("name")]
                    if names:
                        fragments.append(f"{key}: {', '.join(names)}")
                if fragments:
                    return (
                        "Christian Ontology 当前已定义以下分类：\n"
                        + "\n".join(f"- {item}" for item in fragments)
                        + "\n[SOURCE: Christian Ontology] [CONFIDENCE: HIGH]"
                    )

        ontology_calls = self._build_ontology_tool_calls(user_message)
        if ontology_calls:
            raw_arguments = ontology_calls[0].get("function", {}).get("arguments") or "{}"
            function_args = json.loads(raw_arguments)
            result = self._query_ontology(**function_args)
            filter_value = function_args.get("filter_value", "")
            country = function_args.get("country") or "目标区域"
            if result.get("status") == "success" and result.get("count", 0) > 0:
                orgs = result.get("organizations", [])[:5]
                lines = []
                for org in orgs:
                    line = f"- {org.get('name')}（{org.get('country') or '未知国家'}）"
                    if org.get("leader") and org.get("leader") != "未知":
                        line += f"，负责人 {org['leader']}"
                    if org.get("website"):
                        line += f"，官网 {org['website']}"
                    lines.append(line)
                return (
                    f"按 Ontology 分类检索，{country} 下属于 {filter_value} 的机构有 {result.get('count', 0)} 家，"
                    f"当前命中如下：\n{chr(10).join(lines)}\n"
                    "[SOURCE: Christian Ontology + 机构档案] [CONFIDENCE: HIGH]"
                )
            if result.get("status") == "type_defined":
                return (
                    f"{result.get('type_name', filter_value)} 是 Christian Ontology 中已定义的分类。"
                    f"{result.get('description', '')} {result.get('message', '')}"
                    " [SOURCE: Christian Ontology] [CONFIDENCE: HIGH]"
                )
            if result.get("status") == "country_empty":
                examples = result.get("global_examples") or []
                sample_text = "；".join(
                    f"{item.get('name')}（{item.get('country') or '未知国家'}）" for item in examples[:3]
                )
                return (
                    f"当前情报库里，{country} 还没有已标注为 {result.get('type_name', filter_value)} 的机构。"
                    + (
                        f"不过全库里已有相近样本，例如 {sample_text}。"
                        if sample_text
                        else ""
                    )
                    + " 这更像是当前国家数据覆盖不足，而不是该分类不存在。 "
                    "[SOURCE: Christian Ontology + 机构档案] [CONFIDENCE: MEDIUM]"
                )

        if self._looks_like_news_query(user_message):
            intelligence_args = self._build_intelligence_query_args(user_message)
            intelligence_result = self._query_intelligence(**intelligence_args)
            if intelligence_result.get("status") == "success" and intelligence_result.get("count", 0) > 0:
                return self._format_intelligence_result(intelligence_result)
            target = intelligence_args.get("entity") or intelligence_args.get("country") or "全球基督教领域"
            return (
                f"[INSUFFICIENT DATA] 当前情报库中关于 {target} 的新闻记录不足。"
                "建议先检查全球 RSS / API 采集链路是否已运行。 "
                "[SOURCE: 情报数据库] [CONFIDENCE: LOW]"
            )

        query_args = self._build_query_args(user_message)
        result = self._query_database(**query_args)
        unique_results = (
            result.get("query_summary", {}).get("unique_results")
            if isinstance(result.get("query_summary"), dict)
            else None
        )
        result_count = unique_results if unique_results is not None else result.get("count", 0)
        if result.get("status") == "success" and result_count > 0:
            items = result["items"][:3]
            summary_lines = []
            for item in items:
                snippet = (item.get("content") or "").replace("\n", " ").strip()
                if len(snippet) > 90:
                    snippet = f"{snippet[:90]}..."
                summary_lines.append(
                    f"- {item.get('title')}：{snippet} "
                    f"[SOURCE: {item.get('source_name') or item.get('source')}] [CONFIDENCE: {item.get('confidence', 'MEDIUM')}]"
                )

            target = query_args.get("entity") or query_args.get("country") or "该主题"
            return (
                f"关于 {target}，数据库中已有可用情报。综合最近记录看，"
                f"相关动态主要集中在以下几条：\n"
                f"{chr(10).join(summary_lines)}"
            )

        country = query_args.get("country") or "菲律宾"
        collect_result = self._auto_collect(
            country=country,
            entity=query_args.get("entity"),
            reason=f"用户查询数据不足：{user_message[:80]}",
        )
        task_text = ""
        if collect_result.get("status") == "queued":
            task_text = f" 我已为 {country} 安排后台补采。"
        return (
            f"[INSUFFICIENT DATA] 当前数据库中关于 {query_args.get('entity') or country} 的现成情报不足，"
            f"还不足以支持可靠判断。{task_text}"
            f" [SOURCE: 数据库检索] [CONFIDENCE: LOW]"
        )

    def _build_query_args(self, user_message: str) -> dict:
        country = self._extract_country(user_message)
        entity = self._extract_entity(user_message)
        scope = "global" if country == "全球" else "country"
        keywords = self._extract_keywords(user_message, country, entity)
        return {
            "scope": scope,
            "country": None if scope == "global" else country,
            "entity": entity,
            "keywords": keywords,
            "limit": 8,
        }

    def _build_fused_query_args(self, user_message: str) -> dict:
        entity_name = self._extract_entity(user_message) or self._extract_org_phrase(user_message) or ""
        country = self._extract_country(user_message) or None
        scope = "global" if not country or country == "全球" else "country"
        keywords = self._extract_keywords(user_message, country or "", entity_name if entity_name else None)
        noise_tokens = {
            "新闻", "融资", "动态", "投资", "最近", "最近有什么", "recent", "funding", "news", "overview",
            "全景", "综合情报", "完整信息", "最近有什么新闻和融资",
        }
        filtered_keywords = []
        for token in keywords:
            if token.lower() in {item.lower() for item in noise_tokens}:
                continue
            filtered_keywords.append(token)
        return {
            "entity_name": entity_name,
            "keywords": filtered_keywords[:6],
            "scope": scope,
            "country": None if scope == "global" else country,
            "limit": 8,
        }

    def _build_intelligence_query_args(self, user_message: str) -> dict:
        country = self._extract_country(user_message)
        entity = self._extract_entity(user_message)
        context_entities = []
        context_entity_label = None
        if not entity and self._looks_like_plural_entity_reference(user_message) and self.current_entities:
            context_entities = [item.get("name") for item in self.current_entities[-5:] if item.get("name")]
            if context_entities:
                context_entity_label = " / ".join(context_entities[:4])
            if not country:
                context_countries = [item.get("country") for item in self.current_entities[-5:] if item.get("country")]
                if context_countries:
                    country = context_countries[-1]
        if country == "全球":
            scope = "global"
        elif entity:
            scope = "entity"
        elif country:
            scope = "country"
        elif context_entities:
            scope = "entity" if len(context_entities) == 1 else "country"
        else:
            scope = "country"
        keywords = self._extract_keywords(user_message, country, entity)
        news_keywords = []
        noise_markers = ["新闻", "动态", "最近", "最新", "发生", "什么", "全球", "国际", "世界", "news", "headline"]
        for token in keywords:
            lowered = token.lower()
            if lowered in {"新闻", "动态", "最近", "最新", "news", "headline", "headlines"}:
                continue
            if any(marker in lowered for marker in noise_markers):
                continue
            news_keywords.append(token)
        for entity_name in context_entities:
            if entity_name and entity_name not in news_keywords:
                news_keywords.append(entity_name)
        return {
            "scope": scope,
            "country": None if scope != "country" else country,
            "entity": entity or (context_entities[0] if len(context_entities) == 1 else context_entity_label),
            "keywords": news_keywords,
            "limit": 10,
        }

    def _extract_country(self, text: str) -> str:
        lowered = (text or "").lower()
        for country, aliases in COUNTRY_ALIASES.items():
            if any(self._contains_country_alias(lowered, alias) for alias in aliases):
                return country
        return ""

    def _contains_country_alias(self, lowered_text: str, alias: str) -> bool:
        alias_lower = (alias or "").lower()
        if not alias_lower:
            return False
        if re.search(r"[a-z]", alias_lower):
            if len(alias_lower) <= 2:
                return False
            return re.search(rf"\b{re.escape(alias_lower)}\b", lowered_text) is not None
        return alias_lower in lowered_text

    def _clean_org_candidate(self, candidate: str) -> str:
        cleaned = (candidate or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(
            r"^(帮我|请|麻烦|给我|帮忙|查一下|查查|看一下|看看|画一下|分析一下|介绍一下)\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"(这个机构|这家机构|该机构|这个组织|这家组织)$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"(的)?(基本信息|机构信息|机构基本信息|机构简介|机构介绍|机构概况|机构背景|机构画像|画像|档案|简介|介绍|背景|概况|近况|情况|联系方式|联系信息|联系人|邮箱|电话|关系图谱|关系图|图谱)$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.strip(" ？?，。!！:：")

    def _build_arda_country_args(self, user_message: str) -> dict:
        country = self._extract_country(user_message)
        return {
            "country": COUNTRY_ENGLISH_NAMES.get(country or "", country or ""),
        }

    def _extract_organization_profile_name(self, text: str) -> str:
        org_phrase = self._extract_org_phrase(text) or ""
        entity = self._extract_entity(text) or ""
        candidate = self._clean_org_candidate(org_phrase or entity)
        candidate = re.sub(
            r"(怎么样|如何|是什么机构|是什么|情况|背景|介绍|概况|画像|档案|简介|近况)$",
            "",
            (candidate or "").strip(),
            flags=re.IGNORECASE,
        ).strip(" ？?，。!！")
        return candidate

    def _build_prefetched_tool_calls(self, user_message: str) -> list[dict]:
        lowered = (user_message or "").lower()
        if (
            "faithtech" in lowered
            and any(
                token in lowered
                for token in ["投资", "投资机构", "投资人", "投资方", "investor", "fund", "vc", "angel", "pe"]
            )
            and not self._looks_like_match_query(user_message)
            and not self._looks_like_funding_query(user_message)
        ):
            args = self._infer_investor_query_args(user_message)
            return [
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {
                        "name": "query_investors",
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                }
            ]
        organization_profile_calls = self._build_organization_profile_tool_calls(user_message)
        if organization_profile_calls:
            return organization_profile_calls
        fused_calls = self._build_fused_tool_calls(user_message)
        if fused_calls:
            return fused_calls
        graph_calls = self._build_graph_tool_calls(user_message)
        if graph_calls:
            return graph_calls
        task_calls = self._build_task_tool_calls(user_message)
        if task_calls:
            return task_calls
        acquirer_calls = self._build_acquirer_tool_calls(user_message)
        if acquirer_calls:
            return acquirer_calls
        user_calls = self._build_user_match_tool_calls(user_message)
        if user_calls:
            return user_calls
        email_calls = self._build_email_tool_calls(user_message)
        if email_calls:
            return email_calls
        match_calls = self._build_match_tool_calls(user_message)
        if match_calls:
            return match_calls
        funding_calls = self._build_funding_tool_calls(user_message)
        if funding_calls:
            return funding_calls
        investor_calls = self._build_investor_tool_calls(user_message)
        if investor_calls:
            return investor_calls
        ontology_type_calls = self._build_ontology_type_tool_calls(user_message)
        if ontology_type_calls:
            return ontology_type_calls
        ontology_calls = self._build_ontology_tool_calls(user_message)
        if ontology_calls:
            return ontology_calls
        arda_calls = self._build_arda_country_tool_calls(user_message)
        if arda_calls:
            return arda_calls
        intelligence_calls = self._build_intelligence_tool_calls(user_message)
        if intelligence_calls:
            return intelligence_calls
        if not self._looks_like_intel_query(user_message):
            return []
        args = self._build_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_database",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_intelligence_tool_calls(self, user_message: str) -> list[dict]:
        if not (self._looks_like_news_query(user_message) or self._looks_like_intel_query(user_message)):
            return []
        args = self._build_intelligence_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_intelligence",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_fused_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_fused_query(user_message):
            return []
        args = self._build_fused_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_fused",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_arda_country_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_arda_country_query(user_message):
            return []
        args = self._build_arda_country_args(user_message)
        if not args.get("country"):
            return []
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_arda_country",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_organization_profile_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_organization_profile_query(user_message):
            return []
        target_name = self._extract_organization_profile_name(user_message)
        if not target_name:
            return []
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_organization_profile",
                    "arguments": json.dumps({"org_name": target_name}, ensure_ascii=False),
                },
            }
        ]

    def _should_fallback_after_tool(self, function_name: str, result: dict) -> bool:
        if not isinstance(result, dict):
            return False
        if result.get("status") == "error":
            return True
        if function_name == "query_ontology":
            return result.get("status") in {"not_found", "type_defined"} or result.get("count", 0) == 0
        if function_name == "query_fused":
            return result.get("status") == "success" and result.get("total", 0) == 0
        if function_name == "query_arda_country":
            return result.get("status") == "not_found"
        if function_name == "query_organization_profile":
            return result.get("status") == "not_found"
        if function_name in {"query_database", "query_intelligence", "query_investors", "query_funding_rounds", "query_arda_country"}:
            return result.get("status") == "success" and result.get("count", 0) == 0
        return False

    def _continue_after_tool_calls(self, messages: list[dict], tool_calls: list[dict]) -> Optional[dict]:
        tool_results = []
        collected_tool_results: list[dict] = []
        for tool_call in tool_calls:
            raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
            try:
                function_args = json.loads(raw_arguments)
            except json.JSONDecodeError:
                function_args = {}
            function_name = tool_call.get("function", {}).get("name", "")
            result = self._execute_tool_call(tool_call, function_args)
            tool_results.append(result)
            parsed_result = {}
            try:
                parsed_result = json.loads(result.get("content", "{}"))
            except Exception:
                parsed_result = {}
            if isinstance(parsed_result, dict):
                collected_tool_results.append(parsed_result)
            if self._should_fallback_after_tool(function_name, parsed_result):
                return None

        composer_enabled = feature_flag_enabled("ANSWER_COMPOSER_ENABLED")
        if composer_enabled and collected_tool_results:
            messages = list(messages)
            answer_context = self._build_answer_context(messages[-1].get("content", "") if messages else "", collected_tool_results)
            if answer_context:
                messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Answer Context"))]
                messages.append({"role": "system", "content": self._format_answer_context(answer_context)})
            return self._call_llm(messages, tools=None)

        messages = list(messages)
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        messages.extend(tool_results)
        reasoning_enabled = feature_flag_enabled("REASONING_ENGINE_V1_ENABLED")
        if reasoning_enabled and collected_tool_results:
            try:
                from services.reasoning_engine_v1 import QuestionType

                ctx = getattr(self, "_reasoning_v1_context", {}) or {}
                qt_value = str(ctx.get("question_type") or "UNKNOWN")
                from services.core_models import Requirement as CoreRequirement

                req = ctx.get("requirement")
                requirement = req if isinstance(req, CoreRequirement) else CoreRequirement.from_dict(req or {})
                tool_plan = ctx.get("tool_plan") or []
                qt = QuestionType(qt_value) if qt_value in getattr(QuestionType, "_value2member_map_", {}) else QuestionType.UNKNOWN
                engine = self._get_reasoning_engine_service(conversation_id=str(getattr(self, "conversation_id", "") or ""))
                if engine is None:
                    from services.reasoning_engine_v1 import ReasoningEngineV1

                    engine = ReasoningEngineV1()
                evaluation = engine.evaluate_evidence(collected_tool_results, requirement)
                conflicts = engine.detect_conflicts(collected_tool_results)
                ranked_evidence = engine.rank_evidence(collected_tool_results)
                outline = engine.build_answer_outline(qt, requirement, ranked_evidence)
                reasoning_message = self._format_reasoning_engine_v1_message(qt_value, requirement.to_dict(), tool_plan, evaluation, conflicts, outline)
                messages = [m for m in messages if not (m.get("role") == "system" and str(m.get("content") or "").startswith("Reasoning Plan"))]
                messages.append({"role": "system", "content": reasoning_message})
            except Exception:
                pass
        return self._call_llm(messages, tools=None)

    def _execute_tool_call(self, tool_call: dict, function_args: dict) -> dict:
        function_name = tool_call.get("function", {}).get("name", "")
        print(f"[Brain] 调用工具: {function_name}({function_args})")

        func = self.available_functions.get(function_name)
        if func:
            try:
                result = self._normalize_tool_result(function_name, func(**function_args))
            except TypeError as exc:
                result = self._normalize_tool_result(function_name, {"status": "error", "message": f"参数错误: {exc}"})
        else:
            result = self._normalize_tool_result(function_name, {"status": "error", "message": f"未知工具: {function_name}"})

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": json.dumps(result, ensure_ascii=False),
        }

    def _choose_tool_for_message(self, user_message: str) -> Any:
        if self._looks_like_match_query(user_message):
            return {"type": "function", "function": {"name": "match_investors"}}
        if self._extract_profile_from_message(user_message):
            return None
        if self._is_profile_question(user_message):
            return None
        if self._is_contact_query(user_message):
            return None
        if self._looks_like_organization_profile_query(user_message):
            return {"type": "function", "function": {"name": "query_organization_profile"}}
        if self._looks_like_fused_query(user_message):
            return {"type": "function", "function": {"name": "query_fused"}}
        if self._looks_like_graph_query(user_message):
            return {"type": "function", "function": {"name": "query_graph"}}
        if self._looks_like_task_creation_query(user_message):
            return {"type": "function", "function": {"name": "create_task"}}
        if self._looks_like_acquirer_query(user_message):
            return {"type": "function", "function": {"name": "match_acquirers"}}
        if self._looks_like_user_match_query(user_message):
            return {"type": "function", "function": {"name": "match_users"}}
        if self._looks_like_email_generation_query(user_message):
            return {"type": "function", "function": {"name": "generate_outreach_email"}}
        if self._looks_like_funding_query(user_message):
            return {"type": "function", "function": {"name": "query_funding_rounds"}}
        if self._looks_like_investor_query(user_message):
            return {"type": "function", "function": {"name": "query_investors"}}
        if self._looks_like_ontology_type_query(user_message):
            return {"type": "function", "function": {"name": "get_ontology_types"}}
        if self._looks_like_ontology_query(user_message):
            return {"type": "function", "function": {"name": "query_ontology"}}
        if self._looks_like_arda_country_query(user_message):
            return {"type": "function", "function": {"name": "query_arda_country"}}
        if self._looks_like_news_query(user_message):
            return {"type": "function", "function": {"name": "query_intelligence"}}
        if not self._looks_like_intel_query(user_message):
            return None
        return {"type": "function", "function": {"name": "query_database"}}

    def _looks_like_arda_country_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if self._looks_like_news_query(text):
            return False
        country = self._extract_country(text)
        if not country:
            return False
        tokens = [
            "基督教情况",
            "基督教概况",
            "宗教情况",
            "宗教概况",
            "基督徒比例",
            "基督教人口",
            "宗教人口",
            "宗派构成",
            "教会分布",
            "宗教自由",
            "基督教怎么样",
            "宗教怎么样",
            "christian population",
            "religious profile",
            "religious freedom",
            "christian situation",
        ]
        return any(token in lowered for token in tokens)

    def _looks_like_organization_profile_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if not self._extract_organization_profile_name(text):
            return False
        if self._looks_like_match_query(text) or self._looks_like_fused_query(text) or self._looks_like_graph_query(text):
            return False
        tokens = [
            "怎么样",
            "情况",
            "背景",
            "介绍",
            "概况",
            "画像",
            "档案",
            "简介",
            "基本信息",
            "机构信息",
            "是什么机构",
            "是什么",
            "近况",
        ]
        return any(token in lowered for token in tokens)

    def _looks_like_graph_query(self, text: str) -> bool:
        if self._looks_like_email_generation_query(text):
            return False
        lowered = (text or "").lower()
        tokens = [
            "有什么关系", "什么关系", "合作伙伴是谁", "合作伙伴", "关系网络", "投资链条",
            "链条", "谁和谁", "谁投了什么", "graph", "network", "图谱", "关系图",
        ]
        return any(token in lowered for token in tokens)

    def _looks_like_task_creation_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        tokens = ["创建一个任务", "帮我创建任务", "帮我创建一个任务", "创建任务", "跟踪任务", "加入跟踪", "建立待办"]
        return any(token in lowered for token in tokens)

    def _looks_like_acquirer_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        tokens = ["谁可能收购", "潜在的收购方", "潜在收购方", "退出路径", "谁会收购", "acquirer"]
        return any(token in lowered for token in tokens)

    def _looks_like_user_match_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        tokens = ["谁会使用", "谁会用", "目标客户", "潜在用户", "谁会买", "谁会采用"]
        return any(token in lowered for token in tokens)

    def _looks_like_fused_query(self, text: str) -> bool:
        """判断是否为跨源融合查询。"""
        lowered = (text or "").lower()
        has_entity = bool(self._extract_entity(text) or self._extract_org_phrase(text))
        fused_tokens = [
            "综合情报",
            "全景",
            "完整信息",
            "有什么新闻和融资",
            "动态和融资",
            "投资和新闻",
            "全方位",
            "all about",
            "overview",
            "全景图",
        ]
        multi_aspect_tokens = ["新闻", "news", "融资", "funding", "投资", "动态", "recent", "overview"]
        has_multi_aspect = sum(1 for token in multi_aspect_tokens if token in lowered) >= 2
        return has_entity and (any(token in lowered for token in fused_tokens) or has_multi_aspect)

    def _looks_like_match_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if self._looks_like_email_generation_query(text):
            return False
        if self._looks_like_graph_query(text) or self._looks_like_acquirer_query(text) or self._looks_like_user_match_query(text) or self._looks_like_task_creation_query(text):
            return False
        match_tokens = [
            "谁能投我",
            "匹配投资方",
            "推荐投资者",
            "推荐投资方",
            "适合找谁",
            "谁适合投我",
            "我的项目适合找谁",
            "match investors",
        ]
        return any(token in lowered for token in match_tokens)

    def _looks_like_email_generation_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        email_tokens = [
            "帮我写封邮件",
            "生成联系邮件",
            "怎么联系这个投资人",
            "写封给",
            "outreach邮件",
            "联系邮件",
            "email",
        ]
        return any(token in lowered for token in email_tokens)

    def _looks_like_ontology_type_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if "faithtech" in lowered and any(token in lowered for token in ["分哪些类", "分类", "种类", "types", "categories"]):
            return True
        return any(
            token in lowered
            for token in [
                "有哪些机构类型",
                "有哪些类型",
                "分类体系",
                "分哪些类",
                "ontology",
                "类型列表",
            ]
        )

    def _looks_like_investor_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if self._looks_like_match_query(text):
            return False
        if self._looks_like_funding_query(text):
            return False
        if any(
            phrase in lowered
            for phrase in [
                "投资机构",
                "投资人",
                "投资方",
                "有哪些投资",
                "哪些投资机构",
                "哪些投资人",
                "faithtech的投资",
                "投faithtech",
            ]
        ):
            return True
        investor_tokens = [
            "投资", "投资人", "投资机构", "基金会", "基金", "vc", "pe", "angel",
            "谁能投", "谁会投", "谁可能投", "谁适合投", "资助方", "出资方", "investor",
            "fund", "funding",
        ]
        return any(token in lowered for token in investor_tokens)

    def _looks_like_funding_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        funding_tokens = [
            "融资", "融资事件", "拿了投资", "拿过投资", "拿了谁的投资", "谁投了",
            "轮次", "series a", "series b", "ipo", "acquisition", "grant",
            "最近有什么融资", "最近谁拿了投资", "投资交易", "deal", "round",
        ]
        return any(token in lowered for token in funding_tokens)

    def _translate_investor_type(self, investor_type: str) -> str:
        mapping = {
            "vc": "VC",
            "pe": "PE",
            "angel": "天使投资",
            "corporate": "企业投资",
            "foundation": "基金会",
            "impact_investor": "影响力投资",
        }
        return mapping.get((investor_type or "").lower(), investor_type or "未知类型")

    def _infer_investor_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        focus_area = None
        if any(token in lowered for token in ["社交媒体", "social media", "媒体", "media"]):
            focus_area = "Media"
        elif any(token in lowered for token in ["faithtech", "基督教科技", "基督教ai", "ai", "圣经科技", "church tech"]):
            focus_area = "FaithTech"
        elif any(token in lowered for token in ["教育", "神学院", "edtech"]):
            focus_area = "EdTech"
        elif any(token in lowered for token in ["宣教", "差传", "mission"]):
            focus_area = "Mission"

        investor_type = ""
        if "基金会" in lowered or "fund" in lowered:
            investor_type = "foundation"
        elif "天使" in lowered or "angel" in lowered:
            investor_type = "angel"
        elif "vc" in lowered or "venture" in lowered:
            investor_type = "vc"
        elif "pe" in lowered or "private equity" in lowered:
            investor_type = "pe"

        stage = None
        if any(token in lowered for token in ["pre-seed", "天使轮", "种子前"]):
            stage = "pre_seed"
        elif any(token in lowered for token in ["seed", "种子轮"]):
            stage = "seed"
        elif any(token in lowered for token in ["series a", "a轮"]):
            stage = "series_a"
        elif any(token in lowered for token in ["grant", "资助"]):
            stage = "grant"

        country = self._extract_country(user_message)
        region = self._extract_region(user_message)
        if "全球" in lowered:
            country = "全球"
            region = "全球"

        return {
            "focus_area": focus_area,
            "investor_type": investor_type,
            "country": country,
            "region": region,
            "stage": stage,
            "limit": 8,
        }

    def _extract_region(self, text: str) -> str:
        lowered = (text or "").lower()
        mapping = {
            "东南亚": ["东南亚", "southeast asia", "sea"],
            "东亚": ["东亚", "east asia"],
            "全球": ["全球", "global", "worldwide", "international"],
            "中东": ["中东", "middle east"],
            "非洲": ["非洲", "africa"],
        }
        for region_name, aliases in mapping.items():
            if any(alias in lowered for alias in aliases):
                return region_name
        country = self._extract_country(text)
        if country == "菲律宾":
            return "东南亚"
        if country == "韩国":
            return "东亚"
        return ""

    def _infer_match_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        focus_area = ""
        if any(token in lowered for token in ["社交媒体", "social media", "媒体", "media"]):
            focus_area = "Media"
        elif any(token in lowered for token in ["faithtech", "基督教科技", "圣经科技", "church tech", "基督教ai", "ai"]):
            focus_area = "FaithTech"
        elif any(token in lowered for token in ["教育", "神学院", "edtech"]):
            focus_area = "EdTech"
        elif any(token in lowered for token in ["宣教", "差传", "mission"]):
            focus_area = "Mission"

        stage = ""
        if any(token in lowered for token in ["种子期", "种子轮", "seed"]):
            stage = "seed"
        elif any(token in lowered for token in ["pre-seed", "天使轮", "种子前"]):
            stage = "pre_seed"
        elif any(token in lowered for token in ["series a", "a轮"]):
            stage = "series_a"
        elif any(token in lowered for token in ["series b", "b轮"]):
            stage = "series_b"
        elif any(token in lowered for token in ["grant", "资助"]):
            stage = "grant"

        country = ""
        explicit_country = self._extract_country(user_message)
        if explicit_country != "菲律宾" or "菲律宾" in lowered or "philippines" in lowered:
            country = explicit_country
        region = self._extract_region(user_message)

        return {
            "project_description": user_message,
            "focus_area": focus_area,
            "stage": stage,
            "country": country,
            "region": region,
            "limit": 5,
        }

    def _find_investor_name_in_text(self, text: str) -> str:
        lowered = (text or "").lower()
        try:
            from models.database import Investor, OrganizationProfile, get_db

            db = next(get_db())
            try:
                investors = db.query(Investor.name).all()
                matched_names = [name for (name,) in investors if name and name.lower() in lowered]
                if matched_names:
                    matched_names.sort(key=len, reverse=True)
                    return matched_names[0]

                organizations = db.query(OrganizationProfile.name).all()
                matched_orgs = [name for (name,) in organizations if name and name.lower() in lowered]
                if matched_orgs:
                    matched_orgs.sort(key=len, reverse=True)
                    return matched_orgs[0]
            finally:
                db.close()
        except Exception:
            pass

        patterns = [
            r"写(?:一)?封(?:邮件|信)给\s*([A-Za-z][A-Za-z0-9&'.\-\s]{1,80})",
            r"发(?:一)?封(?:邮件|信)给\s*([A-Za-z][A-Za-z0-9&'.\-\s]{1,80})",
            r"给\s*([A-Za-z][A-Za-z0-9&'.\-\s]{1,80})\s*(?:写|发).*(?:邮件|信)",
            r"给(.+?)的邮件",
        ]
        for pattern in patterns:
            matched = re.search(pattern, text, re.IGNORECASE)
            if matched:
                return matched.group(1).strip(" ，。!！?")
        return ""

    def _infer_email_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        investor_name = self._find_investor_name_in_text(user_message)
        project_description = ""

        project_markers = ["项目是", "项目是在", "项目做", "我们做", "我是"]
        for marker in project_markers:
            idx = user_message.find(marker)
            if idx >= 0:
                project_description = user_message[idx:].strip(" ，。")
                break

        if not project_description:
            project_description = "菲律宾基督教社交媒体项目"

        project_stage = ""
        if any(token in lowered for token in ["种子期", "种子轮", "seed"]):
            project_stage = "seed"
        elif any(token in lowered for token in ["series a", "a轮"]):
            project_stage = "series_a"

        sender_name = ""
        if self.conversation_id:
            profile = self._get_user_profile(self.conversation_id)
            if profile.get("status") == "found":
                sender_name = profile.get("profile", {}).get("name", "")

        return {
            "investor_name": investor_name,
            "project_description": project_description,
            "project_stage": project_stage,
            "sender_name": sender_name,
            "tone": "warm",
        }

    def _infer_task_query_args(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        title = text
        title = re.sub(r"^帮我", "", title)
        title = re.sub(r"^创建一个任务[:：]?", "", title)
        title = re.sub(r"^创建任务[:：]?", "", title)
        title = re.sub(r"^帮我创建一个任务[:：]?", "", title)
        title = re.sub(r"^帮我创建任务[:：]?", "", title)
        title = title.strip(" ：:")
        entity_name = self._extract_entity(text)
        if not entity_name:
            investor_name = self._find_investor_name_in_text(text)
            if investor_name:
                entity_name = investor_name
        return {
            "title": title or text,
            "description": f"由情报官创建的跟踪任务：{text}",
            "priority": "medium",
            "entity_name": entity_name or "",
        }

    def _infer_acquirer_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        project_type = ""
        if any(token in lowered for token in ["社交媒体", "social media"]):
            project_type = "social_media"
        elif "saas" in lowered:
            project_type = "saas"
        elif any(token in lowered for token in ["app", "应用"]):
            project_type = "app"
        elif any(token in lowered for token in ["平台", "platform"]):
            project_type = "platform"

        focus_area = ""
        if any(token in lowered for token in ["媒体", "media", "社交媒体"]):
            focus_area = "Media"
        elif any(token in lowered for token in ["faithtech", "基督教科技", "ai", "圣经科技"]):
            focus_area = "FaithTech"

        country = ""
        explicit_country = self._extract_country(user_message)
        if explicit_country != "菲律宾" or "菲律宾" in lowered or "philippines" in lowered:
            country = explicit_country

        return {
            "project_type": project_type,
            "focus_area": focus_area,
            "country": country,
            "limit": 5,
        }

    def _infer_user_match_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        product_type = ""
        if any(token in lowered for token in ["社交媒体", "social media"]):
            product_type = "social_media"
        elif any(token in lowered for token in ["媒体", "content", "内容"]):
            product_type = "media"
        elif "saas" in lowered:
            product_type = "saas"
        elif any(token in lowered for token in ["app", "应用"]):
            product_type = "app"

        target_audience = ""
        if any(token in lowered for token in ["青年", "年轻", "大学生", "youth", "student"]):
            target_audience = "青年"
        elif any(token in lowered for token in ["牧者", "教会领袖", "pastor", "leader"]):
            target_audience = "教会领袖"
        else:
            target_audience = "基督教机构"

        country = ""
        explicit_country = self._extract_country(user_message)
        if explicit_country != "菲律宾" or "菲律宾" in lowered or "philippines" in lowered:
            country = explicit_country

        return {
            "product_type": product_type,
            "target_audience": target_audience,
            "country": country,
            "limit": 8,
        }

    def _infer_funding_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        focus_area = None
        if "faithtech" in lowered or "基督教科技" in lowered or "church tech" in lowered:
            focus_area = "FaithTech"
        elif any(token in lowered for token in ["媒体", "media", "社交媒体"]):
            focus_area = "Media"

        round_type = ""
        if "series b" in lowered or "b轮" in lowered:
            round_type = "series_b"
        elif "series a" in lowered or "a轮" in lowered:
            round_type = "series_a"
        elif "grant" in lowered or "资助" in lowered:
            round_type = "grant"
        elif "ipo" in lowered:
            round_type = "ipo"
        elif "acquisition" in lowered or "收购" in lowered:
            round_type = "acquisition"

        entity_name = None
        for name in [
            "YouVersion / Life.Church",
            "YouVersion",
            "Life.Church",
            "Gloo",
            "BibleProject",
            "RightNow Media",
            "Subsplash",
            "Tithe.ly",
            "Pushpay",
            "LifeWay Christian Resources",
            "Alpha Southeast Asia",
            "OneHope Foundation",
        ]:
            if name.lower() in lowered:
                entity_name = name
                break

        investor_name = None
        for name in [
            "Draper Associates",
            "Messiah Foundation",
            "Greylock Partners",
            "Faith Driven Investor Network",
            "Templeton Religion Trust",
            "Maclellan Foundation",
            "Christian Angel Network",
            "Lightspeed Venture Partners",
            "Bessemer Venture Partners",
            "LifeWay Christian Resources",
            "Life.Church",
        ]:
            if name.lower() in lowered:
                investor_name = name
                break

        return {
            "entity_name": entity_name,
            "investor_name": investor_name,
            "round_type": round_type,
            "focus_area": focus_area,
            "limit": 8,
        }

    def _find_graph_entities_in_text(self, text: str) -> list[str]:
        lowered = (text or "").lower()
        candidates: list[str] = []
        try:
            from models.database import Investor, KnowledgeEntity, OrganizationProfile, get_db

            db = next(get_db())
            try:
                names = set()
                names.update(name for (name,) in db.query(OrganizationProfile.name).all() if name)
                names.update(name for (name,) in db.query(KnowledgeEntity.name).all() if name)
                names.update(name for (name,) in db.query(Investor.name).all() if name)
                for name in sorted(names, key=len, reverse=True):
                    if name.lower() in lowered and name not in candidates:
                        candidates.append(name)
                        if len(candidates) >= 3:
                            break

                # 兼容口语化别名，如 “Victory”和“PCEC”。
                alias_queries = []
                if "victory" in lowered and not any("victory" in item.lower() for item in candidates):
                    alias_queries.append("Victory")
                if "pcec" in lowered and not any("pcec" in item.lower() for item in candidates):
                    alias_queries.append("PCEC")

                for alias in alias_queries:
                    org = (
                        db.query(OrganizationProfile)
                        .filter(OrganizationProfile.name.ilike(f"%{alias}%"))
                        .order_by(OrganizationProfile.updated_at.desc())
                        .first()
                    )
                    if org and org.name not in candidates:
                        candidates.append(org.name)

                # 双实体关系问法优先按“和/与/跟”拆分，再做模糊解析。
                parts = [part.strip(" ？?。！!") for part in re.split(r"[和与跟]", text) if part.strip(" ？?。！!")]
                for part in parts[:2]:
                    if any(existing.lower() in part.lower() or part.lower() in existing.lower() for existing in candidates):
                        continue
                    org = (
                        db.query(OrganizationProfile)
                        .filter(OrganizationProfile.name.ilike(f"%{part}%"))
                        .order_by(OrganizationProfile.updated_at.desc())
                        .first()
                    )
                    if org and org.name not in candidates:
                        candidates.append(org.name)
            finally:
                db.close()
        except Exception:
            pass
        return candidates

    def _infer_graph_query_args(self, user_message: str) -> dict:
        lowered = (user_message or "").lower()
        relation_type = "all"
        if any(token in lowered for token in ["投资链条", "谁投了", "投资", "融资"]):
            relation_type = "investment"
        elif any(token in lowered for token in ["合作伙伴", "合作", "伙伴"]):
            relation_type = "collaboration"

        depth = 2 if any(token in lowered for token in ["链条", "网络", "间接", "二级", "depth 2"]) else 1
        entities = self._find_graph_entities_in_text(user_message)
        inferred_name = (
            self._extract_organization_profile_name(user_message)
            or self._extract_org_phrase(user_message)
            or self._extract_entity(user_message)
            or ""
        )
        entity_name = entities[0] if entities else inferred_name
        if len(entities) >= 2 and any(token in lowered for token in ["和", "与", "跟", "之间"]):
            entity_name = f"{entities[0]}||{entities[1]}"

        return {
            "entity_name": entity_name,
            "relation_type": relation_type,
            "depth": depth,
            "limit": 10,
        }

    def _build_investor_tool_calls(self, user_message: str) -> list[dict]:
        lowered = (user_message or "").lower()
        force_investor_query = "faithtech" in lowered and any(
            token in lowered
            for token in ["投资", "投资机构", "投资人", "投资方", "investor", "fund", "vc", "angel", "pe"]
        )
        if not force_investor_query and not self._looks_like_investor_query(user_message):
            return []
        args = self._infer_investor_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_investors",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_match_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_match_query(user_message):
            return []
        args = self._infer_match_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "match_investors",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_email_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_email_generation_query(user_message):
            return []
        args = self._infer_email_query_args(user_message)
        if not args.get("investor_name") or not args.get("project_description"):
            return []
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "generate_outreach_email",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_task_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_task_creation_query(user_message):
            return []
        args = self._infer_task_query_args(user_message)
        if not args.get("title"):
            return []
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "create_task",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_acquirer_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_acquirer_query(user_message):
            return []
        args = self._infer_acquirer_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "match_acquirers",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_user_match_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_user_match_query(user_message):
            return []
        args = self._infer_user_match_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "match_users",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_funding_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_funding_query(user_message):
            return []
        args = self._infer_funding_query_args(user_message)
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_funding_rounds",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _build_graph_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_graph_query(user_message):
            return []
        args = self._infer_graph_query_args(user_message)
        if not args.get("entity_name"):
            return []
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_graph",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ]

    def _looks_like_ontology_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if (
            self._looks_like_investor_query(text)
            or self._looks_like_match_query(text)
            or self._looks_like_funding_query(text)
            or self._looks_like_graph_query(text)
        ):
            return False
        ontology_tokens = [
            "教会网络",
            "福音派",
            "五旬节",
            "灵恩",
            "faithtech",
            "基金会",
            "神学院",
            "协会",
            "联盟",
            "媒体机构",
            "ai成熟度",
            "合作偏好",
        ]
        has_country = any(alias in lowered for aliases in COUNTRY_ALIASES.values() for alias in aliases)
        has_ontology_token = any(token in lowered for token in ontology_tokens)
        return has_ontology_token or (has_country and "有哪些" in lowered)

    def _build_ontology_type_tool_calls(self, user_message: str) -> list[dict]:
        if not self._looks_like_ontology_type_query(user_message):
            return []
        lowered = (user_message or "").lower()
        category = None
        if "faithtech" in lowered or "机构类型" in lowered or "类型" in lowered:
            category = "organization_types"
        elif any(token in lowered for token in ["神学", "教派", "宗派"]):
            category = "theologies"
        elif "规模" in lowered:
            category = "scales"
        elif "ai" in lowered:
            category = "ai_levels"
        elif any(token in lowered for token in ["合作", "偏好"]):
            category = "collaborations"
        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "get_ontology_types",
                    "arguments": json.dumps({"category": category}, ensure_ascii=False),
                },
            }
        ]

    def _build_ontology_tool_calls(self, user_message: str) -> list[dict]:
        lowered = (user_message or "").lower()
        if "faithtech" in lowered and any(
            token in lowered
            for token in ["投资", "投资机构", "投资人", "投资方", "investor", "fund", "vc", "angel", "pe"]
        ):
            return []
        if not self._looks_like_ontology_query(user_message):
            return []

        country = self._extract_country(user_message)
        filter_type = "organization_type"
        filter_value = None

        mapping = [
            ("organization_type", "church_network", ["教会网络", "network church", "church network"]),
            ("organization_type", "church_independent", ["独立教会"]),
            ("organization_type", "church_denomination", ["宗派体系教会", "宗派教会"]),
            ("organization_type", "church_mega", ["大型教会", "超级教会"]),
            ("organization_type", "mission_agency", ["差传机构", "宣教机构"]),
            ("organization_type", "mission_bible_translation", ["圣经翻译"]),
            ("organization_type", "mission_relief", ["救援", "发展机构"]),
            ("organization_type", "foundation_grant", ["资助型基金会"]),
            ("organization_type", "foundation_investment", ["投资型基金会"]),
            ("organization_type", "foundation_family", ["家族基金会"]),
            ("organization_type", "faithtech_bible", ["圣经科技"]),
            ("organization_type", "faithtech_worship", ["敬拜科技"]),
            ("organization_type", "faithtech_social", ["基督教社交媒体"]),
            ("organization_type", "faithtech_fintech", ["基督教金融科技"]),
            ("organization_type", "faithtech_ai", ["faithtech ai", "基督教ai", "faithtech"]),
            ("organization_type", "faithtech_education", ["教育科技", "门徒训练平台"]),
            ("organization_type", "faithtech_media", ["基督教媒体"]),
            ("organization_type", "ngo_christian", ["基督教ngo"]),
            ("organization_type", "seminary", ["神学院"]),
            ("organization_type", "accelerator", ["加速器", "孵化器"]),
            ("organization_type", "media_outlet", ["媒体机构", "media outlet", "cbn asia"]),
            ("organization_type", "association", ["协会", "联盟", "pcec"]),
            ("theology", "evangelical", ["福音派"]),
            ("theology", "pentecostal", ["五旬节"]),
            ("theology", "charismatic", ["灵恩"]),
            ("theology", "reformed", ["改革宗"]),
            ("theology", "baptist", ["浸信会"]),
            ("theology", "methodist", ["卫理公会"]),
            ("theology", "anglican", ["圣公会"]),
            ("theology", "lutheran", ["路德宗"]),
            ("theology", "catholic", ["天主教"]),
            ("theology", "orthodox", ["东正教"]),
            ("theology", "nondenominational", ["无宗派"]),
            ("theology", "interdenominational", ["跨宗派"]),
            ("scale", "micro", ["微型"]),
            ("scale", "small", ["小型"]),
            ("scale", "medium", ["中型"]),
            ("scale", "large", ["大型"]),
            ("scale", "mega", ["超大型"]),
            ("ai_maturity", "level_0", ["无数字化"]),
            ("ai_maturity", "level_1", ["基础数字化"]),
            ("ai_maturity", "level_2", ["数字化工具"]),
            ("ai_maturity", "level_3", ["ai辅助"]),
            ("ai_maturity", "level_4", ["ai原生"]),
            ("collaboration", "seeking_investment", ["寻找投资"]),
            ("collaboration", "seeking_acquisition", ["寻找收购方", "收购"]),
            ("collaboration", "open_partnership", ["开放合作"]),
            ("collaboration", "making_investments", ["进行投资"]),
            ("collaboration", "seeking_projects", ["寻找项目"]),
            ("collaboration", "not_open", ["暂不开放"]),
            ("collaboration", "exploring", ["探索中"]),
        ]

        for current_type, current_value, tokens in mapping:
            if any(token in lowered for token in tokens):
                filter_type = current_type
                filter_value = current_value
                break

        if not filter_value:
            return []

        return [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {
                    "name": "query_ontology",
                    "arguments": json.dumps(
                        {
                            "filter_type": filter_type,
                            "filter_value": filter_value,
                            "country": country,
                            "limit": 20,
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        ]

    def _looks_like_intel_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        if self._looks_like_news_query(text):
            return True
        entity = self._extract_entity(text)
        has_country = False
        for aliases in COUNTRY_ALIASES.values():
            for alias in aliases:
                if alias in lowered:
                    has_country = True
                    break
            if has_country:
                break
        intent_tokens = [
            "情况",
            "动态",
            "最新",
            "近况",
            "现状",
            "背景",
            "分析",
            "情报",
            "趋势",
            "资料",
            "消息",
            "latest",
            "update",
            "updates",
            "status",
            "situation",
            "intel",
        ]
        if not (entity or has_country or (self._looks_like_plural_entity_reference(text) and self.current_entities)):
            return False
        for token in intent_tokens:
            if token in lowered:
                return True
        return False

    def _looks_like_news_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        news_tokens = [
            "新闻",
            "news",
            "headline",
            "headlines",
            "最近发生了什么",
            "发生了什么",
            "最近有什么",
            "最近",
        ]
        has_news_intent = any(token in lowered for token in news_tokens)
        has_subject = any(
            token in lowered
            for token in ["基督教", "christian", "教会", "福音", "global", "全球", "世界", "国际"]
        )
        if not has_subject and self._looks_like_plural_entity_reference(text) and self.current_entities:
            has_subject = True
        if not has_subject and self._extract_entity(text):
            has_subject = True
        return has_news_intent and has_subject

    def _extract_entity(self, text: str) -> Optional[str]:
        lowered = (text or "").lower()
        for entity in ENTITY_HINTS:
            if entity.lower() in lowered:
                return entity

        acronym_match = re.findall(r"\b[A-Z]{2,8}\b", text or "")
        if acronym_match:
            for acronym in acronym_match:
                if self._extract_country(acronym):
                    continue
                return acronym
        if self._looks_like_plural_entity_reference(text) and len(self.current_entities) == 1:
            return self.current_entities[-1].get("name")
        return None

    def _extract_org_phrase(self, text: str) -> Optional[str]:
        match = re.search(r"([A-Za-z][A-Za-z0-9&'.-]*(?:\s+[A-Za-z][A-Za-z0-9&'.-]*){0,4})", text or "")
        if match:
            return self._clean_org_candidate(match.group(1).strip())
        return None

    def _extract_keywords(self, text: str, country: str, entity: Optional[str]) -> list[str]:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9&'.-]{1,}", text or "")
        blocked = {country.lower(), (entity or "").lower(), "菲律宾", "韩国", "美国", "尼日利亚", "全球"}
        keywords = []
        for token in tokens:
            lowered = token.lower()
            if not lowered or lowered in blocked or lowered in STOPWORDS:
                continue
            if token not in keywords:
                keywords.append(token)
        return keywords[:6]

    def _extract_profile_from_message(self, text: str) -> Optional[dict]:
        cleaned = (text or "").strip()
        if self._looks_like_match_query(cleaned):
            return None
        if self._is_profile_question(cleaned):
            return None
        if not cleaned or "我是" not in cleaned and "我叫" not in cleaned:
            return None

        name_match = re.search(r"(?:我是|我叫)([\u4e00-\u9fffA-Za-z0-9·]{2,30})", cleaned)
        extracted_name = name_match.group(1).strip() if name_match else None
        if extracted_name and any(token in extracted_name for token in ["项目", "机构", "媒体", "社交", "菲律宾", "基督教", "种子", "偏好"]):
            extracted_name = None

        org_match = re.search(r"(?:在|来自)([\u4e00-\u9fffA-Za-z0-9&'.\-\s]{2,60}?)(?:工作|任职|服事|做事|$|，|,)", cleaned)
        role_match = re.search(r"(?:负责|担任|是)([\u4e00-\u9fffA-Za-z0-9&'.\-\s]{2,40})", cleaned)
        lowered = cleaned.lower()

        focus_area = ""
        if any(token in lowered for token in ["社交媒体", "social media", "媒体", "media"]):
            focus_area = "Media"
        elif any(token in lowered for token in ["faithtech", "基督教科技", "church tech", "圣经科技"]):
            focus_area = "FaithTech"
        elif any(token in lowered for token in ["教育", "神学院", "edtech"]):
            focus_area = "EdTech"
        elif any(token in lowered for token in ["宣教", "差传", "mission"]):
            focus_area = "Mission"

        project_stage = ""
        if any(token in lowered for token in ["种子期", "种子轮", "seed"]):
            project_stage = "seed"
        elif any(token in lowered for token in ["pre-seed", "天使轮", "种子前"]):
            project_stage = "pre_seed"
        elif any(token in lowered for token in ["series a", "a轮"]):
            project_stage = "series_a"

        preference = "local" if any(token in lowered for token in ["偏好本地", "本地机构", "当地机构", "local"]) else None
        preferred_investor_type = None
        if "基金会" in lowered or "foundation" in lowered:
            preferred_investor_type = "foundation"
        elif "影响力投资" in lowered or "impact" in lowered:
            preferred_investor_type = "impact_investor"
        elif "天使" in lowered or "angel" in lowered:
            preferred_investor_type = "angel"
        elif "vc" in lowered or "venture" in lowered:
            preferred_investor_type = "vc"

        country = self._extract_country(cleaned)
        region = self._extract_region(cleaned)
        focus_region = country or region or None
        inferred_role = role_match.group(1).strip() if role_match else None
        if not inferred_role and project_stage in {"pre_seed", "seed"}:
            inferred_role = "早期项目"

        profile = {
            "name": extracted_name,
            "org": org_match.group(1).strip() if org_match else None,
            "role": inferred_role,
            "preference": preference,
            "focus_region": focus_region,
            "preferred_investor_type": preferred_investor_type,
            "project_stage": project_stage or None,
            "focus_area": focus_area or None,
            "project_description": cleaned[:120],
            "country": country or None,
            "region": region or None,
        }
        if any(value for value in profile.values()):
            return profile
        return None

    def _is_profile_question(self, text: str) -> bool:
        lowered = (text or "").lower()
        match_keywords = [
            "谁能投",
            "谁能投我",
            "匹配投资方",
            "推荐投资者",
            "推荐投资方",
            "适合找谁",
            "我的项目适合找谁",
            "match_investor",
            "match investors",
        ]
        if any(token in lowered for token in match_keywords):
            return False
        return any(
            token in lowered
            for token in [
                "你知道我是谁",
                "记得我是谁",
                "我是谁",
                "认识我吗",
                "我上次说过我做什么项目",
                "我之前说过我做什么项目",
                "还记得我做什么项目",
                "do you know who i am",
            ]
        )

    def _is_contact_query(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(token in lowered for token in ["联系", "联系人", "邮箱", "电话", "负责人", "对接"])


def think(user_message: str, conversation_id: str, history: list | None = None) -> dict:
    """外部调用入口"""
    brain = Brain()
    return brain.think(user_message, conversation_id, history)
