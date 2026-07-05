from __future__ import annotations

from typing import Any, Dict, List, Tuple

from services.reflection_models import ReflectionIssue, ReflectionResult
from services.runtime_metrics import get_runtime_metrics
from services.trace_center import trace_span


class SelfReflectionEngine:
    def __init__(self, trace_center: Any = None, runtime_metrics: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = runtime_metrics or get_runtime_metrics()

    def reflect(
        self,
        evidence_bundle: Any,
        answer_context: Any,
        reasoning_context: Any,
        verification_result: Dict[str, Any],
    ) -> ReflectionResult:
        with trace_span("Reflection", input_obj=verification_result) as span:
            self._trace("Reflection Started", metadata={})
            coverage_score, coverage_issues = self.check_coverage(verification_result)
            evidence_score, evidence_issues = self.check_evidence(evidence_bundle, answer_context, verification_result)
            reasoning_score, reasoning_issues = self.check_reasoning(reasoning_context, answer_context)
            consistency_score, consistency_issues = self.check_consistency(evidence_bundle, reasoning_context, verification_result)
            issues = [*coverage_issues, *evidence_issues, *reasoning_issues, *consistency_issues]
            overall_score = round((coverage_score + evidence_score + reasoning_score + consistency_score) / 4.0, 2)
            suggestions = self.build_suggestions(issues)
            result = ReflectionResult(
                coverage_score=coverage_score,
                evidence_score=evidence_score,
                reasoning_score=reasoning_score,
                consistency_score=consistency_score,
                overall_score=overall_score,
                issues=issues,
                suggestions=suggestions,
                metadata={
                    "issue_count": len(issues),
                    "missing_fields": list(verification_result.get("missing_fields") or []),
                    "blocking_conflict": bool(verification_result.get("blocking_conflict")),
                },
            )
            self._record_metrics(result)
            self._trace(
                "Reflection Finished",
                metadata={"overall_score": overall_score, "issue_count": len(issues)},
            )
            span.set_output_obj(result)
            return result

    def check_coverage(self, verification_result: Dict[str, Any]) -> Tuple[float, List[ReflectionIssue]]:
        missing_fields = [str(item) for item in (verification_result.get("missing_fields") or []) if str(item or "").strip()]
        issues: List[ReflectionIssue] = []
        for field in missing_fields:
            issues.append(
                ReflectionIssue(
                    issue_type="coverage_insufficient",
                    severity="medium",
                    description=f"missing field: {field}",
                )
            )
        score = max(0.0, round(100.0 - len(missing_fields) * 15.0, 2))
        self._trace("Coverage Checked", metadata={"missing_field_count": len(missing_fields), "score": score})
        return score, issues

    def check_evidence(self, evidence_bundle: Any, answer_context: Any, verification_result: Dict[str, Any]) -> Tuple[float, List[ReflectionIssue]]:
        bundle = self._to_dict(evidence_bundle)
        context = self._to_dict(answer_context)
        evidence_verification = dict(verification_result.get("evidence_verification") or {})
        unsupported = [str(item) for item in (evidence_verification.get("unsupported_facts") or []) if str(item or "").strip()]
        citation_missing = [str(item) for item in ((evidence_verification.get("metadata") or {}).get("citation_missing") or []) if str(item or "").strip()]
        issues: List[ReflectionIssue] = []
        for item in unsupported:
            issues.append(
                ReflectionIssue(
                    issue_type="unsupported_fact",
                    severity="high",
                    description=item,
                    related_fact_ids=self._matching_fact_ids(item, context),
                )
            )
        for item in citation_missing:
            related_evidence = item.split(":", 1)[0] if ":" in item else ""
            issues.append(
                ReflectionIssue(
                    issue_type="citation_missing",
                    severity="medium",
                    description=item,
                    related_evidence_ids=[related_evidence] if related_evidence else [],
                )
            )
        # Extra guard: any answer fact without evidence_ids is treated as unsupported.
        for fact in (context.get("facts") or []):
            if not isinstance(fact, dict):
                continue
            if list(fact.get("evidence_ids") or []):
                continue
            issues.append(
                ReflectionIssue(
                    issue_type="unsupported_fact",
                    severity="high",
                    description=f"fact without evidence: {fact.get('id') or fact.get('fact_id') or ''}",
                    related_fact_ids=[str(fact.get("id") or fact.get("fact_id") or "")],
                )
            )
        penalty = len(unsupported) * 20.0 + len(citation_missing) * 10.0
        if not list(bundle.get("evidences") or []):
            penalty += 30.0
        score = max(0.0, round(100.0 - penalty, 2))
        self._trace("Evidence Checked", metadata={"unsupported_fact_count": len(unsupported), "citation_missing_count": len(citation_missing), "score": score})
        return score, issues

    def check_reasoning(self, reasoning_context: Any, answer_context: Any) -> Tuple[float, List[ReflectionIssue]]:
        context = self._to_dict(reasoning_context)
        answer = self._to_dict(answer_context)
        graph = dict(context.get("reasoning_graph") or {})
        nodes = [item for item in (graph.get("nodes") or []) if isinstance(item, dict)]
        edges = [item for item in (graph.get("edges") or []) if isinstance(item, dict)]
        fact_nodes = [item for item in nodes if str(item.get("node_type") or "").strip().lower() == "fact"]
        conclusion_nodes = [item for item in nodes if str(item.get("node_type") or "").strip().lower() == "conclusion"]
        edge_touches = set()
        dependency_count = 0
        for edge in edges:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            relation = str(edge.get("relation") or "").strip().lower()
            edge_touches.add(source)
            edge_touches.add(target)
            if relation == "depends_on":
                dependency_count += 1
        issues: List[ReflectionIssue] = []
        for node in fact_nodes:
            node_id = str(node.get("node_id") or "")
            if node_id and node_id not in edge_touches:
                metadata = dict(node.get("metadata") or {})
                issues.append(
                    ReflectionIssue(
                        issue_type="isolated_fact",
                        severity="medium",
                        description=f"isolated fact node: {node_id}",
                        related_fact_ids=[str(metadata.get("fact_id") or metadata.get("id") or "")] if (metadata.get("fact_id") or metadata.get("id")) else [],
                    )
                )
        if fact_nodes and dependency_count == 0:
            issues.append(
                ReflectionIssue(
                    issue_type="reasoning_dependency_missing",
                    severity="medium",
                    description="no dependency relation found",
                    related_fact_ids=[str(item.get("id") or item.get("fact_id") or "") for item in (answer.get("facts") or []) if isinstance(item, dict)],
                )
            )
        if fact_nodes and not conclusion_nodes:
            issues.append(
                ReflectionIssue(
                    issue_type="reasoning_conclusion_missing",
                    severity="medium",
                    description="no conclusion node found",
                    related_fact_ids=[str(item.get("id") or item.get("fact_id") or "") for item in (answer.get("facts") or []) if isinstance(item, dict)],
                )
            )
        score = 100.0
        score -= len([item for item in issues if item.issue_type == "isolated_fact"]) * 10.0
        if any(item.issue_type == "reasoning_dependency_missing" for item in issues):
            score -= 20.0
        if any(item.issue_type == "reasoning_conclusion_missing" for item in issues):
            score -= 15.0
        score = max(0.0, round(score, 2))
        self._trace("Reasoning Checked", metadata={"fact_node_count": len(fact_nodes), "conclusion_count": len(conclusion_nodes), "score": score})
        return score, issues

    def check_consistency(self, evidence_bundle: Any, reasoning_context: Any, verification_result: Dict[str, Any]) -> Tuple[float, List[ReflectionIssue]]:
        bundle = self._to_dict(evidence_bundle)
        context = self._to_dict(reasoning_context)
        issues: List[ReflectionIssue] = []
        graph = dict(context.get("reasoning_graph") or {})
        contradict_edges = [item for item in (graph.get("edges") or []) if isinstance(item, dict) and str(item.get("relation") or "").strip().lower() == "contradicts"]
        if bool(verification_result.get("blocking_conflict")) or list(bundle.get("conflicts") or []) or contradict_edges:
            issues.append(
                ReflectionIssue(
                    issue_type="unresolved_conflict",
                    severity="high",
                    description="conflict remains unresolved after verification",
                    related_fact_ids=[],
                    related_evidence_ids=self._collect_conflict_evidence_ids(bundle),
                )
            )
        evidence_ids = {
            str(item.get("evidence_id") or item.get("id") or "")
            for item in (bundle.get("evidences") or [])
            if isinstance(item, dict)
        }
        for fact in (bundle.get("facts") or []):
            if not isinstance(fact, dict):
                continue
            linked = [str(item) for item in (fact.get("evidence_ids") or []) if str(item or "").strip()]
            missing = [item for item in linked if item not in evidence_ids]
            if not missing:
                continue
            issues.append(
                ReflectionIssue(
                    issue_type="fact_evidence_mismatch",
                    severity="medium",
                    description=f"fact references missing evidence ids: {','.join(missing)}",
                    related_fact_ids=[str(fact.get("fact_id") or fact.get("id") or "")] if (fact.get("fact_id") or fact.get("id")) else [],
                    related_evidence_ids=missing,
                )
            )
        score = 100.0 - len(issues) * 20.0
        score = max(0.0, round(score, 2))
        self._trace("Consistency Checked", metadata={"issue_count": len(issues), "score": score})
        return score, issues

    def build_suggestions(self, issues: List[ReflectionIssue]) -> List[str]:
        suggestions: List[str] = []
        issue_types = {item.issue_type for item in (issues or [])}
        if "coverage_insufficient" in issue_types:
            suggestions.append("补齐 missing_fields 对应的事实覆盖。")
        if "unsupported_fact" in issue_types or "citation_missing" in issue_types:
            suggestions.append("补强 Fact 与 Citation 的证据绑定关系。")
        if "reasoning_dependency_missing" in issue_types or "reasoning_conclusion_missing" in issue_types or "isolated_fact" in issue_types:
            suggestions.append("增强 Fact 之间的依赖与结论链路。")
        if "unresolved_conflict" in issue_types or "fact_evidence_mismatch" in issue_types:
            suggestions.append("在后续阶段优先处理冲突与事实-证据不一致问题。")
        return suggestions

    def export_result(self, result: ReflectionResult | Dict[str, Any]) -> Dict[str, Any]:
        if isinstance(result, ReflectionResult):
            return result.to_dict()
        return ReflectionResult.from_dict(result or {}).to_dict()

    def _matching_fact_ids(self, text: str, answer_context: Dict[str, Any]) -> List[str]:
        lowered = str(text or "").strip().lower()
        matched: List[str] = []
        for item in (answer_context.get("facts") or []):
            if not isinstance(item, dict):
                continue
            fact_id = str(item.get("id") or item.get("fact_id") or "")
            fact_text = "::".join(
                [
                    str(item.get("field") or item.get("predicate") or ""),
                    str(item.get("value") or item.get("object") or ""),
                ]
            ).strip().lower()
            if fact_id and fact_text and fact_text in lowered:
                matched.append(fact_id)
        return matched

    def _collect_conflict_evidence_ids(self, bundle: Dict[str, Any]) -> List[str]:
        evidence_ids: List[str] = []
        for item in (bundle.get("conflicts") or []):
            if not isinstance(item, dict):
                continue
            evidence_ids.extend([str(value) for value in (item.get("evidence_ids") or []) if str(value or "").strip()])
        return self._dedupe_list(evidence_ids)

    def _record_metrics(self, result: ReflectionResult) -> None:
        self.runtime_metrics.set("reflection_score", float(result.overall_score or 0.0))
        self.runtime_metrics.set("coverage_score", float(result.coverage_score or 0.0))
        self.runtime_metrics.set("evidence_score", float(result.evidence_score or 0.0))
        self.runtime_metrics.set("reasoning_score", float(result.reasoning_score or 0.0))
        self.runtime_metrics.set("consistency_score", float(result.consistency_score or 0.0))
        self.runtime_metrics.set("reflection_issue_count", float(len(result.issues or [])))

    def _to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                return dict(value.to_dict())
            except Exception:
                return {}
        return {}

    def _dedupe_list(self, items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items or []:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _trace(self, name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event("REFLECTION", name, metadata=metadata or {})
