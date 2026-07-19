from __future__ import annotations

import json
import uuid

from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from models.watch_alert import Alert, Signal
from services.alert_rule_service import (
    ensure_default_alert_rules,
    get_applicable_alert_rule,
    notifications_enabled,
    severity_meets_minimum,
)
from services.watch_alert_ownership import ownership_enabled


@dataclass
class AlertProcessingResult:
    created_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    created_alert_ids: list[str] = field(default_factory=list)
    failed_signal_ids: list[str] = field(default_factory=list)


def _normalize_source_url(source_url: str | None) -> str | None:
    candidate = str(source_url or "").strip()
    if candidate.startswith(("http://", "https://")):
        return candidate
    return None


def _load_signal(db: Session, signal_id: str) -> Signal | None:
    return (
        db.query(Signal)
        .options(joinedload(Signal.watch_target))
        .filter(Signal.id == signal_id)
        .first()
    )


def _watch_target_tenant_id(signal: Signal) -> str | None:
    watch_target = getattr(signal, "watch_target", None)
    tenant_id = str(getattr(watch_target, "tenant_id", "") or "").strip()
    return tenant_id or None


def process_signal(db: Session, signal_id: str) -> Alert | None:
    if not notifications_enabled():
        return None

    ensure_default_alert_rules(db)

    signal = _load_signal(db, signal_id)
    if signal is None or signal.watch_target is None:
        return None
    watch_target_tenant_id = _watch_target_tenant_id(signal)
    if watch_target_tenant_id is None:
        return None
    signal_tenant_id = str(getattr(signal, "tenant_id", "") or "").strip()
    if signal_tenant_id and signal_tenant_id != watch_target_tenant_id:
        return None
    signal.tenant_id = watch_target_tenant_id

    if ownership_enabled():
        user_id = str(signal.owner_user_id or signal.watch_target.owner_user_id or "").strip()
        if not user_id:
            print(
                json.dumps(
                    {
                        "event": "alert_engine_owner_missing",
                        "signal_id": signal_id,
                        "watch_target_id": signal.watch_target_id,
                    },
                    ensure_ascii=False,
                )
            )
            return None
    else:
        user_id = str(signal.watch_target.user_id or "").strip()
        if not user_id:
            return None

    rule = get_applicable_alert_rule(
        db,
        user_id=user_id,
        signal_type=signal.signal_type,
        tenant_id=watch_target_tenant_id,
    )
    if rule is None or not rule.is_enabled:
        return None
    rule_tenant_id = str(getattr(rule, "tenant_id", "") or "").strip()
    if rule_tenant_id and rule_tenant_id != watch_target_tenant_id:
        return None
    if not severity_meets_minimum(signal.severity, rule.minimum_severity):
        return None

    alert = Alert(
        id=str(uuid.uuid4()),
        tenant_id=watch_target_tenant_id,
        user_id=user_id,
        owner_user_id=user_id if ownership_enabled() else None,
        watch_target_id=signal.watch_target_id,
        signal_id=signal.id,
        title=signal.title,
        summary=signal.summary,
        severity=signal.severity,
        source_url=_normalize_source_url(signal.source_url),
        status="unread",
    )
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
    except IntegrityError:
        return None
    return alert


def process_signals(db: Session, signal_ids: list[str]) -> AlertProcessingResult:
    result = AlertProcessingResult()
    if not notifications_enabled():
        result.skipped_count = len(signal_ids)
        return result

    ensure_default_alert_rules(db)

    for signal_id in list(dict.fromkeys(signal_ids)):
        try:
            alert = process_signal(db, signal_id)
        except Exception as exc:
            result.failed_count += 1
            result.failed_signal_ids.append(signal_id)
            print(
                json.dumps(
                    {
                        "event": "alert_engine_process_signal_failed",
                        "signal_id": signal_id,
                        "error": str(exc)[:300],
                    },
                    ensure_ascii=False,
                )
            )
            continue

        if alert is None:
            result.skipped_count += 1
            continue

        result.created_count += 1
        result.created_alert_ids.append(alert.id)

    return result
