from __future__ import annotations

import argparse
import os
import sys

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import or_


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class MigrationError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = str(code)
        self.message = str(message or code)
        super().__init__(self.message)


@dataclass(frozen=True)
class TableStats:
    matched: int = 0
    updated: int = 0
    skipped: int = 0
    conflicts: int = 0


@dataclass(frozen=True)
class MigrationPlan:
    watch_target_ids: set[str]
    eligible_watch_target_ids: set[str]
    conflicting_watch_target_ids: set[str]
    merged_watch_target_ids: set[str]
    merged_watch_target_map: dict[str, str]
    signal_ids_to_verify: set[str]
    alert_ids_to_verify: set[str]
    watch_targets: TableStats
    signals: TableStats
    alerts: TableStats


def _parse_database_to_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise MigrationError("DATABASE_REQUIRED", "Database path or URL is required")
    if "://" in value:
        return value
    return f"sqlite:///{Path(value).expanduser().resolve().as_posix()}"


def _refuse_default_database_url(database_url: str) -> None:
    normalized = str(database_url or "").strip()
    if not normalized.startswith("sqlite:///"):
        return
    raw_path = normalized[len("sqlite:///") :]
    db_path = Path(raw_path).resolve()
    default_db_path = (BACKEND_DIR / "cio_intelligence.db").resolve()
    if db_path == default_db_path:
        raise MigrationError("DEFAULT_DATABASE_FORBIDDEN", "Refuse to operate on default backend database")


def _load_runtime(database_url: str):
    os.environ["DATABASE_URL"] = database_url

    for module_name in (
        "config",
        "models.database",
        "models.auth",
        "models.watch_alert",
        "services.auth_service",
    ):
        sys.modules.pop(module_name, None)

    import importlib

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    watch_models = importlib.import_module("models.watch_alert")
    return config, database, auth_models, watch_models


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized or any(ch.isspace() for ch in normalized):
        raise MigrationError("INVALID_EMAIL", "Invalid email")
    return normalized


def _find_target_user(db, auth_models, email: str):
    normalized_email = _normalize_email(email)
    user = db.query(auth_models.User).filter(auth_models.User.email_normalized == normalized_email).first()
    if user is None:
        raise MigrationError("USER_NOT_FOUND", "Target user not found")
    if user.deleted_at is not None or str(user.status or "").strip() != "active":
        raise MigrationError("USER_NOT_ACTIVE", "Target user must be active")
    return user


def _collect_table_stats(
    records,
    *,
    target_user_id: str,
    force_conflict_ids: set[str] | None = None,
    force_skip_ids: set[str] | None = None,
    id_getter=None,
) -> TableStats:
    matched = updated = skipped = conflicts = 0
    forced_conflicts = force_conflict_ids or set()
    forced_skips = force_skip_ids or set()
    for record in records:
        matched += 1
        record_id = str(id_getter(record) if id_getter else getattr(record, "id", ""))
        owner_user_id = str(getattr(record, "owner_user_id", "") or "").strip()
        if record_id and record_id in forced_conflicts:
            conflicts += 1
        elif record_id and record_id in forced_skips:
            skipped += 1
        elif not owner_user_id:
            updated += 1
        elif owner_user_id == target_user_id:
            skipped += 1
        else:
            conflicts += 1
    return TableStats(matched=matched, updated=updated, skipped=skipped, conflicts=conflicts)


