from __future__ import annotations

import contextvars
import hashlib
import json
import time
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.runtime_metrics import get_runtime_metrics


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class TraceEvent:
    id: str
    timestamp: str
    stage: str
    name: str
    status: str
    duration_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "name": self.name,
            "status": self.status,
            "duration_ms": float(self.duration_ms),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceEvent":
        payload = data or {}
        return cls(
            id=str(payload.get("id") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            stage=str(payload.get("stage") or ""),
            name=str(payload.get("name") or ""),
            status=str(payload.get("status") or ""),
            duration_ms=float(payload.get("duration_ms") or 0.0),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class TraceStage:
    stage_name: str
    start_time: str
    end_time: str
    duration_ms: float
    events: List[TraceEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": float(self.duration_ms),
            "events": [item.to_dict() for item in (self.events or [])],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceStage":
        payload = data or {}
        return cls(
            stage_name=str(payload.get("stage_name") or ""),
            start_time=str(payload.get("start_time") or ""),
            end_time=str(payload.get("end_time") or ""),
            duration_ms=float(payload.get("duration_ms") or 0.0),
            events=[TraceEvent.from_dict(item) for item in (payload.get("events") or []) if isinstance(item, dict)],
        )


@dataclass
class TraceSession:
    trace_id: str
    question: str
    pipeline: str
    stages: List[TraceStage] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    total_duration: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "pipeline": self.pipeline,
            "stages": [item.to_dict() for item in (self.stages or [])],
            "summary": dict(self.summary or {}),
            "total_duration": float(self.total_duration),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceSession":
        payload = data or {}
        return cls(
            trace_id=str(payload.get("trace_id") or ""),
            question=str(payload.get("question") or ""),
            pipeline=str(payload.get("pipeline") or ""),
            stages=[TraceStage.from_dict(item) for item in (payload.get("stages") or []) if isinstance(item, dict)],
            summary=dict(payload.get("summary") or {}),
            total_duration=float(payload.get("total_duration") or 0.0),
        )


class TraceCenter:
    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self._session: TraceSession | None = None
        self._session_started_perf: float | None = None
        self._active_stage_perf: Dict[int, float] = {}
        self._active_stage_index: Dict[str, int] = {}
        self._runtime_metrics = get_runtime_metrics()
        self._session_active = False

    def start_session(self, question: str, pipeline: str = "") -> TraceSession | None:
        if not self.enabled:
            return None
        self._session = TraceSession(
            trace_id=uuid.uuid4().hex,
            question=str(question or ""),
            pipeline=str(pipeline or ""),
            stages=[],
            summary={},
            total_duration=0.0,
        )
        self._session_started_perf = time.perf_counter()
        self._session_active = True
        self._runtime_metrics.inc("trace_session_count")
        self._runtime_metrics.session_started()
        return self._session

    def start_stage(self, stage_name: str) -> TraceStage | None:
        if not self.enabled or self._session is None:
            return None
        stage = TraceStage(
            stage_name=str(stage_name or ""),
            start_time=_utc_now_iso(),
            end_time="",
            duration_ms=0.0,
            events=[],
        )
        self._session.stages.append(stage)
        index = len(self._session.stages) - 1
        self._active_stage_index[stage.stage_name] = index
        self._active_stage_perf[index] = time.perf_counter()
        self._runtime_metrics.inc("trace_stage_count", labels={"stage": stage.stage_name})
        return stage

    def end_stage(
        self,
        stage_name: str,
        *,
        status: str = "completed",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or self._session is None:
            return
        index = self._active_stage_index.get(str(stage_name or ""))
        if index is None or index >= len(self._session.stages):
            return
        stage = self._session.stages[index]
        stage.end_time = _utc_now_iso()
        started_perf = self._active_stage_perf.pop(index, None)
        if started_perf is not None:
            stage.duration_ms = round((time.perf_counter() - started_perf) * 1000, 2)
        self._active_stage_index.pop(stage.stage_name, None)
        self._runtime_metrics.observe("pipeline.stage.latency_ms", stage.duration_ms, labels={"stage": stage.stage_name})
        if status or metadata:
            stage.events.append(
                TraceEvent(
                    id=uuid.uuid4().hex,
                    timestamp=_utc_now_iso(),
                    stage=stage.stage_name,
                    name=f"{stage.stage_name} Stage Ended",
                    status=str(status or "completed"),
                    duration_ms=0.0,
                    metadata=dict(metadata or {}),
                )
            )

    def record_event(
        self,
        stage: str,
        name: str,
        *,
        status: str = "ok",
        duration_ms: float = 0.0,
        metadata: Dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        if not self.enabled or self._session is None:
            return None
        stage_name = str(stage or "GENERAL")
        stage_index = self._active_stage_index.get(stage_name)
        if stage_index is None or stage_index >= len(self._session.stages):
            temp_stage = self.start_stage(stage_name)
            if temp_stage is None:
                return None
            stage_index = self._active_stage_index.get(stage_name)
        if stage_index is None or stage_index >= len(self._session.stages):
            return None
        event = TraceEvent(
            id=uuid.uuid4().hex,
            timestamp=_utc_now_iso(),
            stage=stage_name,
            name=str(name or ""),
            status=str(status or "ok"),
            duration_ms=float(duration_ms or 0.0),
            metadata=dict(metadata or {}),
        )
        self._session.stages[stage_index].events.append(event)
        self._runtime_metrics.inc("trace_event_count", labels={"stage": stage_name})
        return event

    def finish_session(
        self,
        *,
        summary: Dict[str, Any] | None = None,
        pipeline: str | None = None,
    ) -> TraceSession | None:
        if not self.enabled or self._session is None:
            return None
        for stage_name in list(self._active_stage_index.keys()):
            self.end_stage(stage_name, status="completed")
        if pipeline:
            self._session.pipeline = str(pipeline or "")
        if self._session_started_perf is not None:
            self._session.total_duration = round((time.perf_counter() - self._session_started_perf) * 1000, 2)
        self._runtime_metrics.observe(
            "pipeline.total.latency_ms",
            self._session.total_duration,
            labels={"pipeline": str(pipeline or self._session.pipeline or "unknown")},
        )
        self._session.summary = dict(summary or {})
        if self._session_active:
            self._runtime_metrics.session_finished()
            self._session_active = False
        return self._session

    def export_trace(self) -> Dict[str, Any]:
        if not self.enabled or self._session is None:
            return {}
        return self._session.to_dict()

    def record_workflow_event(
        self,
        name: str,
        *,
        status: str = "ok",
        duration_ms: float = 0.0,
        metadata: Dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        return self.record_event(
            "WORKFLOW",
            name,
            status=status,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    def start_workflow(self, workflow_name: str, metadata: Dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.start_stage("WORKFLOW")
        self.record_workflow_event(
            "Workflow Started",
            metadata={"workflow_name": str(workflow_name or ""), **dict(metadata or {})},
        )

    def finish_workflow(
        self,
        workflow_name: str,
        *,
        status: str = "completed",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.record_workflow_event(
            "Workflow Finished" if status == "completed" else "Workflow Failed",
            status=status,
            metadata={"workflow_name": str(workflow_name or ""), **dict(metadata or {})},
        )
        self.end_stage("WORKFLOW", status=status, metadata={"workflow_name": str(workflow_name or "")})

    def record_planning_event(
        self,
        name: str,
        *,
        status: str = "ok",
        duration_ms: float = 0.0,
        metadata: Dict[str, Any] | None = None,
    ) -> TraceEvent | None:
        return self.record_event(
            "PLANNING",
            name,
            status=status,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )

    def start_planning(self, metadata: Dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.start_stage("PLANNING")
        self.record_planning_event("Planning Started", metadata=dict(metadata or {}))

    def finish_planning(self, *, status: str = "completed", metadata: Dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.record_planning_event(
            "Planning Finished" if status == "completed" else "Planning Failed",
            status=status,
            metadata=dict(metadata or {}),
        )
        self.end_stage("PLANNING", status=status, metadata=dict(metadata or {}))

    def start_planning_revision(self, metadata: Dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.record_planning_event("Planning Revision Started", metadata=dict(metadata or {}))

    def finish_planning_revision(self, *, status: str = "completed", metadata: Dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.record_planning_event(
            "Planning Revision Finished" if status == "completed" else "Planning Failed",
            status=status,
            metadata=dict(metadata or {}),
        )


_trace_print_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar("trace_print_enabled", default=False)
_trace_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_request_id", default="")


def set_trace_print(*, enabled: bool, request_id: str = "") -> None:
    _trace_print_enabled.set(bool(enabled))
    _trace_request_id.set(str(request_id or ""))


def _obj_count(obj: Any) -> int:
    if obj is None:
        return 0
    if isinstance(obj, (list, tuple, set, dict)):
        return len(obj)
    for attr in ("tasks", "edges", "nodes", "relations", "facts", "evidences", "sections", "messages"):
        if hasattr(obj, attr):
            try:
                value = getattr(obj, attr)
            except Exception:
                continue
            if isinstance(value, (list, tuple, set, dict)):
                return len(value)
    return 1


def _obj_summary(obj: Any) -> Dict[str, Any]:
    return {
        "type": type(obj).__name__ if obj is not None else "None",
        "count": _obj_count(obj),
        "id": hex(id(obj)) if obj is not None else None,
    }


class _TraceSpan:
    def __init__(self, name: str, *, input_obj: Any = None):
        self.name = str(name or "")
        self.input_obj = input_obj
        self.output_obj: Any = None
        self._started: float | None = None

    def set_output_obj(self, output_obj: Any) -> None:
        self.output_obj = output_obj

    def __enter__(self) -> "_TraceSpan":
        self._started = time.perf_counter()
        if bool(_trace_print_enabled.get()):
            rid = _trace_request_id.get()
            payload = {"request_id": rid, "module": self.name, "input": _obj_summary(self.input_obj)}
            print(f"ENTER {self.name} {payload}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        elapsed = round((time.perf_counter() - (self._started or time.perf_counter())) * 1000, 2)
        if bool(_trace_print_enabled.get()):
            rid = _trace_request_id.get()
            payload = {"request_id": rid, "module": self.name, "elapsed_ms": elapsed, "output": _obj_summary(self.output_obj)}
            print(f"EXIT {self.name} {payload}")


@contextmanager
def trace_span(name: str, *, input_obj: Any = None):
    span = _TraceSpan(name, input_obj=input_obj)
    try:
        yield span.__enter__()
    finally:
        span.__exit__(None, None, None)


# #region debug-point A:single-answer-source-helper
_debug_server_url_cache: str | None = None
_debug_session_id_cache: str | None = None


def _debug_server_config() -> tuple[str, str]:
    global _debug_server_url_cache, _debug_session_id_cache
    if _debug_server_url_cache and _debug_session_id_cache:
        return _debug_server_url_cache, _debug_session_id_cache
    url = "http://127.0.0.1:7777/event"
    session_id = "single-answer-source"
    try:
        with open(".dbg/single-answer-source.env", "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = str(raw_line or "").strip()
                if line.startswith("DEBUG_SERVER_URL="):
                    url = line.split("=", 1)[1] or url
                elif line.startswith("DEBUG_SESSION_ID="):
                    session_id = line.split("=", 1)[1] or session_id
    except Exception:
        pass
    _debug_server_url_cache = url
    _debug_session_id_cache = session_id
    return url, session_id


def debug_answer_event(
    stage: str,
    answer: Any,
    *,
    trace_id: str = "",
    run_id: str = "pre",
    hypothesis_id: str = "A",
    location: str = "",
    extra: Dict[str, Any] | None = None,
) -> None:
    url, session_id = _debug_server_config()
    text = "" if answer is None else str(answer)
    payload = {
        "sessionId": session_id,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "traceId": str(trace_id or ""),
        "location": location or stage,
        "msg": f"[DEBUG] {stage}",
        "data": {
            "stage": stage,
            "answer_object_id": None if answer is None else hex(id(answer)),
            "answer_type": type(answer).__name__ if answer is not None else "None",
            "answer_length": len(text),
            "answer_md5": hashlib.md5(text.encode("utf-8")).hexdigest(),
            "answer_preview": text[:200],
            **dict(extra or {}),
        },
        "ts": int(time.time() * 1000),
    }
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            ),
            timeout=2,
        ).read()
    except Exception:
        pass
# #endregion
