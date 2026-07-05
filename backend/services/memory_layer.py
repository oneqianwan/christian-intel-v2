from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from services.core_models import Requirement
from services.execution_policy import ExecutionPolicyContext, ExecutionPolicyEngine
from services.knowledge_layer import KnowledgeGraph, KnowledgeNode, KnowledgeRelation
from services.runtime_metrics import get_runtime_metrics


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_entity_id(entity_name: str, entity_type: str) -> str:
    raw = f"{str(entity_type or '').strip().lower()}::{str(entity_name or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass
class KnowledgeSnapshot:
    snapshot_id: str
    knowledge_graph: KnowledgeGraph
    reason: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "knowledge_graph": self.knowledge_graph.to_dict(),
            "reason": self.reason,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeSnapshot":
        payload = data or {}
        return cls(
            snapshot_id=str(payload.get("snapshot_id") or ""),
            knowledge_graph=KnowledgeGraph.from_dict(payload.get("knowledge_graph") or {}),
            reason=str(payload.get("reason") or ""),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass
class SessionMemory:
    conversation_id: str
    question_history: List[str] = field(default_factory=list)
    entity_history: List[Dict[str, Any]] = field(default_factory=list)
    country_history: List[str] = field(default_factory=list)
    topic_history: List[str] = field(default_factory=list)
    requirement_history: List[Dict[str, Any]] = field(default_factory=list)
    knowledge_snapshots: List[KnowledgeSnapshot] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversation_id": self.conversation_id,
            "question_history": list(self.question_history or []),
            "entity_history": list(self.entity_history or []),
            "country_history": list(self.country_history or []),
            "topic_history": list(self.topic_history or []),
            "requirement_history": list(self.requirement_history or []),
            "knowledge_snapshots": [item.to_dict() for item in (self.knowledge_snapshots or [])],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionMemory":
        payload = data or {}
        return cls(
            conversation_id=str(payload.get("conversation_id") or ""),
            question_history=list(payload.get("question_history") or []),
            entity_history=list(payload.get("entity_history") or []),
            country_history=list(payload.get("country_history") or []),
            topic_history=list(payload.get("topic_history") or []),
            requirement_history=list(payload.get("requirement_history") or []),
            knowledge_snapshots=[KnowledgeSnapshot.from_dict(item) for item in (payload.get("knowledge_snapshots") or []) if isinstance(item, dict)],
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
        )


@dataclass
class EntityMemory:
    entity_id: str
    entity_name: str
    entity_type: str
    aliases: List[str] = field(default_factory=list)
    known_properties: Dict[str, Any] = field(default_factory=dict)
    known_relations: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "aliases": list(self.aliases or []),
            "known_properties": dict(self.known_properties or {}),
            "known_relations": list(self.known_relations or []),
            "confidence": float(self.confidence),
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntityMemory":
        payload = data or {}
        return cls(
            entity_id=str(payload.get("entity_id") or ""),
            entity_name=str(payload.get("entity_name") or ""),
            entity_type=str(payload.get("entity_type") or ""),
            aliases=list(payload.get("aliases") or []),
            known_properties=dict(payload.get("known_properties") or {}),
            known_relations=list(payload.get("known_relations") or []),
            confidence=float(payload.get("confidence") or 0.0),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
        )


@dataclass
class RetrievalCache:
    query_hash: str
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)
    ttl: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_hash": self.query_hash,
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments or {}),
            "tool_results": copy.deepcopy(self.tool_results or {}),
            "created_at": self.created_at,
            "ttl": int(self.ttl or 0),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetrievalCache":
        payload = data or {}
        return cls(
            query_hash=str(payload.get("query_hash") or ""),
            tool_name=str(payload.get("tool_name") or ""),
            arguments=dict(payload.get("arguments") or {}),
            tool_results=copy.deepcopy(payload.get("tool_results") or {}),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            ttl=int(payload.get("ttl") or 300),
        )


