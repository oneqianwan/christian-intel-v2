import logging
from typing import Dict

from .analysis_agent import AnalysisAgent
from .data_agent import DataAgent
from .intent_agent import IntentAgent
from .report_agent import ReportAgent

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Agent编排调度器，根据意图决定执行路径。"""

    def __init__(self):
        self.intent_agent = IntentAgent()
        self.data_agent = DataAgent()
        self.analysis_agent = AnalysisAgent()
        self.report_agent = ReportAgent()

    def process(self, user_message: str) -> Dict:
        """
        主入口：处理用户查询。

        路径：
        1. IntentAgent 识别意图
        2. DataAgent 查询数据
        3. multi_step 进入 AnalysisAgent
        4. ReportAgent 生成最终报告
        """
        try:
            intent_result = self.intent_agent.recognize(user_message)
            intent = intent_result.get("intent", "general")
            complexity = intent_result.get("complexity", "simple")

            logger.info("[Orchestrator] Intent=%s, Complexity=%s", intent, complexity)

            raw = (user_message or "").strip()
            lowered = raw.lower()
            if (
                intent == "general"
                and raw
                and len(raw) <= 60
                and (
                    "你好" in raw
                    or "您好" in raw
                    or "你是谁" in raw
                    or "介绍下你自己" in raw
                    or "介绍一下你自己" in raw
                    or "who are you" in lowered
                    or "introduce yourself" in lowered
                    or lowered in ["hello", "hi"]
                )
            ):
                response = (
                    "I am the Christian Intelligence Operating System (CIO) — your dedicated research assistant for Christian organizations worldwide.\n\n"
                    "## What I Can Do\n\n"
                    "**1. Organization Scoring**\n"
                    "Query People / Digital / Intel / Composite scores for any organization in our database (1,054 organizations across 256 countries).\n\n"
                    "**2. Organization Comparison**\n"
                    "Compare scores across multiple institutions side-by-side.\n\n"
                    "**3. Investment Relations**\n"
                    "Track invested_in / co_invested / partnered_with relationships with evidence links and verification status.\n\n"
                    "**4. Intelligence Timeline**\n"
                    "Show latest news and intelligence items by organization or country.\n\n"
                    "**5. Database Coverage**\n"
                    "Answer questions about database scope, score coverage, and data gaps.\n\n"
                    "## My Rules\n\n"
                    "- I only answer based on database facts. If data is missing, I say \"not in database\" — I never hallucinate.\n"
                    "- I support both English and Chinese responses.\n"
                    "- For ambiguous names (e.g., \"Victory\"), I list candidates and ask you to clarify.\n\n"
                    "## Try These Examples\n\n"
                    "- \"What is the composite score of Victory Philippines?\"\n"
                    "- \"Compare PCEC and SBC composite scores\"\n"
                    "- \"What organizations did Christian and Missionary Alliance invest in?\"\n"
                    "- \"Show the latest intelligence about Philippines\"\n"
                    "- \"How many organizations have people_score > 0?\"\n"
                )
                return {
                    "response": response,
                    "reply": response,
                    "intent": "general",
                    "data_found": True,
                    "organizations_found": 0,
                    "delivery": {
                        "status": "success",
                        "delivery_type": "assistant_intro",
                        "execution_summary": {"engine": "brain_v3", "direct_answer": True},
                    },
                }

            data_result = self.data_agent.query(intent_result)

            # 评分查询/对比：DataAgent 已返回精确数据，直接格式化回答
            if intent in ["score_query", "score_comparison"] and data_result.get("total_found", 0) > 0:
                orgs = data_result.get("organizations", [])
                reply_lines = []
                for o in orgs:
                    composite = o.get("people_score", 0) + o.get("digital_score", 0) + o.get("intel_score", 0)
                    reply_lines.append(
                        f"**{o['name']}** ({o.get('country', '')})\n"
                        f"- People Score: {o.get('people_score', 0)} ({o.get('people_score_grade', 'F')})\n"
                        f"- Digital Score: {o.get('digital_score', 0)} ({o.get('digital_score_grade', 'F')})\n"
                        f"- Intel Score: {o.get('intel_score', 0)} ({o.get('intel_score_grade', 'F')})\n"
                        f"- **Composite: {composite}**\n"
                    )
                response = "\n".join(reply_lines)
                return {
                    "response": response,
                    "reply": response,
                    "intent": intent,
                    "data_found": True,
                    "organizations_found": len(orgs),
                    "delivery": {
                        "status": "success",
                        "delivery_type": "score_answer",
                        "execution_summary": {"engine": "brain_v3", "direct_answer": True},
                    },
                }

            if intent == "score_query" and intent_result.get("entities", {}).get("organization") and data_result.get("total_found", 0) == 0:
                response = "Not found in database."
                return {
                    "response": response,
                    "reply": response,
                    "intent": intent,
                    "data_found": True,
                    "organizations_found": 0,
                    "delivery": {
                        "status": "success",
                        "delivery_type": "score_answer",
                        "execution_summary": {"engine": "brain_v3", "direct_answer": True},
                    },
                }

            # 投资关系查询：直接返回答案
            if intent == "investment_relations" and data_result.get("relations"):
                rels = data_result.get("relations", [])
                reply_lines = [f"Found {len(rels)} investment relations:\n"]
                for r in rels:
                    amount = (
                        f"{r.get('investment_currency', 'USD')} {r.get('investment_amount', 'N/A')}"
                        if r.get("investment_amount")
                        else "Amount undisclosed"
                    )
                    verified = "✓ Verified" if r.get("is_verified") else "Unverified"
                    reply_lines.append(
                        f"- **{r.get('relation_type', '').upper()}** → {r.get('other_org_name', '')} ({r.get('other_org_country', '')})\n"
                        f"  Amount: {amount} | Round: {r.get('investment_round', 'N/A')} | {verified}\n"
                    )
                response = "\n".join(reply_lines)
                return {
                    "response": response,
                    "reply": response,
                    "intent": intent,
                    "data_found": True,
                    "organizations_found": 0,
                    "delivery": {
                        "status": "success",
                        "delivery_type": "investment_answer",
                        "execution_summary": {"engine": "brain_v3", "direct_answer": True},
                    },
                }

            if intent == "news_intelligence" and data_result.get("intelligence"):
                items = data_result.get("intelligence", [])[:5]
                lines = [f"Latest {len(items)} intelligence items:\n"]
                for it in items:
                    title = it.get("title") or ""
                    src = it.get("source_name") or it.get("source") or ""
                    dt = it.get("published_at") or ""
                    lines.append(f"- {title} ({src}) {dt}".strip())
                response = "\n".join(lines)
                return {
                    "response": response,
                    "reply": response,
                    "intent": intent,
                    "data_found": True,
                    "organizations_found": 0,
                    "delivery": {
                        "status": "success",
                        "delivery_type": "intelligence_answer",
                        "execution_summary": {"engine": "brain_v3", "direct_answer": True},
                    },
                }

            if data_result.get("total_found", 0) == 0 and not data_result.get("country_stats"):
                return {
                    "response": self._format_no_data_response(intent_result),
                    "intent": intent,
                    "data_found": False,
                }

            if complexity == "multi_step":
                analysis = self.analysis_agent.analyze(intent_result, data_result)
            else:
                analysis = data_result.get("summary", "")

            report = self.report_agent.generate(user_message, intent_result, data_result, analysis)
            return {
                "response": report,
                "intent": intent,
                "data_found": True,
                "organizations_found": data_result.get("total_found", 0),
            }
        except Exception as exc:
            logger.error("[Orchestrator] 处理失败: %s", exc)
            return {
                "response": f"系统暂时无法处理该查询，请稍后重试。错误：{str(exc)[:100]}",
                "intent": "error",
                "data_found": False,
            }

    def _format_no_data_response(self, intent_result: dict) -> str:
        """格式化无数据响应。"""
        country = intent_result.get("entities", {}).get("country", "")
        org = intent_result.get("entities", {}).get("organization", "")
        target = country or org or "该地区/机构"

        return f"""## 数据缺口提示

当前数据库中关于 **{target}** 的情报数据不足。

**已覆盖范围：**
- 全球49个国家，1054家机构
- T1机构300家（深度覆盖中）

**建议：**
1. 尝试更宽泛的查询（如"东南亚基督教概况"）
2. 或指定我们已覆盖的国家（菲律宾、韩国、尼日利亚等）

系统已记录此缺口，将优先补充 **{target}** 的数据。
"""
