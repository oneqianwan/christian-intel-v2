from __future__ import annotations

import re
import sys

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (BACKEND_DIR / relative_path).read_text(encoding="utf-8")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    config_text = _read("config.py")
    model_text = _read("models/watch_alert.py")
    watch_router_text = _read("routers/watch_targets.py")
    alert_router_text = _read("routers/alerts.py")
    schema_text = _read("schemas/watch_alert.py")
    dependency_text = _read("dependencies/watch_alert_auth.py")
    watch_service_text = _read("services/watch_target_service.py")
    signal_service_text = _read("services/signal_service.py")
    alert_service_text = _read("services/alert_service.py")
    migration_cli_text = _read("scripts/migrate_legacy_watch_alert_owner.py")

    _assert('"WATCH_ALERT_USER_OWNERSHIP_ENABLED": False' in config_text, "ownership flag must default to false")

    _assert(re.search(r"owner_user_id\s*=\s*Column\(String,\s*ForeignKey\(\"users\.id\"", model_text) is not None, "models must define owner_user_id foreign keys")
    _assert(model_text.count("owner_user_id = Column(") >= 3, "watch target, signal and alert must all define owner_user_id")
    _assert("user_id = Column(String, nullable=False)" in model_text, "legacy user_id fields must remain present")

    _assert(
        "from dependencies.watch_alert_auth import get_watch_alert_current_user_id as get_current_user_id" in watch_router_text,
        "watch router must use unified watch alert auth dependency",
    )
    _assert(
        "from dependencies.watch_alert_auth import get_watch_alert_current_user_id as get_current_user_id" in alert_router_text,
        "alerts router must use unified watch alert auth dependency",
    )
    _assert("Header(alias=\"x-session-id\")" not in watch_router_text, "watch router must not parse x-session-id directly")
    _assert("Header(alias=\"x-session-id\")" not in alert_router_text, "alerts router must not parse x-session-id directly")
    _assert("resolve_user_for_request" in dependency_text, "new mode must resolve formal auth user from auth dependency")

    _assert("owner_user_id" not in schema_text.split("class WatchTargetCreate", 1)[1].split("class WatchTargetUpdate", 1)[0], "watch create schema must not accept owner_user_id")
    _assert("user_id" not in schema_text.split("class WatchTargetCreate", 1)[1].split("class WatchTargetUpdate", 1)[0], "watch create schema must not accept user_id")

    _assert("WatchTarget.owner_user_id == user_id" in watch_service_text, "watch service must filter by owner_user_id in new mode")
    _assert("owner_user_id=user_id if ownership_enabled() else None" in watch_service_text, "watch creation must set owner_user_id in new mode")
    _assert("Signal.owner_user_id == normalized_owner_user_id" in signal_service_text, "signal listing must filter by exact owner_user_id")
    _assert("raise ValueError(\"SIGNAL_OWNER_REQUIRED\")" in signal_service_text, "signal creation must reject missing owner in new mode")
    _assert("Alert.owner_user_id == user_id" in alert_service_text, "alert service must filter by owner_user_id in new mode")
    _assert("query = query.filter(Alert.owner_user_id == user_id)" in alert_service_text, "alert bulk operations must include owner filter")

    _assert('mode = "apply" if args.apply else "dry-run"' in migration_cli_text, "migration CLI must default to dry-run")
    _assert("--password" not in migration_cli_text, "migration CLI must not accept password")
    _assert("AuthSession" in migration_cli_text, "migration CLI must verify AuthSession is not modified")
    _assert("session-1" not in migration_cli_text, "migration CLI must not embed default session ids")
    _assert("default admin" not in migration_cli_text.lower(), "migration CLI must not embed default admin logic")

    print("WATCH_ALERT_USER_OWNERSHIP_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
