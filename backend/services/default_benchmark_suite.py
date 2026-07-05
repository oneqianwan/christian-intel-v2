from __future__ import annotations

from services.benchmark_framework import BenchmarkCase, BenchmarkSuite


def _case(
    *,
    case_id: str,
    category: str,
    difficulty: str,
    question: str,
    entity: str = "",
    fields: list[str] | None = None,
    sources: list[str] | None = None,
    keywords: list[str] | None = None,
    citations: int = 2,
    description: str = "",
) -> BenchmarkCase:
    return BenchmarkCase(
        id=case_id,
        name=f"{category} {case_id}",
        description=description or f"Benchmark case for {category.lower()} queries.",
        question=question,
        expected_entities=[entity] if entity else [],
        expected_fields=list(fields or []),
        expected_sources=list(sources or []),
        expected_answer_keywords=list(keywords or []),
        expected_citations=int(citations or 0),
        minimum_coverage=0.6,
        minimum_confidence=0.5,
        allow_partial=True,
        category=category,
        difficulty=difficulty,
    )


def _organization_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="ORG-001", category="Organization", difficulty="easy", question="Give me the organization profile of World Vision International.", entity="World Vision International", fields=["name", "website", "leader_name", "country"], sources=["database", "profile"], keywords=["world vision", "leader", "website"]),
        _case(case_id="ORG-002", category="Organization", difficulty="easy", question="Who leads Samaritan's Purse and what is its website?", entity="Samaritan's Purse", fields=["leader_name", "website", "country"], sources=["database"], keywords=["samaritan", "leader", "website"]),
        _case(case_id="ORG-003", category="Organization", difficulty="medium", question="Summarize the profile of Alpha USA, including denomination and leadership.", entity="Alpha USA", fields=["name", "denomination", "leader_name", "country"], sources=["profile"], keywords=["alpha", "denomination", "leader"]),
        _case(case_id="ORG-004", category="Organization", difficulty="medium", question="What are the key facts for Compassion International as an organization?", entity="Compassion International", fields=["name", "country", "website", "leader_name"], sources=["database", "profile"], keywords=["compassion", "international"]),
        _case(case_id="ORG-005", category="Organization", difficulty="hard", question="Provide a structured organization overview for Open Doors International.", entity="Open Doors International", fields=["name", "website", "leader_name", "country", "member_count"], sources=["database"], keywords=["open doors", "overview"]),
    ]


def _relationship_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="REL-001", category="Relationship", difficulty="easy", question="What is the relationship between OpenAI and Microsoft?", entity="OpenAI", fields=["relationship", "source"], sources=["graph", "database"], keywords=["relationship", "microsoft", "openai"]),
        _case(case_id="REL-002", category="Relationship", difficulty="medium", question="Explain the relationship between World Vision International and its key country entities.", entity="World Vision International", fields=["relationship", "country", "source"], sources=["graph"], keywords=["relationship", "country"]),
        _case(case_id="REL-003", category="Relationship", difficulty="medium", question="How is Alpha USA connected to Alpha International?", entity="Alpha USA", fields=["relationship", "source"], sources=["graph", "profile"], keywords=["alpha usa", "alpha international"]),
        _case(case_id="REL-004", category="Relationship", difficulty="hard", question="Map the relationship between Compassion International and partner churches.", entity="Compassion International", fields=["relationship", "source", "country"], sources=["graph"], keywords=["partner", "churches"]),
        _case(case_id="REL-005", category="Relationship", difficulty="hard", question="Describe the relationship network around Samaritan's Purse and Franklin Graham.", entity="Samaritan's Purse", fields=["relationship", "leader_name", "source"], sources=["graph", "database"], keywords=["franklin graham", "network"]),
    ]


def _timeline_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="TIM-001", category="Timeline", difficulty="easy", question="What is the recent timeline for OpenAI?", entity="OpenAI", fields=["title", "published_at", "source"], sources=["news", "database"], keywords=["timeline", "recent"]),
        _case(case_id="TIM-002", category="Timeline", difficulty="easy", question="Give me the latest news timeline for Vatican City church policy changes.", entity="Vatican City", fields=["title", "published_at", "source_name"], sources=["news"], keywords=["latest", "timeline", "policy"]),
        _case(case_id="TIM-003", category="Timeline", difficulty="medium", question="Summarize the timeline of Compassion International's recent expansion.", entity="Compassion International", fields=["title", "snippet", "published_at", "source"], sources=["news"], keywords=["expansion", "timeline"]),
        _case(case_id="TIM-004", category="Timeline", difficulty="medium", question="What notable events happened recently for Alpha USA?", entity="Alpha USA", fields=["title", "updated_at", "source_name"], sources=["news", "database"], keywords=["notable", "events"]),
        _case(case_id="TIM-005", category="Timeline", difficulty="hard", question="Build a timeline for Open Doors International using the latest intelligence items.", entity="Open Doors International", fields=["title", "published_at", "source_name", "url"], sources=["news", "intelligence"], keywords=["latest intelligence", "timeline"]),
    ]


