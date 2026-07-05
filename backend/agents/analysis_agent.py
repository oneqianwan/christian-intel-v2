from .base_agent import BaseAgent

ANALYSIS_SYSTEM_PROMPT = """你是Christian Intel的分析推理专家。

你的任务：对DataAgent提供的数据进行深度分析。

分析维度：
1. 趋势识别：数据中的模式和趋势
2. 对比分析：机构间、国家间的对比
3. 机会识别：投资、合作、增长机会
4. 风险评估：政策、竞争、数据缺口风险

输出格式（Markdown）：
## 分析摘要
（3-5句话核心结论）

## 关键发现
- 发现1
- 发现2

## 机会与建议
- 机会1
- 建议1

## 数据缺口
- 哪些数据缺失影响分析质量
"""


class AnalysisAgent(BaseAgent):
    """分析推理Agent。"""

    def __init__(self):
        super().__init__(
            name="AnalysisAgent",
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            max_tokens=1500,
        )

    def analyze(self, intent_result: dict, data_result: dict) -> str:
        """分析数据。"""
        intent = intent_result.get("intent", "general")
        country = intent_result.get("entities", {}).get("country", "未知")

        prompt = f"""基于以下数据进行 {intent} 分析：

意图：{intent}
国家：{country}

数据：
{data_result.get('summary', '无数据')}

机构详情：
"""
        for org in data_result.get("organizations", [])[:5]:
            prompt += (
                f"\n- {org['name']} | {org['country']} | AI:{self._display_score(org['ai_maturity_score'])} | "
                f"Leader:{org['leader_name'] or 'N/A'} | Mission:{(org['mission_statement'] or 'N/A')[:100]}"
            )

        prompt += "\n\n请输出分析结果（Markdown格式）："
        response = self.call(prompt, temperature=0.3)
        if response.startswith("ERROR:") or not response.strip():
            return self._fallback_analysis(intent_result, data_result)
        return response

    def _fallback_analysis(self, intent_result: dict, data_result: dict) -> str:
        """LLM 不可用时的确定性分析降级。"""
        organizations = data_result.get("organizations", [])
        stats = data_result.get("country_stats") or {}
        top_org = organizations[0]["name"] if organizations else "暂无代表性机构"

        findings = [
            f"- 当前命中的核心样本数为 {len(organizations)} 家，头部样本以 {top_org} 为代表。",
        ]
        if stats:
            findings.append(
                f"- 国家维度共 {stats.get('total_organizations', 0)} 家机构，"
                f"其中 {stats.get('with_people', 0)} 家已有人物覆盖，{stats.get('with_ai_assessment', 0)} 家完成 AI 评估。"
            )
        if organizations and any(org.get("ai_maturity_score") for org in organizations):
            findings.append("- 至少部分机构已经具备 AI 成熟度评分，可支持数字化与 AI 采用度比较。")
        else:
            findings.append("- 当前样本的 AI 评分覆盖仍有限，结论更适合作为方向性判断。")

        return "\n".join(
            [
                "## 分析摘要",
                "当前问题可以形成初步行业判断，但深度仍受样本覆盖度限制。",
                "",
                "## 关键发现",
                *findings,
                "",
                "## 机会与建议",
                "- 优先关注 T1 机构中已完成人物与 AI 评分的样本，这些目标最适合继续深挖。",
                "- 若要形成投资或合作级结论，建议补齐 Mission、People 和 Contact 三个字段。",
                "",
                "## 数据缺口",
                "- Contact、Mission、People 覆盖仍不足，可能影响最终排序与推荐质量。",
            ]
        )

    def _display_score(self, value) -> str:
        return str(value) if value is not None else "N/A"
