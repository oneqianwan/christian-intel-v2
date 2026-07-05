from __future__ import annotations

from typing import Any

from services.feature_flags import feature_flag_enabled
from services.service_container import ServiceContainer, ServiceDefinition, ServiceScope


def _enabled(name: str, default: bool = True) -> bool:
    return feature_flag_enabled(name, default=default)


def _optional_service(container: ServiceContainer, name: str) -> Any:
    if not container.has(name):
        return None
    try:
        return container.get(name)
    except Exception:
        return None


def _build_reasoning_engine(**_kwargs):
    from services.reasoning_engine_v1 import ReasoningEngineV1

    return ReasoningEngineV1()


def _build_answer_composer(**_kwargs):
    from services.answer_composer import AnswerComposer

    return AnswerComposer()


def _build_knowledge_layer(*, container: ServiceContainer, **_kwargs):
    from services.knowledge_layer import KnowledgeLayer

    return KnowledgeLayer(trace_center=_optional_service(container, "trace_center"))


def _build_memory_layer(*, container: ServiceContainer, **_kwargs):
    from services.memory_layer import MemoryLayer

    return MemoryLayer(trace_center=_optional_service(container, "trace_center"))


def _build_tool_registry(**_kwargs):
    from services.default_registry import get_default_registry

    return get_default_registry()


def _build_capability_planner(**_kwargs):
    from services.capability_planner import CapabilityPlanner

    return CapabilityPlanner()


def _build_trace_center(**_kwargs):
    from services.trace_center import TraceCenter

    return TraceCenter(enabled=_enabled("TRACE_CENTER_ENABLED", default=True))


def _build_retrieval_loop_controller(
    *,
    container: ServiceContainer,
    scope: ServiceScope,
    tool_registry: Any = None,
    capability_planner: Any = None,
    **_kwargs,
):
    from services.retrieval_loop_controller import RetrievalLoopController

    pipeline_context = getattr(scope, "pipeline_context", None)
    question_context = getattr(pipeline_context, "question_context", None)
    default_entity = ""
    default_country = ""
    default_question_type = "UNKNOWN"
    if question_context is not None:
        entities = list(getattr(question_context, "entities", []) or [])
        if entities and isinstance(entities[0], dict):
            default_entity = str(entities[0].get("name") or "")
        default_country = str(getattr(question_context, "country", "") or "")
        question_type = getattr(question_context, "question_type", None)
        default_question_type = (
            question_type.value if hasattr(question_type, "value") else str(question_type or "UNKNOWN")
        )
    return RetrievalLoopController(
        default_entity=default_entity,
        default_country=default_country,
        default_question_type=default_question_type,
        registry=tool_registry,
        capability_planner=capability_planner,
        trace_center=_optional_service(container, "trace_center"),
    )


def _build_pipeline_service(
    *,
    container: ServiceContainer,
    service_definition: ServiceDefinition,
    **_kwargs,
):
    from services.pipeline_orchestrator import PipelineOrchestrator

    brain = (service_definition.metadata or {}).get("brain")
    return PipelineOrchestrator(brain=brain, container=container)


def _build_architecture_governor(
    *,
    container: ServiceContainer,
    service_definition: ServiceDefinition,
    **_kwargs,
):
    from services.architecture_governor import ArchitectureGovernor

    brain = (service_definition.metadata or {}).get("brain")
    return ArchitectureGovernor(brain=brain, container=container)


def register_default_services(container: ServiceContainer, *, brain: Any = None) -> ServiceContainer:
    retrieval_loop_dependencies = []
    if _enabled("TOOL_REGISTRY_ENABLED", default=True):
        retrieval_loop_dependencies.append("tool_registry")
    if _enabled("CAPABILITY_PLANNER_ENABLED", default=True):
        retrieval_loop_dependencies.append("capability_planner")

    container.register(
        ServiceDefinition(
            name="trace_center",
            service_type="observability",
            implementation=_build_trace_center,
            singleton=True,
            enabled=_enabled("TRACE_CENTER_ENABLED", default=True),
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="reasoning_engine",
            service_type="reasoning",
            implementation=_build_reasoning_engine,
            singleton=True,
            enabled=True,
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="answer_composer",
            service_type="composer",
            implementation=_build_answer_composer,
            singleton=True,
            enabled=True,
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="knowledge_layer",
            service_type="knowledge",
            implementation=_build_knowledge_layer,
            singleton=False,
            enabled=_enabled("KNOWLEDGE_LAYER_ENABLED", default=True),
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="memory_layer",
            service_type="memory",
            implementation=_build_memory_layer,
            singleton=False,
            enabled=_enabled("MEMORY_LAYER_ENABLED", default=True),
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="tool_registry",
            service_type="registry",
            implementation=_build_tool_registry,
            singleton=True,
            enabled=_enabled("TOOL_REGISTRY_ENABLED", default=True),
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="capability_planner",
            service_type="planner",
            implementation=_build_capability_planner,
            singleton=True,
            enabled=_enabled("CAPABILITY_PLANNER_ENABLED", default=True),
            dependencies=[],
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="retrieval_loop_controller",
            service_type="controller",
            implementation=_build_retrieval_loop_controller,
            singleton=False,
            enabled=_enabled("RETRIEVAL_LOOP_ENABLED", default=True),
            dependencies=retrieval_loop_dependencies,
            metadata={"service_group": "core"},
        )
    )
    container.register(
        ServiceDefinition(
            name="pipeline_service",
            service_type="pipeline",
            implementation=_build_pipeline_service,
            singleton=False,
            enabled=_enabled("PIPELINE_ORCHESTRATOR_ENABLED", default=True),
            dependencies=[],
            metadata={"brain": brain, "service_group": "entry"},
        )
    )
    container.register(
        ServiceDefinition(
            name="architecture_governor",
            service_type="governor",
            implementation=_build_architecture_governor,
            singleton=False,
            enabled=_enabled("ARCHITECTURE_GOVERNOR_ENABLED", default=True),
            dependencies=[],
            metadata={"brain": brain, "service_group": "entry"},
        )
    )
    return container


def build_default_service_container(
    *,
    brain: Any = None,
    scope: ServiceScope | None = None,
    trace_center: Any = None,
) -> ServiceContainer:
    container = ServiceContainer(scope=scope, trace_center=trace_center)
    return register_default_services(container, brain=brain)