def _build_plan(db, watch_models, *, legacy_session_id: str, target_user_id: str) -> MigrationPlan:
    watch_targets = (
        db.query(watch_models.WatchTarget)
        .filter(
            watch_models.WatchTarget.user_id == legacy_session_id,
            watch_models.WatchTarget.deleted_at.is_(None),
        )
        .all()
    )
    watch_target_ids = {str(item.id) for item in watch_targets}
    legacy_watch_targets_without_owner = [
        item for item in watch_targets if not str(item.owner_user_id or "").strip()
    ]
    existing_owned_targets = []
    legacy_entity_ids = {str(item.entity_id) for item in legacy_watch_targets_without_owner if str(item.entity_id or "").strip()}
    if legacy_entity_ids:
        existing_owned_targets = (
            db.query(watch_models.WatchTarget)
            .filter(
                watch_models.WatchTarget.owner_user_id == str(target_user_id),
                watch_models.WatchTarget.deleted_at.is_(None),
                watch_models.WatchTarget.entity_id.in_(sorted(legacy_entity_ids)),
            )
            .all()
        )
    existing_owned_target_by_key = {
        (str(item.entity_id), str(item.entity_type)): str(item.id) for item in existing_owned_targets
    }
    conflicting_watch_target_ids = {
        str(item.id)
        for item in watch_targets
        if str(item.owner_user_id or "").strip()
        and str(item.owner_user_id) != str(target_user_id)
    }
    merged_watch_target_map = {
        str(item.id): existing_owned_target_by_key[(str(item.entity_id), str(item.entity_type))]
        for item in legacy_watch_targets_without_owner
        if (str(item.entity_id), str(item.entity_type)) in existing_owned_target_by_key
        and existing_owned_target_by_key[(str(item.entity_id), str(item.entity_type))] != str(item.id)
    }
    merged_watch_target_ids = set(merged_watch_target_map)
    eligible_watch_target_ids = watch_target_ids - conflicting_watch_target_ids - merged_watch_target_ids
    watch_target_stats = _collect_table_stats(
        watch_targets,
        target_user_id=target_user_id,
        force_skip_ids=merged_watch_target_ids,
    )

    signals = []
    if watch_target_ids:
        signals = (
            db.query(watch_models.Signal)
            .filter(watch_models.Signal.watch_target_id.in_(sorted(watch_target_ids)))
            .all()
        )
    signal_stats = _collect_table_stats(
        signals,
        target_user_id=target_user_id,
        force_conflict_ids={
            str(signal.id)
            for signal in signals
            if str(signal.watch_target_id or "") in conflicting_watch_target_ids
        },
    )
    signal_ids_to_verify = {
        str(signal.id)
        for signal in signals
        if str(signal.watch_target_id or "") not in conflicting_watch_target_ids
    }

    alerts = []
    if watch_target_ids:
        alerts = (
            db.query(watch_models.Alert)
            .filter(
                or_(
                    watch_models.Alert.user_id == legacy_session_id,
                    watch_models.Alert.watch_target_id.in_(sorted(watch_target_ids)),
                )
            )
            .all()
        )
    else:
        alerts = db.query(watch_models.Alert).filter(watch_models.Alert.user_id == legacy_session_id).all()

    alert_stats = _collect_table_stats(
        alerts,
        target_user_id=target_user_id,
        force_conflict_ids={
            str(alert.id)
            for alert in alerts
            if str(alert.watch_target_id or "") in conflicting_watch_target_ids
        },
    )
    alert_ids_to_verify = {
        str(alert.id)
        for alert in alerts
        if str(alert.watch_target_id or "") not in conflicting_watch_target_ids
    }

    return MigrationPlan(
        watch_target_ids=watch_target_ids,
        eligible_watch_target_ids=eligible_watch_target_ids,
        conflicting_watch_target_ids=conflicting_watch_target_ids,
        merged_watch_target_ids=merged_watch_target_ids,
        merged_watch_target_map=merged_watch_target_map,
        signal_ids_to_verify=signal_ids_to_verify,
        alert_ids_to_verify=alert_ids_to_verify,
        watch_targets=watch_target_stats,
        signals=signal_stats,
        alerts=alert_stats,
    )


