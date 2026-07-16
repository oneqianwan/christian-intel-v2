import argparse
import importlib
import os
import sys

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import inspect

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

PRIVATE_TABLES = {
    "conversations",
    "messages",
    "bookmarks",
    "user_feedbacks",
    "watch_targets",
    "signals",
    "alert_rules",
    "alerts",
    "request_traces",
    "user_profiles",
    "tasks",
}

PUBLIC_GLOBAL_TABLES = {
    "organization_profiles",
    "knowledge_entities",
    "sources",
    "pages",
    "intelligence_items",
    "relation_edges",
    "funding_rounds",
    "investments",
    "organization_types",
    "theological_positions",
}

REQUIRED_INDEXES = {
    "conversations": {
        "ix_conversations_tenant_id",
        "ix_conversations_tenant_id_created_at",
        "ix_conversations_tenant_owner_user_id",
    },
    "messages": {
        "ix_messages_tenant_id",
        "ix_messages_tenant_id_created_at",
        "ix_messages_tenant_conversation_id",
    },
    "bookmarks": {
        "ix_bookmarks_tenant_id",
        "ix_bookmarks_tenant_id_created_at",
        "ix_bookmarks_tenant_user_id",
    },
    "user_feedbacks": {
        "ix_user_feedbacks_tenant_id",
        "ix_user_feedbacks_tenant_id_created_at",
        "ix_user_feedbacks_tenant_user_id",
    },
    "watch_targets": {
        "ix_watch_targets_tenant_id",
        "ix_watch_targets_tenant_created_at",
        "ix_watch_targets_tenant_user_id",
        "ix_watch_targets_tenant_owner_user_id",
        "ix_watch_targets_tenant_entity_id",
    },
    "signals": {
        "ix_signals_tenant_id",
        "ix_signals_tenant_detected_at",
        "ix_signals_tenant_owner_user_id",
        "ix_signals_tenant_watch_target_id",
        "ix_signals_tenant_entity_id",
    },
    "alert_rules": {
        "ix_alert_rules_tenant_id",
        "ix_alert_rules_tenant_created_at",
        "ix_alert_rules_tenant_user_id",
    },
    "alerts": {
        "ix_alerts_tenant_id",
        "ix_alerts_tenant_created_at",
        "ix_alerts_tenant_user_id",
        "ix_alerts_tenant_owner_user_id",
        "ix_alerts_tenant_watch_target_id",
        "ix_alerts_tenant_signal_id",
    },
    "request_traces": {
        "ix_request_traces_tenant_id",
        "ix_request_traces_tenant_id_created_at",
    },
    "user_profiles": {
        "ix_user_profiles_tenant_id",
        "ix_user_profiles_tenant_id_created_at",
        "ix_user_profiles_tenant_session_id",
    },
    "tasks": {
        "ix_tasks_tenant_id",
        "ix_tasks_tenant_id_created_at",
        "ix_tasks_tenant_entity_id",
    },
}


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    details: dict


def _parse_database_to_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("DATABASE_URL is required")
    if "://" in value:
        return value
    path = Path(value).expanduser().resolve()
    return f"sqlite:///{path.as_posix()}"


def _refuse_default_database_url(database_url: str) -> None:
    normalized = str(database_url or "").strip()
    if not normalized:
        raise ValueError("DATABASE_URL is required")
    if normalized.startswith("sqlite:///"):
        raw_path = normalized[len("sqlite:///") :]
        db_path = Path(raw_path)
        backend_dir = Path(__file__).resolve().parents[1]
        default_db_path = (backend_dir / "cio_intelligence.db").resolve()
        if db_path.resolve() == default_db_path:
            raise ValueError("Refuse to operate on default backend cio_intelligence.db")


