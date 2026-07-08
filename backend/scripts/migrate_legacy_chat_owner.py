from __future__ import annotations

import argparse
import os
import sys

from dataclasses import dataclass
from pathlib import Path


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
    ):
        sys.modules.pop(module_name, None)

    import importlib

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    database.init_db()
    return config, database, auth_models


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


def _build_stats(conversation, *, target_user_id: str) -> TableStats:
    if conversation is None:
        return TableStats()
    owner_user_id = str(getattr(conversation, "owner_user_id", "") or "").strip()
    if not owner_user_id:
        return TableStats(matched=1, updated=1, skipped=0, conflicts=0)
    if owner_user_id == str(target_user_id):
        return TableStats(matched=1, updated=0, skipped=1, conflicts=0)
    return TableStats(matched=1, updated=0, skipped=0, conflicts=1)


def _print_stats(label: str, stats: TableStats) -> None:
    print(
        f"{label} matched={stats.matched} updated={stats.updated} skipped={stats.skipped} conflicts={stats.conflicts}"
    )


def _run(args: argparse.Namespace) -> int:
    mode = "apply" if args.apply else "dry-run"
    database_url = _parse_database_to_url(args.database)
    _refuse_default_database_url(database_url)
    _, database, auth_models = _load_runtime(database_url)

    db = database.SessionLocal()
    try:
        user_count_before = db.query(auth_models.User).count()
        auth_session_count_before = db.query(auth_models.AuthSession).count()
        target_user = _find_target_user(db, auth_models, args.email)
        conversation = db.query(database.Conversation).filter(database.Conversation.id == str(args.legacy_conversation_id)).first()
        conversation_stats = _build_stats(conversation, target_user_id=str(target_user.id))
        message_count = (
            db.query(database.Message)
            .filter(database.Message.conversation_id == str(args.legacy_conversation_id))
            .count()
        )
        message_stats = TableStats(
            matched=message_count,
            updated=0,
            skipped=message_count,
            conflicts=0,
        )

        print(f"MODE={mode}")
        print(f"TARGET_USER_EMAIL={_normalize_email(args.email)}")
        print(f"LEGACY_CONVERSATION_ID={str(args.legacy_conversation_id)}")
        _print_stats("CONVERSATIONS", conversation_stats)
        _print_stats("MESSAGES", message_stats)
        print("MESSAGE_OWNERSHIP=conversation-linked")

        if args.apply and conversation_stats.updated == 1 and conversation is not None:
            conversation.owner_user_id = str(target_user.id)
            db.commit()
        else:
            db.rollback()

        user_count_after = db.query(auth_models.User).count()
        auth_session_count_after = db.query(auth_models.AuthSession).count()
        if user_count_before != user_count_after:
            raise MigrationError("USER_COUNT_CHANGED", "Migration must not create or delete users")
        if auth_session_count_before != auth_session_count_after:
            raise MigrationError("AUTH_SESSION_CHANGED", "Migration must not modify auth sessions")

        print(f"USERS unchanged={user_count_after}")
        print(f"AUTH_SESSIONS unchanged={auth_session_count_after}")
        print("CONSISTENCY_CHECK=PASS" if args.apply else "CONSISTENCY_CHECK=PENDING")
        return 0
    finally:
        db.close()
        database.engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy chat conversation ownership")
    parser.add_argument("--database", required=True, help="SQLite path or SQLAlchemy database URL")
    parser.add_argument("--email", required=True, help="Active target user email")
    parser.add_argument("--legacy-conversation-id", required=True, help="Exact legacy conversation id")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing changes")
    parser.add_argument("--apply", action="store_true", help="Apply migration")
    args = parser.parse_args()

    if args.dry_run and args.apply:
        print("ERROR=MODE_CONFLICT")
        print("MESSAGE=Choose either --dry-run or --apply")
        return 1

    try:
        return _run(args)
    except MigrationError as exc:
        print(f"MODE={'apply' if args.apply else 'dry-run'}")
        print(f"ERROR={exc.code}")
        print(f"MESSAGE={exc.message}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