@dataclass
class MemoryContext:
    session_memory: SessionMemory
    entity_memories: List[EntityMemory] = field(default_factory=list)
    retrieval_cache: List[RetrievalCache] = field(default_factory=list)
    knowledge_snapshots: List[KnowledgeSnapshot] = field(default_factory=list)
    current_entities: List[Dict[str, Any]] = field(default_factory=list)
    current_requirement: Requirement | None = None
    current_country: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_memory": self.session_memory.to_dict(),
            "entity_memories": [item.to_dict() for item in (self.entity_memories or [])],
            "retrieval_cache": [item.to_dict() for item in (self.retrieval_cache or [])],
            "knowledge_snapshots": [item.to_dict() for item in (self.knowledge_snapshots or [])],
            "current_entities": list(self.current_entities or []),
            "current_requirement": self.current_requirement.to_dict() if self.current_requirement else None,
            "current_country": self.current_country,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryContext":
        payload = data or {}
        session_payload = payload.get("session_memory") if isinstance(payload.get("session_memory"), dict) else {}
        requirement_payload = payload.get("current_requirement") if isinstance(payload.get("current_requirement"), dict) else None
        return cls(
            session_memory=SessionMemory.from_dict(session_payload),
            entity_memories=[EntityMemory.from_dict(item) for item in (payload.get("entity_memories") or []) if isinstance(item, dict)],
            retrieval_cache=[RetrievalCache.from_dict(item) for item in (payload.get("retrieval_cache") or []) if isinstance(item, dict)],
            knowledge_snapshots=[KnowledgeSnapshot.from_dict(item) for item in (payload.get("knowledge_snapshots") or []) if isinstance(item, dict)],
            current_entities=list(payload.get("current_entities") or []),
            current_requirement=Requirement.from_dict(requirement_payload) if requirement_payload else None,
            current_country=str(payload.get("current_country") or ""),
        )