def _load_runtime(database_url: str):
    os.environ["DATABASE_URL"] = database_url

    for module_name in (
        "config",
        "models.database",
        "models.auth",
        "models.watch_alert",
        "services.tenant_service",
    ):
        sys.modules.pop(module_name, None)

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    watch_models = importlib.import_module("models.watch_alert")
    tenant_service = importlib.import_module("services.tenant_service")
    return config, database, auth_models, watch_models, tenant_service


def _normalize(value) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _build_user_tenant_map(db, auth_models) -> dict[str, str]:
    rows = db.query(auth_models.User.id, auth_models.User.default_tenant_id).all()
    result: dict[str, str] = {}
    for user_id, tenant_id in rows:
        normalized_user_id = _normalize(user_id)
        normalized_tenant_id = _normalize(tenant_id)
        if normalized_user_id and normalized_tenant_id:
            result[normalized_user_id] = normalized_tenant_id
    return result


def _build_conversation_tenant_map(db, database) -> dict[str, str]:
    rows = db.query(database.Conversation.id, database.Conversation.tenant_id).all()
    result: dict[str, str] = {}
    for conversation_id, tenant_id in rows:
        normalized_conversation_id = _normalize(conversation_id)
        normalized_tenant_id = _normalize(tenant_id)
        if normalized_conversation_id and normalized_tenant_id:
            result[normalized_conversation_id] = normalized_tenant_id
    return result


def _build_watch_target_tenant_map(db, watch_models) -> dict[str, str]:
    rows = db.query(watch_models.WatchTarget.id, watch_models.WatchTarget.tenant_id).all()
    result: dict[str, str] = {}
    for watch_target_id, tenant_id in rows:
        normalized_watch_target_id = _normalize(watch_target_id)
        normalized_tenant_id = _normalize(tenant_id)
        if normalized_watch_target_id and normalized_tenant_id:
            result[normalized_watch_target_id] = normalized_tenant_id
    return result


def _build_profile_tenant_map(db, database) -> dict[str, str]:
    rows = db.query(database.UserProfile.session_id, database.UserProfile.tenant_id).all()
    result: dict[str, str] = {}
    for session_id, tenant_id in rows:
        normalized_session_id = _normalize(session_id)
        normalized_tenant_id = _normalize(tenant_id)
        if normalized_session_id and normalized_tenant_id:
            result[normalized_session_id] = normalized_tenant_id
    return result


def _assign_tenant(record, tenant_id: str | None) -> bool:
    normalized_tenant_id = _normalize(tenant_id)
    if not normalized_tenant_id:
        return False
    if _normalize(getattr(record, "tenant_id", None)) == normalized_tenant_id:
        return False
    record.tenant_id = normalized_tenant_id
    return True