def _apply_plan(db, watch_models, *, plan: MigrationPlan, target_user_id: str, legacy_session_id: str) -> None:
    normalized_target_user_id = str(target_user_id)
    if plan.eligible_watch_target_ids:
        (
            db.query(watch_models.WatchTarget)
            .filter(
                watch_models.WatchTarget.id.in_(sorted(plan.eligible_watch_target_ids)),
                watch_models.WatchTarget.owner_user_id.is_(None),
            )
            .update({watch_models.WatchTarget.owner_user_id: normalized_target_user_id}, synchronize_session=False)
        )
        (
            db.query(watch_models.Signal)
            .filter(
                watch_models.Signal.watch_target_id.in_(sorted(plan.eligible_watch_target_ids)),
                watch_models.Signal.owner_user_id.is_(None),
            )
            .update({watch_models.Signal.owner_user_id: normalized_target_user_id}, synchronize_session=False)
        )
        (
            db.query(watch_models.Alert)
            .filter(
                or_(
                    watch_models.Alert.user_id == legacy_session_id,
                    watch_models.Alert.watch_target_id.in_(sorted(plan.eligible_watch_target_ids)),
                ),
                watch_models.Alert.owner_user_id.is_(None),
            )
            .update({watch_models.Alert.owner_user_id: normalized_target_user_id}, synchronize_session=False)
        )
    if plan.merged_watch_target_map:
        merged_at = datetime.utcnow()
        for legacy_watch_target_id, target_watch_target_id in sorted(plan.merged_watch_target_map.items()):
            (
                db.query(watch_models.Signal)
                .filter(
                    watch_models.Signal.watch_target_id == legacy_watch_target_id,
                    watch_models.Signal.owner_user_id.is_(None),
                )
                .update(
                    {
                        watch_models.Signal.owner_user_id: normalized_target_user_id,
                        watch_models.Signal.watch_target_id: target_watch_target_id,
                    },
                    synchronize_session=False,
                )
            )
            (
                db.query(watch_models.Alert)
                .filter(
                    or_(
                        watch_models.Alert.user_id == legacy_session_id,
                        watch_models.Alert.watch_target_id == legacy_watch_target_id,
                    ),
                    watch_models.Alert.owner_user_id.is_(None),
                )
                .update(
                    {
                        watch_models.Alert.owner_user_id: normalized_target_user_id,
                        watch_models.Alert.watch_target_id: target_watch_target_id,
                    },
                    synchronize_session=False,
                )
            )
            (
                db.query(watch_models.WatchTarget)
                .filter(
                    watch_models.WatchTarget.id == legacy_watch_target_id,
                    watch_models.WatchTarget.owner_user_id.is_(None),
                    watch_models.WatchTarget.deleted_at.is_(None),
                )
                .update(
                    {
                        watch_models.WatchTarget.owner_user_id: normalized_target_user_id,
                        watch_models.WatchTarget.deleted_at: merged_at,
                    },
                    synchronize_session=False,
                )
            )


def _verify_consistency(db, watch_models, *, plan: MigrationPlan, target_user_id: str, legacy_session_id: str) -> None:
    normalized_target_user_id = str(target_user_id)
    if plan.eligible_watch_target_ids:
        missing_watch_targets = (
            db.query(watch_models.WatchTarget.id)
            .filter(
                watch_models.WatchTarget.id.in_(sorted(plan.eligible_watch_target_ids)),
                watch_models.WatchTarget.owner_user_id != normalized_target_user_id,
            )
            .count()
        )
        if missing_watch_targets:
            raise MigrationError("WATCH_TARGET_CONSISTENCY_FAILED", "Watch target ownership consistency check failed")

        missing_signals = (
            db.query(watch_models.Signal.id)
            .filter(
                watch_models.Signal.watch_target_id.in_(sorted(plan.eligible_watch_target_ids)),
                watch_models.Signal.owner_user_id != normalized_target_user_id,
            )
            .count()
        )
        if missing_signals:
            raise MigrationError("SIGNAL_CONSISTENCY_FAILED", "Signal ownership consistency check failed")

    if plan.merged_watch_target_ids:
        missing_merged_watch_targets = (
            db.query(watch_models.WatchTarget.id)
            .filter(
                watch_models.WatchTarget.id.in_(sorted(plan.merged_watch_target_ids)),
                or_(
                    watch_models.WatchTarget.owner_user_id != normalized_target_user_id,
                    watch_models.WatchTarget.deleted_at.is_(None),
                ),
            )
            .count()
        )
        if missing_merged_watch_targets:
            raise MigrationError("WATCH_TARGET_MERGE_FAILED", "Merged watch target consistency check failed")

    missing_signals_by_id = 0
    if plan.signal_ids_to_verify:
        missing_signals_by_id = (
            db.query(watch_models.Signal.id)
            .filter(
                watch_models.Signal.id.in_(sorted(plan.signal_ids_to_verify)),
                watch_models.Signal.owner_user_id != normalized_target_user_id,
            )
            .count()
        )
    if missing_signals_by_id:
        raise MigrationError("SIGNAL_CONSISTENCY_FAILED", "Signal ownership consistency check failed")

    missing_alerts = 0
    if plan.alert_ids_to_verify:
        missing_alerts = (
            db.query(watch_models.Alert.id)
            .filter(
                watch_models.Alert.id.in_(sorted(plan.alert_ids_to_verify)),
                watch_models.Alert.owner_user_id != normalized_target_user_id,
            )
            .count()
        )
    if missing_alerts:
        raise MigrationError("ALERT_CONSISTENCY_FAILED", "Alert ownership consistency check failed")