class MemoryLayer:
    _session_store: Dict[str, SessionMemory] = {}
    _entity_store: Dict[str, EntityMemory] = {}
    _retrieval_cache_store: Dict[str, List[RetrievalCache]] = {}

    def __init__(self, trace_center: Any = None):
        self.trace_center = trace_center
        self.runtime_metrics = get_runtime_metrics()

    def load_memory(
        self,
        conversation_id: str,
        *,
        current_entities: List[Dict[str, Any]] | None = None,
        current_requirement: Requirement | None = None,
        current_country: str = "",
    ) -> MemoryContext:
        session = self._session_store.get(conversation_id)
        if session is None:
            session = SessionMemory(conversation_id=str(conversation_id or "default"))
            self._session_store[conversation_id] = session
        retrieval_cache = self._valid_cache_entries(conversation_id)
        entity_memories = self._load_entity_memories(current_entities or [], session)
        context = MemoryContext(
            session_memory=SessionMemory.from_dict(session.to_dict()),
            entity_memories=entity_memories,
            retrieval_cache=[RetrievalCache.from_dict(item.to_dict()) for item in retrieval_cache],
            knowledge_snapshots=[KnowledgeSnapshot.from_dict(item.to_dict()) for item in (session.knowledge_snapshots or [])],
            current_entities=list(current_entities or []),
            current_requirement=current_requirement,
            current_country=str(current_country or ""),
        )
        self._trace(
            "MEMORY_LOAD",
            "Memory Loaded",
            metadata={
                "conversation_id": conversation_id,
                "question_history_count": len(session.question_history or []),
                "snapshot_count": len(session.knowledge_snapshots or []),
                "cache_count": len(retrieval_cache or []),
            },
        )
        if entity_memories:
            self._trace(
                "MEMORY_LOAD",
                "Entity Restored",
                metadata={
                    "entity_count": len(entity_memories or []),
                    "entities": [item.entity_name for item in entity_memories[:5]],
                },
            )
        self.runtime_metrics.set("memory_session_count", float(len(self._session_store)))
        return context

    def update_session(
        self,
        memory_context: MemoryContext,
        *,
        question: str,
        entities: List[Dict[str, Any]] | None = None,
        country: str = "",
        requirement: Requirement | None = None,
        knowledge_graph: KnowledgeGraph | None = None,
    ) -> MemoryContext:
        session = self._get_live_session(memory_context)
        if str(question or "").strip():
            session.question_history.append(str(question or "").strip())
        for entity in entities or []:
            if isinstance(entity, dict) and (entity.get("name") or "").strip():
                session.entity_history.append(dict(entity))
        if str(country or "").strip():
            session.country_history.append(str(country or "").strip())
        topic = self._derive_topic(requirement, knowledge_graph)
        if topic:
            session.topic_history.append(topic)
        if requirement is not None:
            session.requirement_history.append(requirement.to_dict())
        session.question_history = session.question_history[-30:]
        session.entity_history = session.entity_history[-50:]
        session.country_history = self._dedupe_list(session.country_history[-20:])
        session.topic_history = self._dedupe_list(session.topic_history[-20:])
        session.requirement_history = session.requirement_history[-20:]
        session.updated_at = _utc_now_iso()
        self._session_store[session.conversation_id] = session
        memory_context.session_memory = SessionMemory.from_dict(session.to_dict())
        memory_context.current_entities = list(entities or memory_context.current_entities or [])
        memory_context.current_requirement = requirement or memory_context.current_requirement
        memory_context.current_country = str(country or memory_context.current_country or "")
        self._trace(
            "MEMORY_UPDATE",
            "Session Updated",
            metadata={
                "conversation_id": session.conversation_id,
                "question_history_count": len(session.question_history or []),
                "entity_history_count": len(session.entity_history or []),
                "country_history_count": len(session.country_history or []),
            },
        )
        return memory_context

    def update_entities(self, memory_context: MemoryContext, knowledge_graph: KnowledgeGraph | None) -> MemoryContext:
        if knowledge_graph is None:
            return memory_context
        live_entity_memories: List[EntityMemory] = []
        for node in knowledge_graph.nodes or []:
            node_type = str(node.type or "").strip().lower()
            if node_type not in {"organization", "person", "country", "entity"}:
                continue
            entity_id = _stable_entity_id(node.name, node.type)
            existing = self._entity_store.get(entity_id)
            relations = self._relations_for_node(node, knowledge_graph.relations or [])
            aliases = []
            if existing is not None:
                aliases.extend(existing.aliases or [])
                aliases.append(existing.entity_name)
            aliases.append(node.name)
            merged = EntityMemory(
                entity_id=entity_id,
                entity_name=node.name,
                entity_type=node.type,
                aliases=self._dedupe_list([item for item in aliases if str(item or "").strip()]),
                known_properties=self._merge_properties(
                    existing.known_properties if existing else {},
                    node.properties or {},
                ),
                known_relations=self._merge_relation_dicts(existing.known_relations if existing else [], relations),
                confidence=max(float(existing.confidence or 0.0), float(node.confidence or 0.0)) if existing else float(node.confidence or 0.0),
                updated_at=node.updated_at or _utc_now_iso(),
            )
            self._entity_store[entity_id] = merged
            live_entity_memories.append(EntityMemory.from_dict(merged.to_dict()))
        memory_context.entity_memories = live_entity_memories or memory_context.entity_memories
        return memory_context

    def cache_tool_results(
        self,
        memory_context: MemoryContext,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        tool_results: Dict[str, Any],
        ttl: int = 300,
    ) -> RetrievalCache:
        decision = self._get_execution_policy_engine().evaluate_cache(
            ExecutionPolicyContext(
                question_type="CACHE",
                memory={
                    "operation": "write",
                    "conversation_id": memory_context.session_memory.conversation_id,
                },
                trace={"operation": "write", "tool_name": str(tool_name or "")},
            ),
            default_decision=True,
        )
        session = self._get_live_session(memory_context)
        query_hash = self._build_query_hash(tool_name, arguments)
        cache_entry = RetrievalCache(
            query_hash=query_hash,
            tool_name=str(tool_name or ""),
            arguments=dict(arguments or {}),
            tool_results=copy.deepcopy(tool_results or {}),
            created_at=_utc_now_iso(),
            ttl=int(ttl or 300),
        )
        if not bool(decision.decision):
            return cache_entry
        entries = self._valid_cache_entries(session.conversation_id)
        entries = [item for item in entries if item.query_hash != query_hash]
        entries.append(cache_entry)
        self._retrieval_cache_store[session.conversation_id] = entries[-100:]
        memory_context.retrieval_cache = [RetrievalCache.from_dict(item.to_dict()) for item in self._retrieval_cache_store[session.conversation_id]]
        return cache_entry

    def restore_knowledge(self, memory_context: MemoryContext) -> KnowledgeGraph:
        snapshots = list(memory_context.knowledge_snapshots or [])
        if not snapshots and memory_context.session_memory.knowledge_snapshots:
            snapshots = list(memory_context.session_memory.knowledge_snapshots or [])
        decision = self._get_execution_policy_engine().evaluate_memory(
            ExecutionPolicyContext(
                question_type="MEMORY",
                memory={
                    "operation": "restore",
                    "snapshot_count": len(snapshots or []),
                    "conversation_id": memory_context.session_memory.conversation_id,
                },
            ),
            default_decision=bool(snapshots),
        )
        if not bool(decision.decision):
            return KnowledgeGraph()
        latest = snapshots[-1]
        return KnowledgeGraph.from_dict(latest.knowledge_graph.to_dict())

    def create_snapshot(
        self,
        memory_context: MemoryContext,
        knowledge_graph: KnowledgeGraph,
        *,
        reason: str,
    ) -> KnowledgeSnapshot:
        decision = self._get_execution_policy_engine().evaluate_memory(
            ExecutionPolicyContext(
                question_type="MEMORY",
                memory={
                    "operation": "snapshot",
                    "conversation_id": memory_context.session_memory.conversation_id,
                },
                knowledge={
                    "operation": "snapshot",
                    "node_count": len(knowledge_graph.nodes or []),
                    "relation_count": len(knowledge_graph.relations or []),
                },
            ),
            default_decision=True,
        )
        snapshot = KnowledgeSnapshot(
            snapshot_id=uuid.uuid4().hex,
            knowledge_graph=KnowledgeGraph.from_dict(knowledge_graph.to_dict()),
            reason=str(reason or ""),
            created_at=_utc_now_iso(),
        )
        if not bool(decision.decision):
            return snapshot
        session = self._get_live_session(memory_context)
        session.knowledge_snapshots.append(snapshot)
        session.knowledge_snapshots = session.knowledge_snapshots[-10:]
        session.updated_at = _utc_now_iso()
        self._session_store[session.conversation_id] = session
        memory_context.knowledge_snapshots = [KnowledgeSnapshot.from_dict(item.to_dict()) for item in (session.knowledge_snapshots or [])]
        memory_context.session_memory = SessionMemory.from_dict(session.to_dict())
        self._trace(
            "MEMORY_SNAPSHOT",
            "Knowledge Snapshot Created",
            metadata={
                "conversation_id": session.conversation_id,
                "snapshot_id": snapshot.snapshot_id,
                "reason": snapshot.reason,
                "node_count": len(knowledge_graph.nodes or []),
                "relation_count": len(knowledge_graph.relations or []),
            },
        )
        self.runtime_metrics.inc("memory_snapshot_count")
        return snapshot

    def export_memory(self, memory_context: MemoryContext) -> Dict[str, Any]:
        payload = memory_context.to_dict()
        self._trace(
            "MEMORY_SNAPSHOT",
            "Memory Exported",
            metadata={
                "conversation_id": memory_context.session_memory.conversation_id,
                "snapshot_count": len(memory_context.knowledge_snapshots or []),
                "cache_count": len(memory_context.retrieval_cache or []),
            },
        )
        return payload

    def get_cached_tool_result(
        self,
        memory_context: MemoryContext,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        query_hash = self._build_query_hash(tool_name, arguments)
        cache_entries = self._valid_cache_entries(memory_context.session_memory.conversation_id)
        cache_hit = any(item.query_hash == query_hash for item in cache_entries)
        decision = self._get_execution_policy_engine().evaluate_cache(
            ExecutionPolicyContext(
                question_type="CACHE",
                memory={
                    "operation": "read",
                    "cache_hit": cache_hit,
                    "conversation_id": memory_context.session_memory.conversation_id,
                },
                trace={"operation": "read", "tool_name": str(tool_name or "")},
            ),
            default_decision=cache_hit,
        )
        if not bool(decision.decision):
            self.runtime_metrics.inc("memory_cache_miss", labels={"tool_name": str(tool_name or ""), "reason": "policy_reject"})
            return None
        for item in cache_entries:
            if item.query_hash == query_hash:
                self.runtime_metrics.inc("memory_cache_hit", labels={"tool_name": str(tool_name or "")})
                self._trace(
                    "RETRIEVAL",
                    "Retrieval Cache Hit",
                    metadata={"tool_name": tool_name, "query_hash": query_hash},
                )
                return copy.deepcopy(item.tool_results or {})
        self.runtime_metrics.inc("memory_cache_miss", labels={"tool_name": str(tool_name or ""), "reason": "not_found"})
        return None

    def _get_live_session(self, memory_context: MemoryContext) -> SessionMemory:
        conversation_id = memory_context.session_memory.conversation_id
        live = self._session_store.get(conversation_id)
        if live is None:
            live = SessionMemory.from_dict(memory_context.session_memory.to_dict())
            self._session_store[conversation_id] = live
        return live

    def _valid_cache_entries(self, conversation_id: str) -> List[RetrievalCache]:
        now = datetime.now(timezone.utc)
        valid: List[RetrievalCache] = []
        for item in self._retrieval_cache_store.get(conversation_id, []):
            created = self._parse_time(item.created_at)
            expires_at = datetime.fromtimestamp(created, tz=timezone.utc) + timedelta(seconds=int(item.ttl or 0))
            if expires_at >= now:
                valid.append(item)
        self._retrieval_cache_store[conversation_id] = valid
        return valid

    def _load_entity_memories(self, current_entities: List[Dict[str, Any]], session: SessionMemory) -> List[EntityMemory]:
        candidates: List[EntityMemory] = []
        names: List[tuple[str, str]] = []
        for entity in current_entities or []:
            if isinstance(entity, dict) and (entity.get("name") or "").strip():
                names.append((str(entity.get("name") or ""), str(entity.get("type") or "entity")))
        for entity in (session.entity_history or [])[-10:]:
            if isinstance(entity, dict) and (entity.get("name") or "").strip():
                names.append((str(entity.get("name") or ""), str(entity.get("type") or "entity")))
        seen = set()
        for entity_name, entity_type in names:
            entity_id = _stable_entity_id(entity_name, entity_type)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            stored = self._entity_store.get(entity_id)
            if stored is not None:
                candidates.append(EntityMemory.from_dict(stored.to_dict()))
        return candidates

    def _relations_for_node(self, node: KnowledgeNode, relations: List[KnowledgeRelation]) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        for relation in relations or []:
            if relation.source_node != node.id and relation.target_node != node.id:
                continue
            collected.append(relation.to_dict())
        return collected

    def _merge_properties(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(left or {})
        for key, value in (right or {}).items():
            if value in (None, "", [], {}):
                continue
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
        return merged

    def _merge_relation_dicts(self, left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for item in list(left or []) + list(right or []):
            if not isinstance(item, dict):
                continue
            relation_id = str(item.get("id") or "").strip() or hashlib.sha1(
                json.dumps(item, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            merged[relation_id] = dict(item)
        return list(merged.values())

    def _derive_topic(self, requirement: Requirement | None, knowledge_graph: KnowledgeGraph | None) -> str:
        if requirement is not None and requirement.required_fields:
            return ",".join(list(requirement.required_fields or [])[:3])
        if knowledge_graph is not None and knowledge_graph.nodes:
            return str(knowledge_graph.nodes[0].type or "")
        return ""

    def _build_query_hash(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        payload = {
            "tool_name": str(tool_name or ""),
            "arguments": dict(arguments or {}),
        }
        return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def _parse_time(self, value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

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

    def _get_execution_policy_engine(self) -> ExecutionPolicyEngine:
        return ExecutionPolicyEngine(trace_center=self.trace_center)

    def _trace(self, stage: str, event_name: str, metadata: Dict[str, Any] | None = None) -> None:
        if self.trace_center is None:
            return
        self.trace_center.record_event(stage, event_name, metadata=metadata or {})
