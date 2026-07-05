from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from services.insight_models import InsightResult


class InsightAnswerRenderer:
    SUPPORTED_QUERY_MODES = {
        "score_query",
        "organization",
        "media_list",
        "comparison",
        "missing_entity",
        "source_query",
    }

    def render(
        self,
        question: str,
        insight_result: InsightResult | Dict[str, Any],
        answer_context: Dict[str, Any] | None,
        language: str,
    ) -> str:
        insight = insight_result if isinstance(insight_result, InsightResult) else InsightResult.from_dict(insight_result or {})
        answer_ctx = dict(answer_context or {})
        mode = str(insight.query_mode or "").strip().lower()
        lang = self._normalize_language(language or self._detect_language(question))

        if mode not in self.SUPPORTED_QUERY_MODES:
            return ""
        if mode == "score_query":
            return self._render_score_query(insight, answer_ctx, lang)
        if mode == "organization":
            return self._render_organization(insight, answer_ctx, lang)
        if mode == "media_list":
            return self._render_media_list(insight, answer_ctx, lang)
        if mode == "comparison":
            return self._render_comparison(insight, answer_ctx, lang)
        if mode == "missing_entity":
            return self._render_missing_entity(insight, lang)
        if mode == "source_query":
            return self._render_source_query(insight, answer_ctx, lang)
        return ""

    def _render_score_query(self, insight: InsightResult, answer_context: Dict[str, Any], lang: str) -> str:
        score_map = self._score_map(insight)
        if not score_map:
            return self._render_missing_entity(insight, lang)
        ranked_scores = [(label, payload["value"]) for label, payload in score_map.items() if label != "Composite Score"]
        ranked_scores.sort(key=lambda item: item[1], reverse=True)
        highest = ranked_scores[0] if ranked_scores else ("", "")
        lowest = ranked_scores[-1] if ranked_scores else ("", "")
        sources = self._collect_target_urls(insight, answer_context, prefer_target=True)
        target = self._primary_target(insight)

        lines = [f"## {target} 评分解释", ""]
        lines.append("### 当前分数")
        for label in ("People Score", "Digital Score", "Intel Score", "Composite Score"):
            if label in score_map:
                lines.append(f"- `{label}`：{score_map[label]['display_value']}")
        lines.append("")
        lines.append("### 结构判断")
        if highest[0] and lowest[0]:
            lines.append(f"- 当前最高项：`{highest[0]}`（{self._display_number(highest[1])}）")
            lines.append(f"- 当前最低项：`{lowest[0]}`（{self._display_number(lowest[1])}）")
        lines.append("- 这些解释只基于当前可见证据，不代表系统掌握隐藏评分公式。")
        lines.append("")
        lines.append("### 分项解释")
        for label in ("People Score", "Digital Score", "Intel Score", "Composite Score"):
            payload = score_map.get(label)
            if not payload:
                continue
            lines.append(f"- `{label}`：当前为 `{payload['display_value']}`。{payload['meaning']}")
            lines.append(f"  可见支撑：{payload['visible_support']}")
            lines.append(f"  缺失支撑：{payload['missing_support']}")
        lines.append("")
        lines.append("### 数据限制")
        lines.append("- 当前解释依赖已匹配到的公开证据与结构化字段；若存在未公开或未采集的数据，结论会偏保守。")
        if sources:
            lines.append("")
            lines.append("### Sources")
            lines.extend(f"- {url}" for url in sources)
        return "\n".join(lines).strip()

    def _render_organization(self, insight: InsightResult, answer_context: Dict[str, Any], lang: str) -> str:
        target = self._primary_target(insight)
        sources = self._collect_target_urls(insight, answer_context, prefer_target=True)
        lines = [f"## {target} 情报摘要", ""]
        lines.append("### Executive Summary")
        lines.append(f"- {self._summary_text(insight.executive_summary)}")
        lines.append("")
        lines.append("### Key Findings")
        key_findings = self._summaries(insight.key_findings)
        if key_findings:
            lines.extend(f"- {item}" for item in key_findings)
        else:
            lines.append("- 当前没有形成可稳定输出的关键发现。")
        lines.append("")
        lines.append("### Risks")
        risks = self._summaries(insight.risks)
        if risks:
            lines.extend(f"- {item}" for item in risks)
        else:
            lines.append("- 当前证据中未识别到明确风险信号，不代表不存在风险。")
        lines.append("")
        lines.append("### Opportunities")
        opportunities = self._summaries(insight.opportunities)
        if opportunities:
            lines.extend(f"- {item}" for item in opportunities)
        else:
            lines.append("- 当前证据中未形成足够强的机会信号。")
        lines.append("")
        lines.append("### Data Gaps")
        gaps = self._summaries(insight.data_gaps)
        if gaps:
            lines.extend(f"- {item}" for item in gaps)
        else:
            lines.append("- 当前未显式暴露新的数据缺口，但这不代表数据已完全充分。")
        if sources:
            lines.append("")
            lines.append("### Sources")
            lines.extend(f"- {url}" for url in sources)
        return "\n".join(lines).strip()

    def _render_media_list(self, insight: InsightResult, answer_context: Dict[str, Any], lang: str) -> str:
        grouped = self._group_urls_by_entity(insight, answer_context)
        lines = ["## 菲律宾基督教媒体", ""]
        summary = self._summary_text(insight.executive_summary)
        if summary:
            lines.append(summary)
            lines.append("")
        if not grouped:
            lines.append("- 当前只命中到局部来源，无法输出稳定的媒体列表。")
        else:
            for entity, urls in grouped:
                lines.append(f"- **{entity}**")
                for url in urls:
                    lines.append(f"  来源：{url}")
        gaps = self._summaries(insight.data_gaps)
        if gaps:
            lines.append("")
            lines.append("### Data Gaps")
            lines.extend(f"- {item}" for item in gaps)
        return "\n".join(lines).strip()

    def _render_comparison(self, insight: InsightResult, answer_context: Dict[str, Any], lang: str) -> str:
        target_entities = list(insight.target_entities or [])
        metadata = dict(insight.metadata or {})
        matched_entities = list(metadata.get("matched_target_entities") or [])
        unmatched_entities = [entity for entity in target_entities if entity not in matched_entities]
        grouped = [(entity, self._urls_for_entity(insight, answer_context, entity)) for entity in matched_entities]
        grouped = [(entity, urls) for entity, urls in grouped if urls]

        lines = [f"## {self._comparison_title(target_entities)}", ""]
        lines.append("### 已匹配实体")
        if matched_entities:
            lines.extend(f"- {entity}" for entity in matched_entities)
        else:
            lines.append("- 当前没有匹配到可用于比较的实体。")
        lines.append("")
        lines.append("### 未匹配实体")
        if unmatched_entities:
            lines.extend(f"- {entity}" for entity in unmatched_entities)
        else:
            lines.append("- 无")
        lines.append("")
        lines.append("### Coverage Imbalance")
        if unmatched_entities:
            lines.append(f"- 当前存在 coverage imbalance：{', '.join(unmatched_entities)} 缺少足够证据，因此无法形成对等比较。")
        else:
            lines.append("- 当前两侧都已有基础证据，但比较结论仍受较弱一侧覆盖度限制。")
        lines.append("")
        lines.append("### 当前能够比较的内容")
        if grouped:
            for entity, urls in grouped:
                lines.append(f"- {entity}：当前至少有 {len(urls)} 条可验证来源可用于基础画像或来源比对。")
        elif matched_entities:
            for entity in matched_entities:
                lines.append(f"- {entity}：已命中实体级证据，但当前可直接展示的来源 URL 仍然有限。")
        else:
            lines.append("- 当前没有足够的匹配来源可供比较。")
        lines.append("")
        lines.append("### 当前不能比较的内容")
        if unmatched_entities:
            lines.append(f"- 由于 {', '.join(unmatched_entities)} 未命中或数据不足，不能输出对等的实力、评分或风险比较。")
        else:
            lines.append("- 当前仍不能把有限公开来源直接等同于完整尽调。")
        all_urls = self._flatten_grouped_urls(grouped)
        if all_urls:
            lines.append("")
            lines.append("### Sources")
            lines.extend(f"- {url}" for url in all_urls)
        return "\n".join(lines).strip()

    def _render_missing_entity(self, insight: InsightResult, lang: str) -> str:
        target = self._primary_target(insight)
        lines = [f"## {target} 数据缺口说明", ""]
        lines.append("- 未找到可稳定匹配到该目标实体的证据。")
        lines.append("- 为避免错绑到其他机构或随机新闻，当前不生成实体结论。")
        lines.append("")
        lines.append("### 当前数据缺口")
        gaps = self._summaries(insight.data_gaps)
        if gaps:
            lines.extend(f"- {item}" for item in gaps)
        else:
            lines.append("- 当前缺少可验证的目标实体来源。")
        lines.append("")
        lines.append("### 建议补采或下一问")
        next_questions = self._summaries(insight.recommended_next_questions)
        if next_questions:
            lines.extend(f"- {item}" for item in next_questions)
        else:
            lines.append("- 建议先补充该机构的官网、注册信息或可信第三方来源。")
        return "\n".join(lines).strip()

    def _render_source_query(self, insight: InsightResult, answer_context: Dict[str, Any], lang: str) -> str:
        target = self._primary_target(insight)
        urls = self._collect_target_urls(insight, answer_context, prefer_target=True)
        lines = [f"## {target} 的来源", ""]
        if urls:
            lines.extend(f"- {url}" for url in urls)
        else:
            lines.append("- 当前未找到与该目标实体稳定匹配的来源 URL。")
        return "\n".join(lines).strip()

    def _score_map(self, insight: InsightResult) -> Dict[str, Dict[str, Any]]:
        score_map: Dict[str, Dict[str, Any]] = {}
        for item in list(insight.score_explanations or []):
            title = str(item.title or "").strip()
            if not title:
                continue
            current_score = self._extract_score_value(item.summary)
            visible_support, missing_support = self._extract_support_parts(item.summary)
            meaning = self._extract_meaning(item.summary, visible_support)
            score_map[title] = {
                "value": current_score,
                "display_value": self._display_number(current_score) if current_score is not None else "N/A",
                "visible_support": visible_support or "当前没有抽取到稳定的可见支撑说明。",
                "missing_support": missing_support or "当前没有抽取到明确的缺失支撑说明。",
                "meaning": meaning or "该分数反映当前系统可见到的公开信号，不代表隐藏公式。",
            }
        return score_map

    def _extract_score_value(self, summary: str) -> float | None:
        match = re.search(r"(?:is currently|is)\s+([0-9]+(?:\.[0-9]+)?)", str(summary or ""), re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _extract_support_parts(self, summary: str) -> Tuple[str, str]:
        text = str(summary or "")
        visible_match = re.search(r"Visible support:\s*(.+?)\.\s*Missing support:", text, re.IGNORECASE)
        missing_match = re.search(r"Missing support:\s*(.+?)\.\s*This explanation", text, re.IGNORECASE)
        return (
            str(visible_match.group(1) if visible_match else "").strip(),
            str(missing_match.group(1) if missing_match else "").strip(),
        )

    def _extract_meaning(self, summary: str, visible_support: str) -> str:
        text = str(summary or "")
        if not text:
            return ""
        if "Visible support:" in text:
            text = text.split("Visible support:", 1)[0].strip()
        parts = [part.strip() for part in text.split(".") if part.strip()]
        if len(parts) >= 2:
            return f"{parts[1]}。"
        if parts:
            return f"{parts[0]}。"
        return ""

    def _collect_target_urls(self, insight: InsightResult, answer_context: Dict[str, Any], *, prefer_target: bool) -> List[str]:
        target_entities = list(insight.target_entities or [])
        evidence_items = [item for item in list(answer_context.get("evidence") or []) if isinstance(item, dict)]
        matched_urls: List[str] = []
        fallback_urls: List[str] = []
        for evidence in evidence_items:
            url = str(evidence.get("url") or "").strip()
            if not self._is_valid_url(url):
                continue
            fallback_urls.append(url)
            if not prefer_target or self._matches_target_evidence(evidence, target_entities):
                matched_urls.append(url)
        for url in list(insight.source_urls or []):
            if self._is_valid_url(url):
                fallback_urls.append(url)
        return self._dedupe(matched_urls or fallback_urls)

    def _group_urls_by_entity(
        self,
        insight: InsightResult,
        answer_context: Dict[str, Any],
        *,
        restrict_to: List[str] | None = None,
    ) -> List[Tuple[str, List[str]]]:
        grouped: Dict[str, List[str]] = {}
        evidence_items = [item for item in list(answer_context.get("evidence") or []) if isinstance(item, dict)]
        allowed = set(restrict_to or [])
        for evidence in evidence_items:
            url = str(evidence.get("url") or "").strip()
            if not self._is_valid_url(url):
                continue
            entity = self._best_entity_name_from_evidence(evidence)
            if not entity:
                continue
            if allowed and entity not in allowed:
                continue
            grouped.setdefault(entity, []).append(url)
        if not grouped:
            for item in list(insight.key_findings or []):
                title = str(item.title or "").strip()
                if title.startswith("Media Entity: "):
                    entity = title.split("Media Entity: ", 1)[1].strip()
                    urls = [url for url in list(item.source_urls or []) if self._is_valid_url(url)]
                    if urls:
                        grouped.setdefault(entity, []).extend(urls)
        results = [(entity, self._dedupe(urls)) for entity, urls in grouped.items()]
        results.sort(key=lambda item: (len(item[1]), item[0]), reverse=True)
        return results

    def _best_entity_name_from_evidence(self, evidence: Dict[str, Any]) -> str:
        source_name = str(evidence.get("source_name") or "").strip()
        title = str(evidence.get("title") or "").strip()
        if "/" in source_name:
            tail = source_name.split("/")[-1].strip()
            if tail:
                return tail
        if source_name and not self._is_valid_url(source_name):
            return source_name
        if title:
            for part in re.split(r"[-:|]", title):
                candidate = part.strip()
                if len(candidate) >= 4:
                    return candidate
        return ""

    def _matches_target_evidence(self, evidence: Dict[str, Any], target_entities: List[str]) -> bool:
        if not target_entities:
            return True
        haystack = " ".join(
            [
                str(evidence.get("title") or ""),
                str(evidence.get("snippet") or ""),
                str(evidence.get("source_name") or ""),
                str(evidence.get("url") or ""),
            ]
        ).lower()
        for entity in target_entities:
            tokens = [token for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", entity.lower()) if token]
            tokens = [token for token in tokens if token not in {"the", "and", "of", "score", "digital", "people", "intel", "composite"}]
            if tokens and all(token in haystack for token in tokens):
                return True
        return False

    def _flatten_grouped_urls(self, grouped: List[Tuple[str, List[str]]]) -> List[str]:
        urls: List[str] = []
        for _, items in grouped:
            urls.extend(items)
        return self._dedupe(urls)

    def _urls_for_entity(self, insight: InsightResult, answer_context: Dict[str, Any], entity: str) -> List[str]:
        if not entity:
            return []
        evidence_items = [item for item in list(answer_context.get("evidence") or []) if isinstance(item, dict)]
        matched_urls = [
            str(evidence.get("url") or "").strip()
            for evidence in evidence_items
            if self._matches_target_evidence(evidence, [entity]) and self._is_valid_url(evidence.get("url"))
        ]
        fallback_urls = [url for url in list(insight.source_urls or []) if self._is_valid_url(url)]
        return self._dedupe(matched_urls or fallback_urls)

    def _primary_target(self, insight: InsightResult) -> str:
        if insight.target_entities:
            return insight.target_entities[0]
        return str(insight.target_scope or "目标实体")

    def _comparison_title(self, target_entities: List[str]) -> str:
        if len(target_entities) >= 2:
            return f"{target_entities[0]} vs {target_entities[1]} 对比"
        if target_entities:
            return f"{target_entities[0]} 对比"
        return "机构对比"

    def _summary_text(self, section: Any) -> str:
        return str(getattr(section, "summary", "") or "").strip() or "当前没有稳定摘要。"

    def _summaries(self, items: List[Any]) -> List[str]:
        values: List[str] = []
        for item in list(items or []):
            summary = str(getattr(item, "summary", "") or "").strip()
            if summary:
                values.append(summary)
        return values

    def _display_number(self, value: float | None) -> str:
        if value is None:
            return "N/A"
        if float(value).is_integer():
            return str(int(value))
        return str(round(float(value), 2))

    def _detect_language(self, question: str) -> str:
        return "zh" if re.search(r"[\u4e00-\u9fff]", str(question or "")) else "en"

    def _normalize_language(self, language: str) -> str:
        lang = str(language or "").strip().lower()
        return "zh" if lang.startswith("zh") or lang == "cn" else "en"

    def _is_valid_url(self, value: Any) -> bool:
        text = str(value or "").strip()
        return text.startswith("http://") or text.startswith("https://")

    def _dedupe(self, values: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for value in list(values or []):
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered
