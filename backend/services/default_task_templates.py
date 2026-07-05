from __future__ import annotations

from typing import Any, Dict, List

from services.task_graph import TaskNode


def _task(
    task_id: str,
    name: str,
    description: str,
    task_type: str,
    *,
    priority: int,
    required: bool = True,
    inputs: List[str] | None = None,
    outputs: List[str] | None = None,
    dependencies: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> TaskNode:
    return TaskNode(
        id=task_id,
        name=name,
        description=description,
        task_type=task_type,
        priority=priority,
        required=required,
        status="pending",
        inputs=list(inputs or []),
        outputs=list(outputs or []),
        dependencies=list(dependencies or []),
        metadata=dict(metadata or {}),
    )


def build_research_template() -> List[TaskNode]:
    return [
        _task("research.search", "Research Search", "Search broad evidence and intelligence candidates.", "SEARCH", priority=95, outputs=["search_candidates"]),
        _task("research.retrieve", "Research Retrieve", "Retrieve detailed evidence for research questions.", "RETRIEVE", priority=92, inputs=["search_candidates"], outputs=["retrieved_evidence"], dependencies=["research.search"]),
        _task("research.reason", "Research Reason", "Reason over research evidence.", "REASON", priority=80, inputs=["retrieved_evidence"], outputs=["reasoning_result"], dependencies=["research.retrieve"]),
        _task("research.verify", "Research Verify", "Verify research coverage and consistency.", "VERIFY", priority=70, inputs=["reasoning_result"], outputs=["verification_result"], dependencies=["research.reason"]),
        _task("research.final", "Research Final Generate", "Prepare the final answer payload.", "FINAL_GENERATE", priority=60, inputs=["verification_result"], outputs=["final_answer"], dependencies=["research.verify"]),
    ]


def build_organization_template() -> List[TaskNode]:
    return [
        _task("organization.retrieve", "Organization Retrieve", "Retrieve organization profile information.", "RETRIEVE", priority=95, outputs=["organization_profile"]),
        _task("organization.relationship", "Organization Relationship", "Retrieve organization relationships when relevant.", "RELATIONSHIP", priority=75, required=False, outputs=["organization_relationships"]),
        _task("organization.summarize", "Organization Summarize", "Summarize organization facts.", "SUMMARIZE", priority=65, inputs=["organization_profile"], outputs=["organization_summary"], dependencies=["organization.retrieve"]),
        _task("organization.verify", "Organization Verify", "Verify organization facts and sources.", "VERIFY", priority=60, inputs=["organization_summary"], outputs=["verification_result"], dependencies=["organization.summarize"]),
        _task("organization.final", "Organization Final Generate", "Prepare final organization answer.", "FINAL_GENERATE", priority=55, inputs=["verification_result"], outputs=["final_answer"], dependencies=["organization.verify"]),
    ]


def build_timeline_template() -> List[TaskNode]:
    return [
        _task("timeline.search", "Timeline Search", "Search chronological evidence.", "SEARCH", priority=90, outputs=["timeline_candidates"]),
        _task("timeline.retrieve", "Timeline Retrieve", "Retrieve timeline events and updates.", "TIMELINE", priority=95, inputs=["timeline_candidates"], outputs=["timeline_events"], dependencies=["timeline.search"]),
        _task("timeline.reason", "Timeline Reason", "Order and reason over timeline events.", "REASON", priority=75, inputs=["timeline_events"], outputs=["timeline_reasoning"], dependencies=["timeline.retrieve"]),
        _task("timeline.verify", "Timeline Verify", "Verify timeline completeness and recency.", "VERIFY", priority=65, inputs=["timeline_reasoning"], outputs=["verification_result"], dependencies=["timeline.reason"]),
        _task("timeline.final", "Timeline Final Generate", "Prepare final timeline answer.", "FINAL_GENERATE", priority=55, inputs=["verification_result"], outputs=["final_answer"], dependencies=["timeline.verify"]),
    ]


def build_investment_template() -> List[TaskNode]:
    return [
        _task("investment.retrieve", "Investment Retrieve", "Retrieve investment, funding and investor relations.", "INVESTMENT", priority=95, outputs=["investment_data"]),
        _task("investment.graph", "Investment Graph", "Retrieve graph context for investment entities.", "GRAPH", priority=82, required=False, outputs=["investment_graph"]),
        _task("investment.compare", "Investment Compare", "Compare investment signals when needed.", "COMPARE", priority=70, required=False, inputs=["investment_data"], outputs=["investment_comparison"], dependencies=["investment.retrieve"]),
        _task("investment.verify", "Investment Verify", "Verify investment claims and citations.", "VERIFY", priority=62, inputs=["investment_data"], outputs=["verification_result"], dependencies=["investment.retrieve"]),
        _task("investment.final", "Investment Final Generate", "Prepare final investment answer.", "FINAL_GENERATE", priority=55, inputs=["verification_result"], outputs=["final_answer"], dependencies=["investment.verify"]),
    ]


def build_relationship_template() -> List[TaskNode]:
    return [
        _task("relationship.retrieve", "Relationship Retrieve", "Retrieve direct relationship evidence.", "RELATIONSHIP", priority=95, outputs=["relationship_data"]),
        _task("relationship.graph", "Relationship Graph", "Retrieve graph structure for related entities.", "GRAPH", priority=88, outputs=["relationship_graph"]),
        _task("relationship.reason", "Relationship Reason", "Reason over relationship evidence.", "REASON", priority=72, inputs=["relationship_data", "relationship_graph"], outputs=["relationship_reasoning"], dependencies=["relationship.retrieve", "relationship.graph"]),
        _task("relationship.verify", "Relationship Verify", "Verify relationship claims.", "VERIFY", priority=62, inputs=["relationship_reasoning"], outputs=["verification_result"], dependencies=["relationship.reason"]),
        _task("relationship.final", "Relationship Final Generate", "Prepare final relationship answer.", "FINAL_GENERATE", priority=55, inputs=["verification_result"], outputs=["final_answer"], dependencies=["relationship.verify"]),
    ]


def build_comparison_template() -> List[TaskNode]:
    return [
        _task("comparison.retrieve", "Comparison Retrieve", "Retrieve comparable evidence for entities.", "RETRIEVE", priority=94, outputs=["comparison_inputs"]),
        _task("comparison.compare", "Comparison Compare", "Compare entities across matched dimensions.", "COMPARE", priority=90, inputs=["comparison_inputs"], outputs=["comparison_result"], dependencies=["comparison.retrieve"]),
        _task("comparison.rank", "Comparison Rank", "Rank comparable results when needed.", "RANK", priority=72, required=False, inputs=["comparison_result"], outputs=["ranking_result"], dependencies=["comparison.compare"]),
        _task("comparison.verify", "Comparison Verify", "Verify comparison coverage and consistency.", "VERIFY", priority=62, inputs=["comparison_result"], outputs=["verification_result"], dependencies=["comparison.compare"]),
        _task("comparison.final", "Comparison Final Generate", "Prepare final comparison answer.", "FINAL_GENERATE", priority=55, inputs=["verification_result"], outputs=["final_answer"], dependencies=["comparison.verify"]),
    ]


def get_task_template(template_name: str) -> List[TaskNode]:
    templates = {
        "research": build_research_template,
        "organization": build_organization_template,
        "timeline": build_timeline_template,
        "investment": build_investment_template,
        "relationship": build_relationship_template,
        "comparison": build_comparison_template,
    }
    factory = templates.get(str(template_name or "").strip().lower(), build_research_template)
    return list(factory())
