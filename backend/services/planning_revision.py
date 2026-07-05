from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RevisionReason(str, Enum):
    MISSING_ENTITY = "MissingEntity"
    MISSING_EVIDENCE = "MissingEvidence"
    KNOWLEDGE_GAP = "KnowledgeGap"
    VERIFICATION_FAILED = "VerificationFailed"
    POLICY_RETRY = "PolicyRetry"
    LOOP_CONTINUE = "LoopContinue"


@dataclass(frozen=True)
class PlanningRevision:
    revision_id: str
    reason: str
    created_at: str
    added_tasks: List[Dict[str, Any]] = field(default_factory=list)
    removed_tasks: List[Dict[str, Any]] = field(default_factory=list)
    reprioritized_tasks: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "added_tasks": list(self.added_tasks or []),
            "removed_tasks": list(self.removed_tasks or []),
            "reprioritized_tasks": list(self.reprioritized_tasks or []),
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanningRevision":
        payload = data or {}
        return cls(
            revision_id=str(payload.get("revision_id") or ""),
            reason=str(payload.get("reason") or ""),
            created_at=str(payload.get("created_at") or ""),
            added_tasks=list(payload.get("added_tasks") or []),
            removed_tasks=list(payload.get("removed_tasks") or []),
            reprioritized_tasks=list(payload.get("reprioritized_tasks") or []),
            metadata=dict(payload.get("metadata") or {}),
        )

    @classmethod
    def create(
        cls,
        reason: RevisionReason | str,
        *,
        metadata: Dict[str, Any] | None = None,
    ) -> "PlanningRevision":
        return cls(
            revision_id=uuid.uuid4().hex,
            reason=str(reason.value if isinstance(reason, RevisionReason) else reason or ""),
            created_at=_utc_now_iso(),
            added_tasks=[],
            removed_tasks=[],
            reprioritized_tasks=[],
            metadata=dict(metadata or {}),
        )
