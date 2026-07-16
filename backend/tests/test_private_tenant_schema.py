from __future__ import annotations

import importlib

from test_production_readiness_startup_checks import startup_runtime


def _index_names(inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def test_private_models_define_tenant_id_columns(startup_runtime):
    database = startup_runtime["database"]
    watch_models = importlib.import_module("models.watch_alert")

    assert "tenant_id" in database.Conversation.__table__.columns.keys()
    assert "tenant_id" in database.Message.__table__.columns.keys()
    assert "tenant_id" in database.Bookmark.__table__.columns.keys()
    assert "tenant_id" in database.UserFeedback.__table__.columns.keys()
    assert "tenant_id" in database.RequestTrace.__table__.columns.keys()
    assert "tenant_id" in database.UserProfile.__table__.columns.keys()
    assert "tenant_id" in database.Task.__table__.columns.keys()
    assert "tenant_id" in watch_models.WatchTarget.__table__.columns.keys()
    assert "tenant_id" in watch_models.Signal.__table__.columns.keys()
    assert "tenant_id" in watch_models.AlertRule.__table__.columns.keys()
    assert "tenant_id" in watch_models.Alert.__table__.columns.keys()


def test_private_tenant_indexes_exist_in_runtime_schema(startup_runtime):
    database = startup_runtime["database"]
    inspector = importlib.import_module("sqlalchemy").inspect(database.engine)

    assert {
        "ix_conversations_tenant_id",
        "ix_conversations_tenant_id_created_at",
        "ix_conversations_tenant_owner_user_id",
    }.issubset(_index_names(inspector, "conversations"))
    assert {
        "ix_messages_tenant_id",
        "ix_messages_tenant_id_created_at",
        "ix_messages_tenant_conversation_id",
    }.issubset(_index_names(inspector, "messages"))
    assert {
        "ix_bookmarks_tenant_id",
        "ix_bookmarks_tenant_id_created_at",
        "ix_bookmarks_tenant_user_id",
    }.issubset(_index_names(inspector, "bookmarks"))
    assert {
        "ix_user_feedbacks_tenant_id",
        "ix_user_feedbacks_tenant_id_created_at",
        "ix_user_feedbacks_tenant_user_id",
    }.issubset(_index_names(inspector, "user_feedbacks"))
    assert {
        "ix_request_traces_tenant_id",
        "ix_request_traces_tenant_id_created_at",
    }.issubset(_index_names(inspector, "request_traces"))
    assert {
        "ix_user_profiles_tenant_id",
        "ix_user_profiles_tenant_id_created_at",
        "ix_user_profiles_tenant_session_id",
    }.issubset(_index_names(inspector, "user_profiles"))
    assert {
        "ix_tasks_tenant_id",
        "ix_tasks_tenant_id_created_at",
        "ix_tasks_tenant_entity_id",
    }.issubset(_index_names(inspector, "tasks"))
    assert {
        "ix_watch_targets_tenant_id",
        "ix_watch_targets_tenant_created_at",
        "ix_watch_targets_tenant_user_id",
        "ix_watch_targets_tenant_owner_user_id",
        "ix_watch_targets_tenant_entity_id",
    }.issubset(_index_names(inspector, "watch_targets"))
    assert {
        "ix_signals_tenant_id",
        "ix_signals_tenant_detected_at",
        "ix_signals_tenant_owner_user_id",
        "ix_signals_tenant_watch_target_id",
        "ix_signals_tenant_entity_id",
    }.issubset(_index_names(inspector, "signals"))
    assert {
        "ix_alert_rules_tenant_id",
        "ix_alert_rules_tenant_created_at",
        "ix_alert_rules_tenant_user_id",
    }.issubset(_index_names(inspector, "alert_rules"))
    assert {
        "ix_alerts_tenant_id",
        "ix_alerts_tenant_created_at",
        "ix_alerts_tenant_user_id",
        "ix_alerts_tenant_owner_user_id",
        "ix_alerts_tenant_watch_target_id",
        "ix_alerts_tenant_signal_id",
    }.issubset(_index_names(inspector, "alerts"))
