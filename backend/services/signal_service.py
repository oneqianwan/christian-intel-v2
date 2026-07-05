from __future__ import annotations

import uuid

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models.watch_alert import Signal, WatchTarget


SIGNAL_SEVERITY = {
    "leadership_change": "high",
    "contact_change": "medium",
    "relation_change": "medium",
    "new_news": "low",
    "new_video": "low",
    "new_intelligence": "low",
    "website_change": "medium",
}


def _normalize_for_key(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or "null"
    return str(value)


def _severity_for_change(change: dict) -> str:
    if change["signal_type"] != "score_change":
        return SIGNAL_SEVERITY[change["signal_type"]]
    old_value = change.get("old_value")
    new_value = change.get("new_value")
    if old_value is None or new_value is None:
        return "medium"
    return "high" if new_value < old_value else "medium"


def _source_url_for_change(change: dict, current_snapshot: dict) -> str | None:
    candidate = change.get("new_value") if isinstance(change.get("new_value"), str) else None
    if candidate and candidate.startswith(("http://", "https://")):
        return candidate
    website = ((current_snapshot.get("fields") or {}).get("official_website") or "").strip()
    if website.startswith(("http://", "https://")):
        return website
    return None


def _title_and_summary(change: dict) -> tuple[str, str]:
    signal_type = change["signal_type"]
    field_name = change.get("field_name")
    old_value = change.get("old_value")
    new_value = change.get("new_value")

    if signal_type == "leadership_change":
        return (
            "Leadership changed",
            f"leader_name changed from {old_value!r} to {new_value!r}",
        )
    if signal_type == "contact_change":
        return (
            f"Contact changed: {field_name}",
            f"{field_name} changed from {old_value!r} to {new_value!r}",
        )
    if signal_type == "score_change":
        return (
            f"Score changed: {field_name}",
            f"{field_name} changed from {old_value!r} to {new_value!r}",
        )
    if signal_type == "new_intelligence":
        return ("New intelligence detected", f"New intelligence item detected: {new_value}")
    if signal_type == "new_news":
        return ("New news detected", f"New news URL detected: {new_value}")
    if signal_type == "new_video":
        return ("New video detected", f"New video URL detected: {new_value}")
    if signal_type == "relation_change":
        return ("Relation changed", f"New relation detected: {new_value}")
    return ("Website changed", "Website content changed")


def _dedup_key(watch_target: WatchTarget, change: dict) -> str:
    signal_type = change["signal_type"]
    if signal_type in {"new_intelligence", "new_news", "new_video"}:
        identity = _normalize_for_key(change.get("new_value"))
        return f"{watch_target.id}|{signal_type}|{identity}"
    field_name = _normalize_for_key(change.get("field_name"))
    normalized_value = _normalize_for_key(change.get("new_value"))
    return f"{watch_target.id}|{signal_type}|{field_name}|{normalized_value}"


def create_signals_for_changes(
    db: Session,
    watch_target: WatchTarget,
    current_snapshot: dict,
    changes: list[dict],
) -> int:
    created = 0
    for change in changes:
        dedup_key = _dedup_key(watch_target, change)
        title, summary = _title_and_summary(change)
        signal = Signal(
            id=str(uuid.uuid4()),
            watch_target_id=watch_target.id,
            entity_id=watch_target.entity_id,
            signal_type=change["signal_type"],
            title=title,
            summary=summary,
            severity=_severity_for_change(change),
            evidence_id=_normalize_for_key(change.get("new_value")) if change["signal_type"] == "new_intelligence" else None,
            source_url=_source_url_for_change(change, current_snapshot),
            old_value_json={"value": change.get("old_value"), "field": change.get("field_name")},
            new_value_json={"value": change.get("new_value"), "field": change.get("field_name")},
            detected_at=datetime.utcnow(),
            dedup_key=dedup_key,
            metadata_json={
                "field_name": change.get("field_name"),
                "snapshot_version": current_snapshot.get("snapshot_version"),
            },
        )
        try:
            with db.begin_nested():
                db.add(signal)
                db.flush()
                created += 1
        except IntegrityError:
            continue
    return created


def list_signals_for_watch_target(
    db: Session,
    watch_target_id: str,
    *,
    signal_type: str | None,
    severity: str | None,
    page: int,
    page_size: int,
):
    query = db.query(Signal).filter(Signal.watch_target_id == watch_target_id)
    if signal_type:
        query = query.filter(Signal.signal_type == signal_type)
    if severity:
        query = query.filter(Signal.severity == severity)
    total = query.count()
    items = (
        query.order_by(Signal.detected_at.desc(), Signal.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total
