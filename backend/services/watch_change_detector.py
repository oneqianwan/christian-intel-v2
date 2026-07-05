from __future__ import annotations

from typing import Any


def _normalize_scalar(value: Any):
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return value


def _changed(old_value: Any, new_value: Any) -> bool:
    old_normalized = _normalize_scalar(old_value)
    new_normalized = _normalize_scalar(new_value)
    if old_normalized is None and new_normalized is None:
        return False
    return old_normalized != new_normalized


def _iter_new_entries(current_values, previous_values):
    previous = set(previous_values or [])
    current = list(current_values or [])
    for value in current:
        if value not in previous:
            yield value


def detect_watch_changes(previous_snapshot: dict | None, current_snapshot: dict) -> list[dict]:
    if not previous_snapshot:
        return []

    previous_fields = (previous_snapshot or {}).get("fields") or {}
    current_fields = (current_snapshot or {}).get("fields") or {}

    changes: list[dict] = []

    if _changed(previous_fields.get("leader_name"), current_fields.get("leader_name")):
        changes.append(
            {
                "signal_type": "leadership_change",
                "field_name": "leader_name",
                "old_value": previous_fields.get("leader_name"),
                "new_value": current_fields.get("leader_name"),
            }
        )

    for field_name in ["email", "phone", "official_website"]:
        if _changed(previous_fields.get(field_name), current_fields.get(field_name)):
            changes.append(
                {
                    "signal_type": "contact_change",
                    "field_name": field_name,
                    "old_value": previous_fields.get(field_name),
                    "new_value": current_fields.get(field_name),
                }
            )

    score_fields_changed = []
    for field_name in ["people_score", "digital_score", "intel_score"]:
        if _changed(previous_fields.get(field_name), current_fields.get(field_name)):
            score_fields_changed.append(field_name)
            changes.append(
                {
                    "signal_type": "score_change",
                    "field_name": field_name,
                    "old_value": previous_fields.get(field_name),
                    "new_value": current_fields.get(field_name),
                }
            )

    if not score_fields_changed and _changed(previous_fields.get("composite_score"), current_fields.get("composite_score")):
        changes.append(
            {
                "signal_type": "score_change",
                "field_name": "composite_score",
                "old_value": previous_fields.get("composite_score"),
                "new_value": current_fields.get("composite_score"),
            }
        )

    for intelligence_id in _iter_new_entries(
        current_snapshot.get("intelligence_ids"),
        previous_snapshot.get("intelligence_ids"),
    ):
        changes.append(
            {
                "signal_type": "new_intelligence",
                "field_name": "intelligence_id",
                "old_value": None,
                "new_value": intelligence_id,
            }
        )

    for news_url in _iter_new_entries(
        current_snapshot.get("news_urls"),
        previous_snapshot.get("news_urls"),
    ):
        changes.append(
            {
                "signal_type": "new_news",
                "field_name": "news_url",
                "old_value": None,
                "new_value": news_url,
            }
        )

    for video_url in _iter_new_entries(
        current_snapshot.get("video_urls"),
        previous_snapshot.get("video_urls"),
    ):
        changes.append(
            {
                "signal_type": "new_video",
                "field_name": "video_url",
                "old_value": None,
                "new_value": video_url,
            }
        )

    for relation_key in _iter_new_entries(
        current_snapshot.get("relation_keys"),
        previous_snapshot.get("relation_keys"),
    ):
        changes.append(
            {
                "signal_type": "relation_change",
                "field_name": "relation_key",
                "old_value": None,
                "new_value": relation_key,
            }
        )

    previous_website_hash = previous_snapshot.get("website_hash")
    current_website_hash = current_snapshot.get("website_hash")
    if previous_website_hash and current_website_hash and previous_website_hash != current_website_hash:
        changes.append(
            {
                "signal_type": "website_change",
                "field_name": "website_hash",
                "old_value": previous_website_hash,
                "new_value": current_website_hash,
            }
        )

    return changes
