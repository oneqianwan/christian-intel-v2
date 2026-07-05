from __future__ import annotations

from services.workflow_engine import WorkflowDefinition, WorkflowEdge, WorkflowNode


def _linear_pipeline_workflow(name: str, description: str, pipeline_name: str) -> WorkflowDefinition:
    nodes = [
        WorkflowNode(id="start", name="Start", description="Workflow entry", node_type="START"),
        WorkflowNode(
            id="prepare_context",
            name="Prepare Context",
            description="Build question context, requirement and capability plan.",
            node_type="SERVICE",
            service="prepare_context",
            outputs=["question_context", "requirement", "capability_plan", "memory_context"],
        ),
        WorkflowNode(
            id="retrieval",
            name="Retrieval",
            description="Execute the existing retrieval path and collect tool results.",
            node_type="SERVICE",
            service="retrieval",
            inputs=["question_context", "requirement", "capability_plan"],
            outputs=["tool_results"],
            depends_on=["prepare_context"],
        ),
        WorkflowNode(
            id="knowledge",
            name="Knowledge",
            description="Build knowledge graph from current tool results.",
            node_type="SERVICE",
            service="knowledge",
            inputs=["tool_results"],
            outputs=["knowledge_graph"],
            depends_on=["retrieval"],
        ),
        WorkflowNode(
            id="memory_update",
            name="Memory Update",
            description="Update session memory after knowledge merge.",
            node_type="SERVICE",
            service="memory_update",
            inputs=["knowledge_graph"],
            outputs=["memory_context"],
            depends_on=["knowledge"],
        ),
        WorkflowNode(
            id="answer_composer",
            name="Answer Composer",
            description="Build answer context from merged knowledge and retrieval results.",
            node_type="SERVICE",
            service="answer_composer",
            inputs=["tool_results", "knowledge_graph", "memory_context"],
            outputs=["answer_context"],
            depends_on=["memory_update"],
        ),
        WorkflowNode(
            id="verification",
            name="Verification",
            description="Evaluate coverage, citations and conflicts.",
            node_type="SERVICE",
            service="verification",
            inputs=["answer_context", "knowledge_graph"],
            outputs=["verification"],
            depends_on=["answer_composer"],
        ),
        WorkflowNode(
            id="loop_condition",
            name="Loop Condition",
            description="Decide whether the retrieval loop should continue.",
            node_type="CONDITION",
            condition="Loop Continue",
            inputs=["verification"],
            depends_on=["verification"],
        ),
        WorkflowNode(
            id="retrieval_loop",
            name="Retrieval Loop",
            description="Run the existing retrieval loop controller path when needed.",
            node_type="LOOP",
            service="retrieval_loop",
            inputs=["verification", "knowledge_graph", "answer_context"],
            outputs=["tool_results", "knowledge_graph", "answer_context", "verification", "loop_summary"],
            depends_on=["loop_condition"],
        ),
        WorkflowNode(
            id="memory_snapshot",
            name="Memory Snapshot",
            description="Create memory snapshot after verification and optional loop.",
            node_type="SERVICE",
            service="memory_snapshot",
            inputs=["knowledge_graph", "verification"],
            outputs=["memory_context"],
            depends_on=["verification"],
        ),
        WorkflowNode(
            id="llm",
            name="LLM",
            description="Run the existing final generation path.",
            node_type="SERVICE",
            service="llm",
            inputs=["tool_results", "knowledge_graph", "answer_context", "verification", "loop_summary"],
            outputs=["final_result"],
            depends_on=["memory_snapshot"],
        ),
        WorkflowNode(id="end", name="End", description="Workflow exit", node_type="END", depends_on=["llm"]),
    ]
    edges = [
        WorkflowEdge(source="start", target="prepare_context"),
        WorkflowEdge(source="prepare_context", target="retrieval"),
        WorkflowEdge(source="retrieval", target="knowledge"),
        WorkflowEdge(source="knowledge", target="memory_update"),
        WorkflowEdge(source="memory_update", target="answer_composer"),
        WorkflowEdge(source="answer_composer", target="verification"),
        WorkflowEdge(source="verification", target="loop_condition"),
        WorkflowEdge(source="loop_condition", target="retrieval_loop", condition="true"),
        WorkflowEdge(source="loop_condition", target="memory_snapshot", condition="false"),
        WorkflowEdge(source="retrieval_loop", target="memory_snapshot"),
        WorkflowEdge(source="memory_snapshot", target="llm"),
        WorkflowEdge(source="llm", target="end"),
    ]
    return WorkflowDefinition(
        name=name,
        description=description,
        nodes=nodes,
        edges=edges,
        entry_nodes=["start"],
        exit_nodes=["end"],
        version="v1",
        metadata={"pipeline_name": pipeline_name},
    )


def build_default_workflows() -> list[WorkflowDefinition]:
    return [
        _linear_pipeline_workflow("StandardWorkflow", "Default workflow for standard pipeline execution.", "StandardPipeline"),
        _linear_pipeline_workflow("ResearchWorkflow", "Workflow for research-oriented pipeline execution.", "ResearchPipeline"),
        _linear_pipeline_workflow("OrganizationWorkflow", "Workflow for organization-focused pipeline execution.", "OrganizationPipeline"),
        _linear_pipeline_workflow("TimelineWorkflow", "Workflow for timeline-oriented pipeline execution.", "TimelinePipeline"),
        _linear_pipeline_workflow("GraphWorkflow", "Workflow for graph-oriented pipeline execution.", "GraphPipeline"),
        _linear_pipeline_workflow("InvestmentWorkflow", "Workflow for investment-oriented pipeline execution.", "InvestmentPipeline"),
        _linear_pipeline_workflow("RelationshipWorkflow", "Workflow for relationship-oriented pipeline execution.", "RelationshipPipeline"),
    ]


_DEFAULT_WORKFLOWS: list[WorkflowDefinition] | None = None


def get_default_workflows() -> list[WorkflowDefinition]:
    global _DEFAULT_WORKFLOWS
    if _DEFAULT_WORKFLOWS is None:
        _DEFAULT_WORKFLOWS = build_default_workflows()
    return list(_DEFAULT_WORKFLOWS)


def get_workflow_for_pipeline(pipeline_name: str) -> WorkflowDefinition:
    normalized = str(pipeline_name or "").strip()
    for workflow in get_default_workflows():
        if str((workflow.metadata or {}).get("pipeline_name") or "") == normalized:
            return workflow
    for workflow in get_default_workflows():
        if workflow.name == "StandardWorkflow":
            return workflow
    return build_default_workflows()[0]
