from __future__ import annotations

from services.tool_registry import ToolDefinition, ToolRegistry


_DEFAULT_REGISTRY: ToolRegistry | None = None


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolDefinition(
            name="query_database",
            display_name="Database Query",
            description="Query intelligence database items by scope, country, entity and keywords.",
            category="retrieval",
            supported_question_types=["NEWS", "TIMELINE", "COUNTRY", "UNKNOWN", "RANKING", "COMPARISON"],
            supported_entities=["organization", "country", "investor"],
            supported_countries=["*"],
            required_arguments=["scope"],
            optional_arguments=["country", "entity", "keywords", "limit"],
            priority=70,
            cost="low",
            latency_level="low",
            supports_batch=True,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_intelligence",
            display_name="Intelligence Query",
            description="Query recent intelligence items and news signals.",
            category="retrieval",
            supported_question_types=["NEWS", "TIMELINE", "RANKING", "COMPARISON", "UNKNOWN"],
            supported_entities=["organization", "country", "investor"],
            supported_countries=["*"],
            required_arguments=["scope"],
            optional_arguments=["country", "entity", "keywords", "limit"],
            priority=85,
            cost="low",
            latency_level="low",
            supports_batch=True,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_contacts",
            display_name="Organization Contacts",
            description="Query organization contact details and leader contacts.",
            category="profile",
            supported_question_types=["CONTACT", "PROFILE"],
            supported_entities=["organization"],
            supported_countries=["*"],
            required_arguments=["org_name"],
            optional_arguments=[],
            priority=90,
            cost="low",
            latency_level="low",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_ontology",
            display_name="Ontology Query",
            description="Query organizations by ontology classification filters.",
            category="classification",
            supported_question_types=["COUNTRY", "PROFILE", "UNKNOWN"],
            supported_entities=["organization"],
            supported_countries=["*"],
            required_arguments=["filter_type", "filter_value"],
            optional_arguments=["country", "limit"],
            priority=55,
            cost="medium",
            latency_level="medium",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_investors",
            display_name="Investor Query",
            description="Query investors and investor profiles.",
            category="investment",
            supported_question_types=["INVESTMENT", "RELATIONSHIP", "GRAPH"],
            supported_entities=["investor", "organization"],
            supported_countries=["*"],
            required_arguments=[],
            optional_arguments=["country", "investor_type", "keywords", "limit"],
            priority=72,
            cost="medium",
            latency_level="medium",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_graph",
            display_name="Graph Query",
            description="Query organization and investment relationship graph.",
            category="graph",
            supported_question_types=["GRAPH", "RELATIONSHIP", "INVESTMENT"],
            supported_entities=["organization", "investor"],
            supported_countries=["*"],
            required_arguments=["entity_name"],
            optional_arguments=["relation_type", "depth", "limit"],
            priority=95,
            cost="medium",
            latency_level="medium",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_funding_rounds",
            display_name="Funding Rounds",
            description="Query funding rounds by entity or filters.",
            category="investment",
            supported_question_types=["INVESTMENT", "RELATIONSHIP"],
            supported_entities=["organization", "investor"],
            supported_countries=["*"],
            required_arguments=[],
            optional_arguments=["entity_name", "country", "round_type", "limit"],
            priority=74,
            cost="medium",
            latency_level="medium",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_fused",
            display_name="Fused Query",
            description="Run fused organization retrieval across multiple sources.",
            category="retrieval",
            supported_question_types=["PROFILE", "COMPARISON", "RANKING", "UNKNOWN"],
            supported_entities=["organization"],
            supported_countries=["*"],
            required_arguments=[],
            optional_arguments=["org_name", "country", "keywords", "limit"],
            priority=68,
            cost="medium",
            latency_level="medium",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_arda_country",
            display_name="ARDA Country",
            description="Query ARDA country level baseline information.",
            category="country",
            supported_question_types=["COUNTRY", "NEWS", "TIMELINE"],
            supported_entities=["country"],
            supported_countries=["*"],
            required_arguments=["country"],
            optional_arguments=[],
            priority=88,
            cost="low",
            latency_level="low",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="query_organization_profile",
            display_name="Organization Profile",
            description="Query organization profile, news, ontology and investor relations.",
            category="profile",
            supported_question_types=["PROFILE", "RANKING", "COMPARISON", "CONTACT", "INVESTMENT"],
            supported_entities=["organization"],
            supported_countries=["*"],
            required_arguments=["org_name"],
            optional_arguments=[],
            priority=92,
            cost="low",
            latency_level="low",
            supports_batch=False,
            supports_stream=False,
            enabled=True,
        )
    )
    return registry


def get_default_registry() -> ToolRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY
