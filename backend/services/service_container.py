from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, List

from services.runtime_metrics import get_runtime_metrics


def _serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            return value.to_dict()
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    return value


def _callable_name(value: Any) -> str:
    if value is None:
        return ""
    module = getattr(value, "__module__", "")
    qualname = getattr(value, "__qualname__", getattr(value, "__name__", ""))
    if module and qualname:
        return f"{module}.{qualname}"
    return str(value)


@dataclass
class ServiceDefinition:
    name: str
    service_type: str
    implementation: Any
    singleton: bool = True
    enabled: bool = True
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "service_type": self.service_type,
            "implementation": _callable_name(self.implementation),
            "singleton": bool(self.singleton),
            "enabled": bool(self.enabled),
            "dependencies": list(self.dependencies or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceDefinition":
        payload = data or {}
        return cls(
            name=str(payload.get("name") or ""),
            service_type=str(payload.get("service_type") or ""),
            implementation=payload.get("implementation"),
            singleton=bool(payload.get("singleton", True)),
            enabled=bool(payload.get("enabled", True)),
            dependencies=[str(item) for item in (payload.get("dependencies") or []) if str(item or "").strip()],
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class ServiceScope:
    conversation_id: str = ""
    trace_id: str = ""
    memory_context: Any = None
    pipeline_context: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "trace_id": self.trace_id,
            "memory_context": _serialize_value(self.memory_context),
            "pipeline_context": _serialize_value(self.pipeline_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ServiceScope":
        payload = data or {}
        return cls(
            conversation_id=str(payload.get("conversation_id") or ""),
            trace_id=str(payload.get("trace_id") or ""),
            memory_context=payload.get("memory_context"),
            pipeline_context=payload.get("pipeline_context"),
        )


class ServiceContainer:
    def __init__(self, *, scope: ServiceScope | None = None, trace_center: Any = None):
        self.scope = scope or ServiceScope()
        self.trace_center = trace_center
        self._runtime_metrics = get_runtime_metrics()
        self._definitions: Dict[str, ServiceDefinition] = {}
        self._singletons: Dict[str, Any] = {}
        self._resolving: List[str] = []
        self._pending_events: List[Dict[str, Any]] = []
        self._runtime_metrics.set("singleton_count", 0.0)
        self._record_event(
            "Container Initialized",
            metadata={"scope": self.scope.to_dict()},
        )

    def register(self, service_definition: ServiceDefinition) -> None:
        if not isinstance(service_definition, ServiceDefinition):
            raise TypeError("service_definition must be ServiceDefinition")
        service_name = str(service_definition.name or "").strip()
        if not service_name:
            raise ValueError("service_definition.name is required")
        self._definitions[service_name] = service_definition
        if service_name in self._singletons and not service_definition.singleton:
            self._singletons.pop(service_name, None)
            self._runtime_metrics.set("singleton_count", float(len(self._singletons)))
        self._record_event(
            "Service Registered",
            metadata={
                "service_name": service_name,
                "service_type": service_definition.service_type,
                "singleton": bool(service_definition.singleton),
                "enabled": bool(service_definition.enabled),
                "dependencies": list(service_definition.dependencies or []),
            },
        )

    def unregister(self, name: str) -> None:
        service_name = str(name or "").strip()
        self._definitions.pop(service_name, None)
        instance = self._singletons.pop(service_name, None)
        self._runtime_metrics.set("singleton_count", float(len(self._singletons)))
        self._shutdown_instance(instance)

    def get(self, name: str, *, scope: ServiceScope | None = None, _emit_trace: bool = True) -> Any:
        service_name = str(name or "").strip()
        if not service_name:
            raise KeyError("service name is required")
        definition = self._definitions.get(service_name)
        if definition is None:
            raise KeyError(f"service '{service_name}' is not registered")
        if not definition.enabled:
            raise ValueError(f"service '{service_name}' is disabled")
        if definition.singleton and service_name in self._singletons:
            instance = self._singletons[service_name]
            if _emit_trace:
                self._runtime_metrics.inc("container_resolve", labels={"service_name": service_name, "singleton_hit": "true"})
                self._record_event(
                    "Service Resolved",
                    metadata={"service_name": service_name, "singleton_hit": True},
                )
            return instance
        if service_name in self._resolving:
            chain = " -> ".join(self._resolving + [service_name])
            raise RuntimeError(f"circular service dependency detected: {chain}")

        active_scope = scope or self.scope
        self._resolving.append(service_name)
        try:
            resolved_dependencies = self.resolve_dependencies(definition.dependencies, scope=active_scope)
            instance = self._instantiate(definition, resolved_dependencies, active_scope)
            if definition.singleton:
                self._singletons[service_name] = instance
                if _emit_trace:
                    self._runtime_metrics.inc("container_singleton", labels={"service_name": service_name})
                    self._runtime_metrics.set("singleton_count", float(len(self._singletons)))
                    self._record_event(
                        "Singleton Created",
                        metadata={"service_name": service_name},
                    )
            if _emit_trace:
                self._runtime_metrics.inc("container_resolve", labels={"service_name": service_name, "singleton_hit": "false"})
                self._record_event(
                    "Service Resolved",
                    metadata={
                        "service_name": service_name,
                        "singleton_hit": False,
                        "dependencies": list(definition.dependencies or []),
                    },
                )
            return instance
        finally:
            if self._resolving and self._resolving[-1] == service_name:
                self._resolving.pop()
            else:
                self._resolving = [item for item in self._resolving if item != service_name]

    def has(self, name: str) -> bool:
        return str(name or "").strip() in self._definitions

    def list_services(self) -> List[Dict[str, Any]]:
        return [self._definitions[name].to_dict() for name in sorted(self._definitions)]

    def resolve_dependencies(self, dependencies: List[str], *, scope: ServiceScope | None = None) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        active_scope = scope or self.scope
        for dependency_name in dependencies or []:
            service_name = str(dependency_name or "").strip()
            if not service_name:
                continue
            resolved[service_name] = self.get(service_name, scope=active_scope, _emit_trace=False)
            self._runtime_metrics.inc("container_dependency", labels={"dependency_name": service_name})
            self._record_event(
                "Dependency Resolved",
                metadata={"dependency_name": service_name, "scope": active_scope.to_dict()},
            )
        return resolved

    def initialize_singletons(self, *, scope: ServiceScope | None = None) -> None:
        active_scope = scope or self.scope
        for definition in list(self._definitions.values()):
            if not definition.enabled or not definition.singleton:
                continue
            self.get(definition.name, scope=active_scope)

    def shutdown(self) -> None:
        for instance in list(self._singletons.values()):
            self._shutdown_instance(instance)
        self._singletons.clear()
        self._runtime_metrics.set("singleton_count", 0.0)
        self._record_event("Container Shutdown", metadata={"service_count": len(self._definitions)})

    def _instantiate(
        self,
        definition: ServiceDefinition,
        resolved_dependencies: Dict[str, Any],
        scope: ServiceScope,
    ) -> Any:
        implementation = definition.implementation
        if not callable(implementation):
            return implementation
        kwargs = {"container": self, "scope": scope, "service_definition": definition, **resolved_dependencies}
        call_kwargs = self._filter_call_kwargs(implementation, kwargs)
        return implementation(**call_kwargs)

    def _filter_call_kwargs(self, implementation: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        try:
            signature = inspect.signature(implementation)
        except (TypeError, ValueError):
            return kwargs
        parameters = signature.parameters
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return kwargs
        allowed = {
            name
            for name, param in parameters.items()
            if param.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        }
        return {key: value for key, value in kwargs.items() if key in allowed}

    def _shutdown_instance(self, instance: Any) -> None:
        if instance is None:
            return
        for method_name in ("shutdown", "close"):
            method = getattr(instance, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                return

    def _record_event(self, name: str, *, metadata: Dict[str, Any] | None = None) -> None:
        payload = {"name": str(name or ""), "metadata": dict(metadata or {})}
        trace_center = self._resolve_trace_center()
        if trace_center is None:
            self._pending_events.append(payload)
            return
        self._flush_pending_events(trace_center)
        event = trace_center.record_event(
            "SERVICE_CONTAINER",
            payload["name"],
            metadata=payload["metadata"],
        )
        if event is None:
            self._pending_events.append(payload)

    def _resolve_trace_center(self) -> Any:
        if self.trace_center is not None:
            return self.trace_center
        trace_instance = self._singletons.get("trace_center")
        if trace_instance is not None:
            return trace_instance
        return None

    def _flush_pending_events(self, trace_center: Any) -> None:
        if trace_center is None or not self._pending_events:
            return
        remaining: List[Dict[str, Any]] = []
        for item in list(self._pending_events):
            event = trace_center.record_event(
                "SERVICE_CONTAINER",
                str(item.get("name") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
            if event is None:
                remaining.append(item)
        self._pending_events = remaining