def _investment_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="INV-001", category="Investment", difficulty="easy", question="What are OpenAI's recent investment activities?", entity="OpenAI", fields=["investment", "source", "published_at"], sources=["graph", "database"], keywords=["investment", "openai"]),
        _case(case_id="INV-002", category="Investment", difficulty="medium", question="Show investment relationships around Microsoft and OpenAI.", entity="Microsoft", fields=["investment", "relationship", "source"], sources=["graph"], keywords=["investment", "microsoft"]),
        _case(case_id="INV-003", category="Investment", difficulty="medium", question="What funding signals are visible for faith-based startups in the United States?", entity="United States", fields=["country", "title", "source"], sources=["news", "database"], keywords=["funding", "faith-based"]),
        _case(case_id="INV-004", category="Investment", difficulty="hard", question="Benchmark the investment pattern linked to OpenAI, Microsoft, and key partners.", entity="OpenAI", fields=["investment", "relationship", "source", "title"], sources=["graph", "news"], keywords=["pattern", "partners"]),
        _case(case_id="INV-005", category="Investment", difficulty="hard", question="List investment-related evidence for global Christian media organizations.", entity="Christian media organizations", fields=["title", "source_name", "country"], sources=["news", "database"], keywords=["media", "investment"]),
    ]


def _country_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="CTR-001", category="Country", difficulty="easy", question="What is the Christian baseline for Brazil?", entity="Brazil", fields=["country", "source", "title"], sources=["country_baseline", "database"], keywords=["brazil", "baseline"]),
        _case(case_id="CTR-002", category="Country", difficulty="easy", question="Summarize the church environment in Nigeria.", entity="Nigeria", fields=["country", "source", "title"], sources=["country_baseline"], keywords=["nigeria", "church"]),
        _case(case_id="CTR-003", category="Country", difficulty="medium", question="What are the major Christian trends in India?", entity="India", fields=["country", "title", "source_name"], sources=["country_baseline", "news"], keywords=["india", "trends"]),
        _case(case_id="CTR-004", category="Country", difficulty="medium", question="Give a country intelligence summary for South Korea.", entity="South Korea", fields=["country", "title", "source", "published_at"], sources=["country_baseline", "news"], keywords=["south korea", "summary"]),
        _case(case_id="CTR-005", category="Country", difficulty="hard", question="Compare the Christian operating environment of Kenya using current intelligence.", entity="Kenya", fields=["country", "title", "source_name", "relationship"], sources=["country_baseline", "news"], keywords=["kenya", "current intelligence"]),
    ]


def _graph_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="GRF-001", category="Graph", difficulty="easy", question="Show the graph around OpenAI.", entity="OpenAI", fields=["graph", "relationship", "source"], sources=["graph"], keywords=["graph", "openai"]),
        _case(case_id="GRF-002", category="Graph", difficulty="easy", question="Render the graph for Samaritan's Purse and its leadership.", entity="Samaritan's Purse", fields=["graph", "leader_name", "source"], sources=["graph", "database"], keywords=["graph", "leadership"]),
        _case(case_id="GRF-003", category="Graph", difficulty="medium", question="What does the graph look like for World Vision International?", entity="World Vision International", fields=["graph", "country", "source"], sources=["graph"], keywords=["world vision", "graph"]),
        _case(case_id="GRF-004", category="Graph", difficulty="medium", question="Map the graph of Compassion International and associated people.", entity="Compassion International", fields=["graph", "relationship", "leader_name"], sources=["graph"], keywords=["map", "people"]),
        _case(case_id="GRF-005", category="Graph", difficulty="hard", question="Create a graph-oriented overview for Alpha USA across entities and countries.", entity="Alpha USA", fields=["graph", "relationship", "country", "source"], sources=["graph", "database"], keywords=["entities", "countries"]),
    ]


def _comparison_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="CMP-001", category="Comparison", difficulty="medium", question="Compare OpenAI and Microsoft on relationship and investment signals.", entity="OpenAI", fields=["relationship", "investment", "source"], sources=["graph", "database"], keywords=["compare", "microsoft", "openai"]),
        _case(case_id="CMP-002", category="Comparison", difficulty="medium", question="Compare World Vision International and Compassion International.", entity="World Vision International", fields=["name", "country", "leader_name", "source"], sources=["database", "profile"], keywords=["compare", "compassion"]),
        _case(case_id="CMP-003", category="Comparison", difficulty="hard", question="Compare Nigeria and Brazil on Christian baseline indicators.", entity="Nigeria", fields=["country", "title", "source_name"], sources=["country_baseline"], keywords=["nigeria", "brazil", "compare"]),
        _case(case_id="CMP-004", category="Comparison", difficulty="hard", question="Compare Alpha USA and Alpha International on organization profile and reach.", entity="Alpha USA", fields=["name", "website", "country", "relationship"], sources=["profile", "graph"], keywords=["reach", "profile"]),
        _case(case_id="CMP-005", category="Comparison", difficulty="hard", question="Compare Open Doors International and Samaritan's Purse across leadership and geography.", entity="Open Doors International", fields=["leader_name", "country", "source"], sources=["database", "profile"], keywords=["leadership", "geography"]),
    ]


