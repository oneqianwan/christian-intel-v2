import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

# ===== 第一层：系统级约束（每次调用必带） =====
SYSTEM_CONSTRAINT = """你是「守望者」（The Watcher），基督教行业高级情报官。你的职责是为教会机构负责人、BD人员和决策者提供可执行的战略情报。

【身份铁律】
- 你是情报官，不是牧师。你不讲道、不劝信、不做属灵辅导。
- 你是分析师，不是搜索引擎。你不罗列 raw data，你提供洞察和判断。
- 你是服务者，不是权威。不确定就说"信息不足"，绝不编造。

【语言风格】
- 冷静、精准、简洁。每句话都要有信息量。
- 使用情报术语：CONFIDENCE LEVEL（置信度）、SOURCE（来源）、ACTION REQUIRED（建议行动）、STALE DATA（数据过时）。
- 不说废话：没有"您好"、"希望对您有帮助"、"祝您平安"等寒暄。
- 用结论先行：先给判断，再给依据。

【输出格式 — 情报简报体】
所有输出遵循以下结构：
1. 核心结论（1-2句，最精简）
2. 详细情报（分点，每点含事实+来源+置信度）
3. 数据时效（最后更新时间）
4. 建议行动（如果有的话）

【置信度标注规范】
- [HIGH]：3个以上独立来源交叉验证，或官方一手数据
- [MEDIUM]：1-2个来源，或推断合理但未经证实
- [LOW]：单一来源且未验证，或数据过时效
- [INSUFFICIENT DATA]：信息不足以支撑结论

【来源标注规范】
- 每条事实必须标注 [SOURCE: XXX]
- 一手来源优先：官网 > 权威数据库 > 媒体报道 > 社交媒体
- 来源链接如果公开，必须给出 URL

【不确定时的标准回应】
不要猜测。如果信息不足，直接说：
"关于[主题]，当前可获取的信息不足以支撑可靠结论。建议：
1. 明确您关注的具体维度（如：财务状况/人事变动/合作项目）
2. 指定时间范围
3. 我可以据此启动定向采集"

【基督教领域特殊规则】
- 涉及逼迫/敏感话题时，保持客观中立，不煽情。
- 涉及不同宗派时，不站队、不评价神学立场。
- 涉及金额/人数时，标注"官方声称"或"第三方估算"。
- 中国相关话题极度敏感，如无十足把握，标记为[INSUFFICIENT DATA]。

【多语言处理】
- 用户用中文，你用中文回复。
- 涉及外国机构名、人名时，首次出现标注原文（如：Philippine Council of Evangelical Churches，简称 PCEC）。
- 英文缩写首次出现必须展开。
"""

SYSTEM_PROMPT = SYSTEM_CONSTRAINT

# ===== 第二层：任务级约束 =====
TASK_PROMPTS = {
    "knowledge_summary": """【任务类型：知识库摘要】
请基于知识库数据生成机构/主题摘要。
重点突出：机构概况、关键统计数据、历史背景、组织架构。
避免：猜测机构未来计划、评价机构好坏。""",
    "collection_report": """【任务类型：采集动态报告】
请基于采集结果生成最新动态简报。
重点突出：时间线、事件影响范围、涉及机构/人物、传播数据。
避免：过度解读单一事件的重要性。""",
    "compare_analysis": """【任务类型：实体对比分析】
请对比多个实体的近期动态。
重点突出：各自活动重点、差异点、潜在关联、影响力对比。
格式要求：每个实体独立成段，最后给综合结论。""",
    "url_analysis": """【任务类型：链接内容分析】
请分析该链接内容的相关性和价值。
重点突出：内容主题、与基督教行业的关联度、涉及机构、影响力数据。
必须给出：是否建议入库（是/否）及理由。""",
}

# ===== 第三层：输出格式约束 =====
OUTPUT_FORMAT_PROMPT = """【输出格式约束】
- 输出必须为 Markdown。
- 建议包含：概览、核心结论、风险或局限、结论。
- 每条核心结论都必须带有【事实】或【推断-置信度】标签。
- 每条核心结论后都必须追加至少一个来源追溯，格式为：[来源：来源名称](URL)
- 如果数据不足，单独列出"数据不足说明"，并明确写出"基于当前数据无法得出结论"。
- 不要输出 JSON，不要输出与数据无关的泛化建议。"""

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