def _backfill_private_tenant_ids(db, database, auth_models, watch_models) -> dict:
    report = {
        "conversations_backfilled": 0,
        "messages_backfilled": 0,
        "bookmarks_backfilled": 0,
        "feedback_backfilled": 0,
        "watch_targets_backfilled": 0,
        "signals_backfilled": 0,
        "alert_rules_backfilled": 0,
        "alerts_backfilled": 0,
        "request_traces_backfilled": 0,
        "user_profiles_backfilled": 0,
        "tasks_backfilled": 0,
        "request_traces_unresolved": 0,
        "user_profiles_unresolved": 0,
        "tasks_unresolved": 0,
    }

    user_tenant_map = _build_user_tenant_map(db, auth_models)

    for conversation in db.query(database.Conversation).filter(database.Conversation.tenant_id.is_(None)).all():
        if _assign_tenant(conversation, user_tenant_map.get(_normalize(conversation.owner_user_id) or "")):
            report["conversations_backfilled"] += 1
    db.flush()

    conversation_tenant_map = _build_conversation_tenant_map(db, database)

    for message in db.query(database.Message).filter(database.Message.tenant_id.is_(None)).all():
        if _assign_tenant(message, conversation_tenant_map.get(_normalize(message.conversation_id) or "")):
            report["messages_backfilled"] += 1

    for bookmark in db.query(database.Bookmark).filter(database.Bookmark.tenant_id.is_(None)).all():
        if _assign_tenant(bookmark, user_tenant_map.get(_normalize(bookmark.user_id) or "")):
            report["bookmarks_backfilled"] += 1

    for feedback in db.query(database.UserFeedback).filter(database.UserFeedback.tenant_id.is_(None)).all():
        if _assign_tenant(feedback, user_tenant_map.get(_normalize(feedback.user_id) or "")):
            report["feedback_backfilled"] += 1

    for watch_target in db.query(watch_models.WatchTarget).filter(watch_models.WatchTarget.tenant_id.is_(None)).all():
        tenant_id = user_tenant_map.get(_normalize(watch_target.owner_user_id) or "")
        if tenant_id is None:
            tenant_id = user_tenant_map.get(_normalize(watch_target.user_id) or "")
        if _assign_tenant(watch_target, tenant_id):
            report["watch_targets_backfilled"] += 1
    db.flush()

    watch_target_tenant_map = _build_watch_target_tenant_map(db, watch_models)

    for signal in db.query(watch_models.Signal).filter(watch_models.Signal.tenant_id.is_(None)).all():
        tenant_id = watch_target_tenant_map.get(_normalize(signal.watch_target_id) or "")
        if tenant_id is None:
            tenant_id = user_tenant_map.get(_normalize(signal.owner_user_id) or "")
        if _assign_tenant(signal, tenant_id):
            report["signals_backfilled"] += 1

    for alert_rule in db.query(watch_models.AlertRule).filter(watch_models.AlertRule.tenant_id.is_(None)).all():
        if _assign_tenant(alert_rule, user_tenant_map.get(_normalize(alert_rule.user_id) or "")):
            report["alert_rules_backfilled"] += 1

    for alert in db.query(watch_models.Alert).filter(watch_models.Alert.tenant_id.is_(None)).all():
        tenant_id = watch_target_tenant_map.get(_normalize(alert.watch_target_id) or "")
        if tenant_id is None:
            tenant_id = user_tenant_map.get(_normalize(alert.owner_user_id) or "")
        if tenant_id is None:
            tenant_id = user_tenant_map.get(_normalize(alert.user_id) or "")
        if _assign_tenant(alert, tenant_id):
            report["alerts_backfilled"] += 1

    for user_profile in db.query(database.UserProfile).filter(database.UserProfile.tenant_id.is_(None)).all():
        session_id = _normalize(user_profile.session_id) or ""
        tenant_id = None
        if session_id.startswith("user:"):
            tenant_id = user_tenant_map.get(session_id.split(":", 1)[1])
        if tenant_id is None:
            tenant_id = conversation_tenant_map.get(session_id)
        if _assign_tenant(user_profile, tenant_id):
            report["user_profiles_backfilled"] += 1
        else:
            report["user_profiles_unresolved"] += 1
    db.flush()

    profile_tenant_map = _build_profile_tenant_map(db, database)

    for trace in db.query(database.RequestTrace).filter(database.RequestTrace.tenant_id.is_(None)).all():
        event_data = trace.event_data or {}
        tenant_id = None
        if isinstance(event_data, dict):
            conversation_id = _normalize(event_data.get("conversation_id"))
            if conversation_id:
                tenant_id = conversation_tenant_map.get(conversation_id) or profile_tenant_map.get(conversation_id)
            if tenant_id is None:
                event_user_id = _normalize(event_data.get("user_id")) or _normalize(event_data.get("owner_user_id"))
                if event_user_id:
                    tenant_id = user_tenant_map.get(event_user_id)
        if tenant_id is None:
            request_id = _normalize(trace.request_id) or ""
            if request_id.startswith("profile:"):
                tenant_id = profile_tenant_map.get(request_id.split(":", 1)[1])
        if _assign_tenant(trace, tenant_id):
            report["request_traces_backfilled"] += 1
        else:
            report["request_traces_unresolved"] += 1

    for task in db.query(database.Task).filter(database.Task.tenant_id.is_(None)).all():
        if _assign_tenant(task, None):
            report["tasks_backfilled"] += 1
        else:
            report["tasks_unresolved"] += 1

    db.flush()
    return report