def _print_stats(print_fn, label: str, stats: TableStats) -> None:
    print_fn(
        f"{label} matched={stats.matched} updated={stats.updated} "
        f"skipped={stats.skipped} conflicts={stats.conflicts}"
    )


def run(argv: list[str] | None = None, *, print_fn=print) -> int:
    parser = argparse.ArgumentParser(prog="migrate_legacy_watch_alert_owner")
    parser.add_argument("--email", required=True)
    parser.add_argument("--legacy-session-id", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    if args.dry_run and args.apply:
        print_fn("ERROR=MODE_CONFLICT")
        return 1

    mode = "apply" if args.apply else "dry-run"
    database_url = _parse_database_to_url(args.database)
    _refuse_default_database_url(database_url)
    legacy_session_id = str(args.legacy_session_id or "").strip()
    if not legacy_session_id:
        print_fn("ERROR=LEGACY_SESSION_ID_REQUIRED")
        return 1

    _, database, auth_models, watch_models = _load_runtime(database_url)
    database.init_db()
    db = database.SessionLocal()
    try:
        target_user = _find_target_user(db, auth_models, args.email)
        auth_session_count_before = db.query(auth_models.AuthSession).count()
        user_count_before = db.query(auth_models.User).count()
        plan = _build_plan(
            db,
            watch_models,
            legacy_session_id=legacy_session_id,
            target_user_id=str(target_user.id),
        )

        print_fn(f"MODE={mode}")
        print_fn(f"DATABASE={database_url}")
        print_fn(f"TARGET_EMAIL={target_user.email_normalized}")
        _print_stats(print_fn, "WATCH_TARGETS", plan.watch_targets)
        _print_stats(print_fn, "SIGNALS", plan.signals)
        _print_stats(print_fn, "ALERTS", plan.alerts)

        if mode == "apply":
            _apply_plan(
                db,
                watch_models,
                plan=plan,
                target_user_id=str(target_user.id),
                legacy_session_id=legacy_session_id,
            )
            _verify_consistency(
                db,
                watch_models,
                plan=plan,
                target_user_id=str(target_user.id),
                legacy_session_id=legacy_session_id,
            )
            auth_session_count_after = db.query(auth_models.AuthSession).count()
            user_count_after = db.query(auth_models.User).count()
            if auth_session_count_after != auth_session_count_before:
                raise MigrationError("AUTH_SESSION_MODIFIED", "AuthSession rows must not be modified")
            if user_count_after != user_count_before:
                raise MigrationError("USER_COUNT_CHANGED", "User rows must not be created or deleted")
            db.commit()
            print_fn("CONSISTENCY_CHECK=PASS")
        else:
            db.rollback()
            print_fn("CONSISTENCY_CHECK=PENDING")
        return 0
    except MigrationError as exc:
        db.rollback()
        print_fn(f"ERROR={exc.code}")
        return 1
    finally:
        db.close()


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