def _ranking_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="RNK-001", category="Ranking", difficulty="medium", question="Rank the most visible recent Christian aid organizations by intelligence coverage.", entity="Christian aid organizations", fields=["ranking", "title", "source"], sources=["news", "database"], keywords=["rank", "coverage"]),
        _case(case_id="RNK-002", category="Ranking", difficulty="medium", question="Which faith-based organizations appear most connected in the graph?", entity="faith-based organizations", fields=["ranking", "relationship", "source"], sources=["graph"], keywords=["connected", "graph"]),
        _case(case_id="RNK-003", category="Ranking", difficulty="hard", question="Rank OpenAI ecosystem entities by relationship density.", entity="OpenAI", fields=["ranking", "relationship", "source"], sources=["graph"], keywords=["density", "ecosystem"]),
        _case(case_id="RNK-004", category="Ranking", difficulty="hard", question="Rank countries by current Christian intelligence signal volume.", entity="countries", fields=["ranking", "country", "source_name"], sources=["news", "country_baseline"], keywords=["signal volume", "countries"]),
        _case(case_id="RNK-005", category="Ranking", difficulty="hard", question="Rank organizations with the strongest recent leadership visibility.", entity="organizations", fields=["ranking", "leader_name", "source"], sources=["news", "database"], keywords=["leadership visibility"]),
    ]


def _unknown_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="UNK-001", category="Unknown", difficulty="easy", question="Tell me something useful about OpenAI.", entity="OpenAI", fields=["title", "source"], sources=["database", "news"], keywords=["openai", "useful"]),
        _case(case_id="UNK-002", category="Unknown", difficulty="easy", question="What should I know about Alpha USA?", entity="Alpha USA", fields=["name", "source"], sources=["profile", "database"], keywords=["alpha usa"]),
        _case(case_id="UNK-003", category="Unknown", difficulty="medium", question="Help me understand World Vision International.", entity="World Vision International", fields=["name", "leader_name", "source"], sources=["database"], keywords=["understand", "world vision"]),
        _case(case_id="UNK-004", category="Unknown", difficulty="medium", question="Give me an overview of Nigeria church intelligence.", entity="Nigeria", fields=["country", "title", "source"], sources=["country_baseline", "news"], keywords=["overview", "nigeria"]),
        _case(case_id="UNK-005", category="Unknown", difficulty="hard", question="What can this system infer about Compassion International right now?", entity="Compassion International", fields=["title", "source_name", "country"], sources=["database", "news"], keywords=["infer", "right now"]),
    ]


def _mixed_cases() -> list[BenchmarkCase]:
    return [
        _case(case_id="MIX-001", category="Mixed Query", difficulty="hard", question="Give me the organization profile, recent timeline, and relationship graph for OpenAI.", entity="OpenAI", fields=["name", "leader_name", "title", "relationship", "source"], sources=["database", "news", "graph"], keywords=["profile", "timeline", "graph"]),
        _case(case_id="MIX-002", category="Mixed Query", difficulty="hard", question="Summarize Brazil's Christian baseline and connect it to major organizations and recent events.", entity="Brazil", fields=["country", "relationship", "title", "source_name"], sources=["country_baseline", "news", "graph"], keywords=["baseline", "organizations", "events"]),
        _case(case_id="MIX-003", category="Mixed Query", difficulty="hard", question="Compare Alpha USA with Alpha International and include recent timeline evidence.", entity="Alpha USA", fields=["relationship", "title", "source", "leader_name"], sources=["graph", "news", "profile"], keywords=["compare", "timeline evidence"]),
        _case(case_id="MIX-004", category="Mixed Query", difficulty="hard", question="Show the graph, leadership, and current intelligence around Samaritan's Purse.", entity="Samaritan's Purse", fields=["graph", "leader_name", "title", "source"], sources=["graph", "database", "news"], keywords=["leadership", "current intelligence"]),
        _case(case_id="MIX-005", category="Mixed Query", difficulty="hard", question="Build a mixed intelligence brief for Compassion International across profile, relationships, and latest updates.", entity="Compassion International", fields=["name", "relationship", "title", "source_name"], sources=["database", "graph", "news"], keywords=["brief", "latest updates"]),
    ]


def get_default_benchmark_suite() -> BenchmarkSuite:
    cases = (
        _organization_cases()
        + _relationship_cases()
        + _timeline_cases()
        + _investment_cases()
        + _country_cases()
        + _graph_cases()
        + _comparison_cases()
        + _ranking_cases()
        + _unknown_cases()
        + _mixed_cases()
    )
    return BenchmarkSuite(
        name="Default Benchmark Suite V1",
        description="Default enterprise benchmark suite for agent pipeline runtime evaluation.",
        cases=cases,
    )