def apply_private_tenant_migration(database, auth_models, watch_models, tenant_service) -> dict:
    with database.engine.begin() as conn:
        database.Base.metadata.create_all(bind=conn)

    database._ensure_schema_compatibility()

    db = database.SessionLocal()
    try:
        tenant_service.ensure_default_tenant_foundation(db)
        report = _backfill_private_tenant_ids(db, database, auth_models, watch_models)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def verify_private_tenant_schema(database) -> VerifyResult:
    inspector = inspect(database.engine)
    tables = set(inspector.get_table_names())

    missing_tables = sorted(PRIVATE_TABLES - tables)
    if missing_tables:
        return VerifyResult(ok=False, details={"missing_private_tables": missing_tables})

    missing_tenant_columns: dict[str, list[str]] = {}
    missing_indexes: dict[str, list[str]] = {}
    public_tables_with_tenant_id: list[str] = []

    for table_name in sorted(PRIVATE_TABLES):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "tenant_id" not in columns:
            missing_tenant_columns[table_name] = ["tenant_id"]
        indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        expected_indexes = REQUIRED_INDEXES.get(table_name, set())
        missing = sorted(expected_indexes - indexes)
        if missing:
            missing_indexes[table_name] = missing

    for table_name in sorted(PUBLIC_GLOBAL_TABLES & tables):
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if "tenant_id" in columns:
            public_tables_with_tenant_id.append(table_name)

    if missing_tenant_columns or missing_indexes or public_tables_with_tenant_id:
        return VerifyResult(
            ok=False,
            details={
                "missing_tenant_columns": missing_tenant_columns,
                "missing_indexes": missing_indexes,
                "public_tables_with_tenant_id": public_tables_with_tenant_id,
            },
        )

    with database.engine.begin() as conn:
        unresolved_counts = {
            "request_traces_unresolved": int(
                conn.execute(importlib.import_module("sqlalchemy").text("SELECT COUNT(*) FROM request_traces WHERE tenant_id IS NULL")).scalar()
                or 0
            ),
            "user_profiles_unresolved": int(
                conn.execute(importlib.import_module("sqlalchemy").text("SELECT COUNT(*) FROM user_profiles WHERE tenant_id IS NULL")).scalar()
                or 0
            ),
            "tasks_unresolved": int(
                conn.execute(importlib.import_module("sqlalchemy").text("SELECT COUNT(*) FROM tasks WHERE tenant_id IS NULL")).scalar()
                or 0
            ),
        }

    return VerifyResult(
        ok=True,
        details={
            "private_tables_verified": sorted(PRIVATE_TABLES),
            "public_tables_verified": sorted(PUBLIC_GLOBAL_TABLES & tables),
            **unresolved_counts,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_tenant_private_v1.py")
    parser.add_argument("--database", required=True, help="SQLite path or SQLAlchemy URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")

    args = parser.parse_args(argv)

    database_url = _parse_database_to_url(args.database)
    _refuse_default_database_url(database_url)

    _, database, auth_models, watch_models, tenant_service = _load_runtime(database_url)

    if args.dry_run:
        inspector = inspect(database.engine)
        print(f"DRY_RUN_DATABASE_URL={database_url}")
        print(f"DRY_RUN_TABLES_PRESENT={sorted(inspector.get_table_names())}")
        return 0

    if args.apply:
        report = apply_private_tenant_migration(database, auth_models, watch_models, tenant_service)
        print(f"APPLY_PRIVATE_REPORT={report}")

    if args.verify:
        result = verify_private_tenant_schema(database)
        print(f"VERIFY_PRIVATE_OK={'true' if result.ok else 'false'}")
        print(f"VERIFY_PRIVATE_DETAILS={result.details}")
        return 0 if result.ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
