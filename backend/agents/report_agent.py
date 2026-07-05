from .base_agent import BaseAgent

REPORT_SYSTEM_PROMPT = """你是Christian Intel的报告生成专家。

你的任务：把分析结果格式化为专业、可读的情报报告。

报告风格：
- 结论先行：第一句话给出核心答案
- 数据支撑：每个结论都有数据支撑
- 结构化：使用标题、列表、表格
- 可读性：避免长段落，多用bullet points
- 专业术语：使用行业术语（AI成熟度、宗派生态、数字化程度等）

输出格式：Markdown

报告模板：
# [标题]

## 核心结论
（1-2句话直接回答用户问题）

## 详细分析
（AnalysisAgent的分析结果，精炼整理）

## 关键数据
（表格形式的数据摘要）

## 建议与下一步
（可操作的建议）

## 数据可信度
（高/中/低 + 理由）
"""


class ReportAgent(BaseAgent):
    """报告生成Agent。"""

    def __init__(self):
        super().__init__(
            name="ReportAgent",
            system_prompt=REPORT_SYSTEM_PROMPT,
            max_tokens=2000,
        )

    def generate(self, user_message: str, intent_result: dict, data_result: dict, analysis: str) -> str:
        """生成最终报告。"""
        prompt = f"""基于以下信息生成情报报告：

用户原始问题："{user_message}"

意图：{intent_result.get('intent')}
国家/机构：{intent_result.get('entities', {})}

分析结果：
{analysis}

关键数据：
"""
        for org in data_result.get("organizations", [])[:5]:
            prompt += (
                f"- {org['name']} ({org['country']}) | AI:{self._display_score(org['ai_maturity_score'])} | "
                f"People:{org['leader_name'] or 'N/A'}\n"
            )

        prompt += "\n请生成专业情报报告："
        response = self.call(prompt, temperature=0.4)
        if response.startswith("ERROR:") or not response.strip():
            return self._fallback_report(user_message, intent_result, data_result, analysis)
        return response

    def _fallback_report(self, user_message: str, intent_result: dict, data_result: dict, analysis: str) -> str:
        """LLM 不可用时的确定性报告降级。"""
        organizations = data_result.get("organizations", [])
        rows = ["| 机构 | 国家 | AI成熟度 | 负责人 |", "|---|---|---:|---|"]
        for org in organizations[:5]:
            rows.append(
                f"| {org['name']} | {org['country'] or '-'} | {self._display_score(org['ai_maturity_score'])} | {org['leader_name'] or '-'} |"
            )

        confidence = "中"
        if data_result.get("country_stats") and len(organizations) >= 5:
            confidence = "中高"
        elif len(organizations) <= 2:
            confidence = "低"

        return "\n".join(
            [
                f"# 多Agent情报报告：{intent_result.get('intent', 'general')}",
                "",
                "## 核心结论",
                f"针对“{user_message}”，系统已完成意图识别、数据库检索与报告生成，当前结果以数据库现有覆盖为基础形成初步判断。",
                "",
                "## 详细分析",
                analysis,
                "",
                "## 关键数据",
                *rows,
                "",
                "## 建议与下一步",
                "- 若用于投资或合作决策，建议继续补齐 Contact、Mission、People 三个核心字段。",
                "- 可基于当前样本继续发起深采或定向筛选，形成更高置信度的 shortlist。",
                "",
                "## 数据可信度",
                f"- {confidence}：结论基于当前数据库命中结果，覆盖质量受样本完整度影响。",
            ]
        )

    def _display_score(self, value) -> str:
        return str(value) if value is not None else "N/A"