class LLMClient:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.base_url = DEEPSEEK_BASE_URL.rstrip("/")
        self.model = DEEPSEEK_MODEL
        self.enabled = bool(self.api_key)

    def _stringify_value(self, value: Any) -> str:
        if value is None or value == "":
            return "未知"
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        return text[:500]

    def _build_messages(
        self,
        query: str,
        items: List[Dict[str, Any]],
        task_type: str = "knowledge_summary",
    ) -> List[Dict[str, str]]:
        """构建带系统级、任务级和格式级约束的 prompt。"""
        task_constraint = TASK_PROMPTS.get(task_type, TASK_PROMPTS["knowledge_summary"])

        context_parts: List[str] = []
        for index, item in enumerate(items[:12], 1):
            data_value = item.get("data", "")
            context_parts.append(
                "\n".join(
                    [
                        f"【数据{index}】",
                        f"名称：{self._stringify_value(item.get('name'))}",
                        f"类型：{self._stringify_value(item.get('type'))}",
                        f"国家：{self._stringify_value(item.get('country'))}",
                        f"类别：{self._stringify_value(item.get('category'))}",
                        f"描述：{self._stringify_value(data_value)}",
                        f"来源名称：{self._stringify_value(item.get('source_name'))}",
                        f"来源URL：{self._stringify_value(item.get('source_url'))}",
                    ]
                )
            )
        context = "\n\n".join(context_parts) if context_parts else "无可用数据"

        user_message = f"""{task_constraint}

{OUTPUT_FORMAT_PROMPT}

当前时间：{datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC

用户问题：「{query}」

数据：
{context}

请严格按全部约束要求生成情报简报。"""

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

    async def analyze(
        self,
        query: str,
        items: List[Dict[str, Any]],
        task_type: str = "knowledge_summary",
    ) -> Optional[str]:
        """带约束的 LLM 分析。"""
        if not self.enabled or not items:
            return None

        messages = self._build_messages(query, items, task_type)

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 2000,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except (asyncio.TimeoutError, httpx.TimeoutException):
            print(f"[LLM] 调用超时: {query[:30]}")
            return None
        except Exception as e:
            print(f"[LLM] 调用异常: {str(e)[:100]}")
            return None

    # 兼容旧接口
    async def summarize_intelligence(self, query: str, items: List[Dict[str, Any]]) -> Optional[str]:
        return await self.analyze(query, items, task_type="knowledge_summary")

    async def summarize(self, query: str, context: List[Dict[str, Any]]) -> Optional[str]:
        return await self.summarize_intelligence(query, context)

    async def analyze_collection(self, query: str, items: List[Dict[str, Any]]) -> Optional[str]:
        return await self.analyze(query, items, task_type="collection_report")

    async def analyze_comparison(self, query: str, items: List[Dict[str, Any]]) -> Optional[str]:
        return await self.analyze(query, items, task_type="compare_analysis")

    async def analyze_url(self, query: str, items: List[Dict[str, Any]]) -> Optional[str]:
        return await self.analyze(query, items, task_type="url_analysis")

    def health_check(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "base_url": self.base_url,
            "status": "ready" if self.enabled else "no_api_key",
            "constraints_version": "v2.0",
            "task_types": list(TASK_PROMPTS.keys()),
        }


llm = LLMClient()


def call_llm(
    prompt: Optional[str] = None,
    max_tokens: int = 1500,
    temperature: float = 0.1,
    messages: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None,
) -> str:
    """同步兼容入口，支持 prompt 或 messages 两种调用方式。"""
    if not llm.enabled:
        raise RuntimeError("LLM API key 未配置")

    if not prompt and not messages:
        raise ValueError("prompt 和 messages 不能同时为空")

    async def _call() -> str:
        request_messages = messages or [
            {"role": "system", "content": "你是信息提取器，只输出用户要求的结果。"},
            {"role": "user", "content": prompt or ""},
        ]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{llm.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {llm.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model or llm.model,
                    "messages": request_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return ((data.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()

    try:
        return asyncio.run(_call())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_call())
        finally:
            loop.close()


def get_llm_client() -> LLMClient:
    return llm
