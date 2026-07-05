from __future__ import annotations

from services.architecture_governor import PipelineDefinition


_DEFAULT_PIPELINE_REGISTRY: list[PipelineDefinition] | None = None


def build_default_pipeline_registry() -> list[PipelineDefinition]:
    return [
        PipelineDefinition(
            name="StandardPipeline",
            description="General fallback pipeline for standard intelligence questions.",
            supported_question_types=["UNKNOWN", "PROFILE", "NEWS", "COUNTRY", "COMPARISON", "RANKING"],
            supported_capabilities=["PROFILE", "NEWS", "DATABASE", "COUNTRY_BASELINE", "RANKING"],
            priority=70,
            cost="low",
            latency="low",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="ResearchPipeline",
            description="Research-oriented pipeline for broad investigation, ranking and evidence-heavy retrieval.",
            supported_question_types=["UNKNOWN", "NEWS", "TIMELINE", "RANKING", "COUNTRY"],
            supported_capabilities=["NEWS", "TIMELINE", "DATABASE", "RANKING", "COUNTRY_BASELINE"],
            priority=82,
            cost="medium",
            latency="medium",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="OrganizationPipeline",
            description="Entity-centric pipeline for organization profile and contact questions.",
            supported_question_types=["PROFILE", "CONTACT", "COMPARISON"],
            supported_capabilities=["PROFILE", "CONTACTS", "NEWS", "DATABASE"],
            priority=90,
            cost="low",
            latency="low",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="GraphPipeline",
            description="Graph-oriented pipeline for network and graph traversal questions.",
            supported_question_types=["GRAPH"],
            supported_capabilities=["GRAPH", "RELATIONSHIP", "PROFILE"],
            priority=94,
            cost="medium",
            latency="medium",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="TimelinePipeline",
            description="Timeline-oriented pipeline for chronological news and change tracking questions.",
            supported_question_types=["TIMELINE", "NEWS"],
            supported_capabilities=["TIMELINE", "NEWS", "DATABASE"],
            priority=91,
            cost="medium",
            latency="medium",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="InvestmentPipeline",
            description="Investment-oriented pipeline for investors, funding and financing relationships.",
            supported_question_types=["INVESTMENT"],
            supported_capabilities=["INVESTMENT", "GRAPH", "RELATIONSHIP", "PROFILE"],
            priority=93,
            cost="medium",
            latency="medium",
            supports_stream=True,
            enabled=True,
        ),
        PipelineDefinition(
            name="RelationshipPipeline",
            description="Relationship-oriented pipeline for partnerships, affiliation and cross-entity links.",
            supported_question_types=["RELATIONSHIP"],
            supported_capabilities=["RELATIONSHIP", "GRAPH", "PROFILE"],
            priority=92,
            cost="medium",
            latency="medium",
            supports_stream=True,
            enabled=True,
        ),
    ]


def get_default_pipeline_registry() -> list[PipelineDefinition]:
    global _DEFAULT_PIPELINE_REGISTRY
    if _DEFAULT_PIPELINE_REGISTRY is None:
        _DEFAULT_PIPELINE_REGISTRY = build_default_pipeline_registry()
    return list(_DEFAULT_PIPELINE_REGISTRY)
