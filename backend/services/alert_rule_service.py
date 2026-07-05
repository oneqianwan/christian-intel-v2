from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from models.watch_alert import AlertRule

SEVERITY_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

DEFAULT_ALERT_RULES = {
    "leadership_change": "high",
    "score_change": "medium",
    "contact_change": "medium",
    "website_change": "medium",
    "relation_change": "medium",
    "new_news": "low",
    "new_video": "low",
    "new_intelligence": "low",
}


def notifications_enabled() -> bool:
    return settings.feature_flag("WATCH_ALERT_V1_ENABLED") and settings.feature_flag("WATCH_ALERT_NOTIFICATIONS_ENABLED")


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(str(severity or "").strip().lower(), -1)


def severity_meets_minimum(signal_severity: str, minimum_severity: str) -> bool:
    return severity_rank(signal_severity) >= severity_rank(minimum_severity)


def ensure_default_alert_rules(db: Session) -> list[AlertRule]:
    existing_rules = {
        rule.signal_type: rule
        for rule in db.query(AlertRule)
        .filter(
            AlertRule.user_id.is_(None),
            AlertRule.signal_type.in_(tuple(DEFAULT_ALERT_RULES.keys())),
        )
        .all()
    }

    for signal_type, minimum_severity in DEFAULT_ALERT_RULES.items():
        if signal_type in existing_rules:
            continue
        rule = AlertRule(
            id=str(uuid.uuid4()),
            user_id=None,
            signal_type=signal_type,
            minimum_severity=minimum_severity,
            is_enabled=True,
            configuration_json={},
        )
        try:
            with db.begin_nested():
                db.add(rule)
                db.flush()
        except IntegrityError:
            continue

    return (
        db.query(AlertRule)
        .filter(
            AlertRule.user_id.is_(None),
            AlertRule.signal_type.in_(tuple(DEFAULT_ALERT_RULES.keys())),
        )
        .all()
    )


def get_applicable_alert_rule(db: Session, *, user_id: str, signal_type: str) -> AlertRule | None:
    user_rule = (
        db.query(AlertRule)
        .filter(
            AlertRule.user_id == user_id,
            AlertRule.signal_type == signal_type,
        )
        .first()
    )
    if user_rule is not None:
        return user_rule

    return (
        db.query(AlertRule)
        .filter(
            AlertRule.user_id.is_(None),
            AlertRule.signal_type == signal_type,
        )
        .first()
    )
