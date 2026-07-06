import uuid

from datetime import datetime
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from models.database import Base


class WatchTarget(Base):
    __tablename__ = "watch_targets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'paused', 'disabled')",
            name="ck_watch_targets_status",
        ),
        CheckConstraint(
            "frequency IN ('daily', 'weekly', 'manual')",
            name="ck_watch_targets_frequency",
        ),
        Index("ix_watch_targets_entity_id", "entity_id"),
        Index("ix_watch_targets_status_next_check_at", "status", "next_check_at"),
        Index("ix_watch_targets_user_id", "user_id"),
        Index("ix_watch_targets_owner_user_id", "owner_user_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    owner_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    entity_id = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    frequency = Column(String, nullable=False, default="daily")
    last_checked_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)

    watch_runs = relationship("WatchRun", back_populates="watch_target")
    signals = relationship("Signal", back_populates="watch_target")
    alerts = relationship("Alert", back_populates="watch_target")


Index(
    "ux_watch_targets_user_entity_type_active",
    WatchTarget.user_id,
    WatchTarget.entity_id,
    WatchTarget.entity_type,
    unique=True,
    sqlite_where=WatchTarget.deleted_at.is_(None),
)
Index(
    "ux_watch_targets_owner_entity_type_active",
    WatchTarget.owner_user_id,
    WatchTarget.entity_id,
    WatchTarget.entity_type,
    unique=True,
    sqlite_where=(WatchTarget.deleted_at.is_(None) & WatchTarget.owner_user_id.is_not(None)),
)


class WatchRun(Base):
    __tablename__ = "watch_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'success', 'failed', 'skipped')",
            name="ck_watch_runs_status",
        ),
        Index("ix_watch_runs_watch_target_id", "watch_target_id"),
        Index("ix_watch_runs_status", "status"),
        Index("ix_watch_runs_started_at", "started_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    watch_target_id = Column(String, ForeignKey("watch_targets.id"), nullable=False)
    # Keep a same-type reference to job_runs.id for compatibility with the existing model graph.
    job_run_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    items_found = Column(Integer, nullable=False, default=0)
    signals_created = Column(Integer, nullable=False, default=0)
    alerts_created = Column(Integer, nullable=False, default=0)
    error_code = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    watch_target = relationship("WatchTarget", back_populates="watch_runs")


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('new_intelligence', 'website_change', 'new_news', 'new_video', 'leadership_change', 'contact_change', 'score_change', 'relation_change')",
            name="ck_signals_signal_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_signals_severity",
        ),
        Index("ix_signals_watch_target_id", "watch_target_id"),
        Index("ix_signals_entity_id_detected_at", "entity_id", "detected_at"),
        Index("ix_signals_signal_type_severity", "signal_type", "severity"),
        Index("ix_signals_owner_user_id_detected_at", "owner_user_id", "detected_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    watch_target_id = Column(String, ForeignKey("watch_targets.id"), nullable=False)
    owner_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    entity_id = Column(String, nullable=False)
    signal_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    severity = Column(String, nullable=False, default="low")
    evidence_id = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    old_value_json = Column(JSON, nullable=True)
    new_value_json = Column(JSON, nullable=True)
    detected_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    dedup_key = Column(String, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    watch_target = relationship("WatchTarget", back_populates="signals")
    alerts = relationship("Alert", back_populates="signal")


Index("ux_signals_dedup_key", Signal.dedup_key, unique=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(
            "signal_type IN ('new_intelligence', 'website_change', 'new_news', 'new_video', 'leadership_change', 'contact_change', 'score_change', 'relation_change')",
            name="ck_alert_rules_signal_type",
        ),
        CheckConstraint(
            "minimum_severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_alert_rules_minimum_severity",
        ),
        Index("ix_alert_rules_is_enabled", "is_enabled"),
        Index("ix_alert_rules_signal_type", "signal_type"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=True)
    signal_type = Column(String, nullable=False)
    minimum_severity = Column(String, nullable=False, default="low")
    is_enabled = Column(Boolean, nullable=False, default=True)
    configuration_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


Index(
    "ux_alert_rules_user_signal_type",
    AlertRule.user_id,
    AlertRule.signal_type,
    unique=True,
    sqlite_where=AlertRule.user_id.is_not(None),
)

Index(
    "ux_alert_rules_default_signal_type",
    AlertRule.signal_type,
    unique=True,
    sqlite_where=AlertRule.user_id.is_(None),
)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('unread', 'read', 'dismissed')",
            name="ck_alerts_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_alerts_severity",
        ),
        UniqueConstraint("signal_id", "user_id", name="uix_alerts_signal_id_user_id"),
        Index("ix_alerts_user_id_status_created_at", "user_id", "status", "created_at"),
        Index("ix_alerts_owner_user_id_status_created_at", "owner_user_id", "status", "created_at"),
        Index("ix_alerts_watch_target_id", "watch_target_id"),
        Index("ix_alerts_signal_id", "signal_id"),
        Index("ix_alerts_severity", "severity"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    owner_user_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    watch_target_id = Column(String, ForeignKey("watch_targets.id"), nullable=False)
    signal_id = Column(String, ForeignKey("signals.id"), nullable=False)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    severity = Column(String, nullable=False, default="low")
    status = Column(String, nullable=False, default="unread")
    source_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    read_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)

    watch_target = relationship("WatchTarget", back_populates="alerts")
    signal = relationship("Signal", back_populates="alerts")


Index(
    "ux_alerts_signal_id_owner_user_id",
    Alert.signal_id,
    Alert.owner_user_id,
    unique=True,
    sqlite_where=Alert.owner_user_id.is_not(None),
)
