import argparse
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    details: dict


def _load_runtime(database_url: str):
    os.environ["DATABASE_URL"] = database_url

    for module_name in (
        "config",
        "models.database",
        "models.auth",
        "models.watch_alert",
        "services.tenant_service",
        "scripts.migrate_tenant_private_v1",
    ):
        sys.modules.pop(module_name, None)

    config = importlib.import_module("config")
    database = importlib.import_module("models.database")
    auth_models = importlib.import_module("models.auth")
    tenant_service = importlib.import_module("services.tenant_service")
    return config, database, auth_models, tenant_service


def _load_private_migration_module():
    return importlib.import_module("scripts.migrate_tenant_private_v1")


def _apply_migration(database, auth_models, tenant_service) -> None:
    with database.engine.begin() as conn:
        database.Base.metadata.create_all(
            bind=conn,
            tables=[
                auth_models.Tenant.__table__,
                auth_models.User.__table__,
                auth_models.TenantMembership.__table__,
                auth_models.AuthSession.__table__,
                auth_models.AccountToken.__table__,
            ],
        )
    db = database.SessionLocal()
    try:
        tenant_service.ensure_default_tenant_foundation(db)
    finally:
        db.close()
    private_migration = _load_private_migration_module()
    watch_models = importlib.import_module("models.watch_alert")
    private_migration.apply_private_tenant_migration(database, auth_models, watch_models, tenant_service)


def _verify_schema(database, auth_models) -> VerifyResult:
    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    inspector = inspect(database.engine)
    tables = set(inspector.get_table_names())
    required_tables = {"users", "auth_sessions", "account_tokens", "tenants", "tenant_memberships"}
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        return VerifyResult(ok=False, details={"missing_tables": missing_tables})

    def _colnames(table: str) -> set[str]:
        return {col["name"] for col in inspector.get_columns(table)}

    users_cols = _colnames("users")
    sessions_cols = _colnames("auth_sessions")
    account_tokens_cols = _colnames("account_tokens")

    required_users_cols = {
        "id",
        "public_id",
        "email",
        "email_normalized",
        "password_hash",
        "display_name",
        "role",
        "status",
        "default_tenant_id",
        "email_verified_at",
        "last_login_at",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    required_sessions_cols = {
        "id",
        "public_id",
        "user_id",
        "token_hash",
        "status",
        "created_at",
        "last_seen_at",
        "expires_at",
        "revoked_at",
    }
    required_account_token_cols = {
        "id",
        "public_id",
        "user_id",
        "created_by_user_id",
        "token_hash",
        "purpose",
        "status",
        "created_at",
        "expires_at",
        "used_at",
        "revoked_at",
    }
    required_tenant_cols = {
        "id",
        "public_id",
        "name",
        "slug",
        "status",
        "created_at",
        "updated_at",
        "deleted_at",
    }
    required_tenant_membership_cols = {
        "id",
        "public_id",
        "tenant_id",
        "user_id",
        "role",
        "status",
        "created_by_user_id",
        "created_at",
        "updated_at",
        "deleted_at",
    }

    missing_users_cols = sorted(required_users_cols - users_cols)
    missing_sessions_cols = sorted(required_sessions_cols - sessions_cols)
    missing_account_token_cols = sorted(required_account_token_cols - account_tokens_cols)
    missing_tenant_cols = sorted(required_tenant_cols - _colnames("tenants"))
    missing_tenant_membership_cols = sorted(required_tenant_membership_cols - _colnames("tenant_memberships"))
    if (
        missing_users_cols
        or missing_sessions_cols
        or missing_account_token_cols
        or missing_tenant_cols
        or missing_tenant_membership_cols
    ):
        return VerifyResult(
            ok=False,
            details={
                "missing_users_columns": missing_users_cols,
                "missing_auth_sessions_columns": missing_sessions_cols,
                "missing_account_tokens_columns": missing_account_token_cols,
                "missing_tenants_columns": missing_tenant_cols,
                "missing_tenant_memberships_columns": missing_tenant_membership_cols,
            },
        )

    forbidden_columns = [
        name
        for name in sorted(users_cols | sessions_cols | account_tokens_cols)
        if "raw_password" in name
        or "plain_password" in name
        or "password_plain" in name
        or "raw_token" in name
        or "session_token" in name
        or "cookie_token" in name
    ]
    if forbidden_columns:
        return VerifyResult(ok=False, details={"forbidden_columns": forbidden_columns})

    unique_users = {tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("users")}
    unique_sessions = {tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("auth_sessions")}
    unique_account_tokens = {tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("account_tokens")}
    unique_tenants = {tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("tenants")}
    unique_tenant_memberships = {
        tuple(sorted(c["column_names"])) for c in inspector.get_unique_constraints("tenant_memberships")
    }

    expected_unique_users = {("email_normalized",), ("public_id",)}
    expected_unique_sessions = {("public_id",), ("token_hash",)}
    expected_unique_account_tokens = {("public_id",), ("token_hash",)}
    expected_unique_tenants = {("public_id",), ("slug",)}
    expected_unique_tenant_memberships = {("public_id",)}

    missing_unique_users = sorted(expected_unique_users - unique_users)
    missing_unique_sessions = sorted(expected_unique_sessions - unique_sessions)
    missing_unique_account_tokens = sorted(expected_unique_account_tokens - unique_account_tokens)
    missing_unique_tenants = sorted(expected_unique_tenants - unique_tenants)
    missing_unique_tenant_memberships = sorted(expected_unique_tenant_memberships - unique_tenant_memberships)
    if (
        missing_unique_users
        or missing_unique_sessions
        or missing_unique_account_tokens
        or missing_unique_tenants
        or missing_unique_tenant_memberships
    ):
        return VerifyResult(
            ok=False,
            details={
                "missing_unique_users": missing_unique_users,
                "missing_unique_auth_sessions": missing_unique_sessions,
                "missing_unique_account_tokens": missing_unique_account_tokens,
                "missing_unique_tenants": missing_unique_tenants,
                "missing_unique_tenant_memberships": missing_unique_tenant_memberships,
            },
        )

    session_indexes = {index["name"] for index in inspector.get_indexes("auth_sessions")}
    account_token_indexes = {index["name"] for index in inspector.get_indexes("account_tokens")}
    tenant_indexes = {index["name"] for index in inspector.get_indexes("tenants")}
    tenant_membership_indexes = {index["name"] for index in inspector.get_indexes("tenant_memberships")}
    expected_account_token_indexes = {
        "ix_account_tokens_user_id",
        "ix_account_tokens_purpose",
        "ix_account_tokens_expires_at",
    }
    expected_tenant_indexes = {"ix_tenants_slug"}
    expected_tenant_membership_indexes = {
        "ix_tenant_memberships_tenant_id",
        "ix_tenant_memberships_user_id",
        "ix_tenant_memberships_created_by_user_id",
        "ux_tenant_memberships_tenant_user_active",
    }
    missing_account_token_indexes = sorted(expected_account_token_indexes - account_token_indexes)
    missing_tenant_indexes = sorted(expected_tenant_indexes - tenant_indexes)
    missing_tenant_membership_indexes = sorted(expected_tenant_membership_indexes - tenant_membership_indexes)
    if missing_account_token_indexes or missing_tenant_indexes or missing_tenant_membership_indexes:
        return VerifyResult(
            ok=False,
            details={
                "missing_account_token_indexes": missing_account_token_indexes,
                "missing_tenant_indexes": missing_tenant_indexes,
                "missing_tenant_membership_indexes": missing_tenant_membership_indexes,
                "existing_auth_session_indexes": sorted(session_indexes),
                "existing_account_token_indexes": sorted(account_token_indexes),
                "existing_tenant_indexes": sorted(tenant_indexes),
                "existing_tenant_membership_indexes": sorted(tenant_membership_indexes),
            },
        )

    fk_sessions = inspector.get_foreign_keys("auth_sessions")
    has_user_fk = any(
        fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
        and fk.get("constrained_columns") == ["user_id"]
        for fk in fk_sessions
    )
    if not has_user_fk:
        return VerifyResult(ok=False, details={"missing_foreign_key": True, "auth_sessions_foreign_keys": fk_sessions})

    fk_account_tokens = inspector.get_foreign_keys("account_tokens")
    account_tokens_has_user_fk = any(
        fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
        and fk.get("constrained_columns") == ["user_id"]
        for fk in fk_account_tokens
    )
    if not account_tokens_has_user_fk:
        return VerifyResult(
            ok=False,
            details={"missing_account_tokens_user_foreign_key": True, "account_tokens_foreign_keys": fk_account_tokens},
        )

    fk_tenant_memberships = inspector.get_foreign_keys("tenant_memberships")
    membership_has_tenant_fk = any(
        fk.get("referred_table") == "tenants"
        and fk.get("referred_columns") == ["id"]
        and fk.get("constrained_columns") == ["tenant_id"]
        for fk in fk_tenant_memberships
    )
    membership_has_user_fk = any(
        fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
        and fk.get("constrained_columns") == ["user_id"]
        for fk in fk_tenant_memberships
    )
    if not membership_has_tenant_fk or not membership_has_user_fk:
        return VerifyResult(
            ok=False,
            details={
                "missing_tenant_membership_foreign_keys": True,
                "tenant_memberships_foreign_keys": fk_tenant_memberships,
            },
        )

    conn = database.engine.connect()
    trans = conn.begin()
    db = Session(bind=conn)
    try:
        def seed_user() -> str:
            user = auth_models.User(
                email="admin@example.com",
                email_normalized="admin@example.com",
                password_hash="x",
                display_name="Admin",
                role="admin",
                status="active",
            )
            db.add(user)
            db.flush()
            return str(user.id)

        user_id = seed_user()
        db.add(
            auth_models.AuthSession(
                user_id=user_id,
                token_hash="a" * 64,
                status="active",
                expires_at=database.datetime.utcnow(),
            )
        )
        db.flush()

        db.add(
            auth_models.User(
                email="bad@example.com",
                email_normalized="bad@example.com",
                password_hash="x",
                display_name="Bad",
                role="invalid_role",
                status="active",
            )
        )
        try:
            db.flush()
            return VerifyResult(ok=False, details={"check_constraints_enforced": False, "reason": "invalid role inserted"})
        except IntegrityError:
            db.rollback()

        user_id = seed_user()
        db.add(
            auth_models.AuthSession(
                user_id=user_id,
                token_hash="b" * 64,
                status="invalid_status",
                expires_at=database.datetime.utcnow(),
            )
        )
        try:
            db.flush()
            return VerifyResult(ok=False, details={"check_constraints_enforced": False, "reason": "invalid status inserted"})
        except IntegrityError:
            db.rollback()

        user_id = seed_user()
        db.add(
            auth_models.AccountToken(
                user_id=user_id,
                token_hash="c" * 64,
                purpose="setup_password",
                status="active",
                expires_at=database.datetime.utcnow(),
            )
        )
        db.flush()

        db.add(
            auth_models.AccountToken(
                user_id=user_id,
                token_hash="d" * 64,
                purpose="invalid_purpose",
                status="active",
                expires_at=database.datetime.utcnow(),
            )
        )
        try:
            db.flush()
            return VerifyResult(
                ok=False,
                details={"check_constraints_enforced": False, "reason": "invalid account token purpose inserted"},
            )
        except IntegrityError:
            db.rollback()

        user_id = seed_user()
        db.add(
            auth_models.AccountToken(
                user_id=user_id,
                token_hash="e" * 64,
                purpose="password_reset",
                status="invalid_status",
                expires_at=database.datetime.utcnow(),
            )
        )
        try:
            db.flush()
            return VerifyResult(
                ok=False,
                details={"check_constraints_enforced": False, "reason": "invalid account token status inserted"},
            )
        except IntegrityError:
            db.rollback()
    finally:
        db.close()
        trans.rollback()
        conn.close()

    default_tenant_slug = None
    default_tenant_membership_count = 0
    conn = database.engine.connect()
    try:
        row = conn.execute(importlib.import_module("sqlalchemy").text("SELECT slug FROM tenants LIMIT 1")).fetchone()
        if row is not None:
            default_tenant_slug = row[0]
        default_tenant_membership_count = int(
            conn.execute(importlib.import_module("sqlalchemy").text("SELECT COUNT(*) FROM tenant_memberships")).scalar() or 0
        )
    finally:
        conn.close()

    private_migration = _load_private_migration_module()
    private_result = private_migration.verify_private_tenant_schema(database)
    if not private_result.ok:
        return VerifyResult(
            ok=False,
            details={
                "auth_verify": {
                    "tables": sorted(required_tables),
                    "default_tenant_slug": default_tenant_slug,
                    "tenant_membership_count": default_tenant_membership_count,
                },
                "private_verify": private_result.details,
            },
        )

    return VerifyResult(
        ok=True,
        details={
            "tables": sorted(required_tables),
            "default_tenant_slug": default_tenant_slug,
            "tenant_membership_count": default_tenant_membership_count,
            "private_verify": private_result.details,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_auth_v1.py")
    parser.add_argument("--database", required=True, help="SQLite path or SQLAlchemy URL")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")

    args = parser.parse_args(argv)

    database_url = _parse_database_to_url(args.database)
    _refuse_default_database_url(database_url)

    _, database, auth_models, tenant_service = _load_runtime(database_url)

    if args.dry_run:
        from sqlalchemy import inspect

        inspector = inspect(database.engine)
        existing_tables = sorted(inspector.get_table_names())
        print(f"DRY_RUN_DATABASE_URL={database_url}")
        print(f"DRY_RUN_TABLES_PRESENT={existing_tables}")
        return 0

    if args.apply:
        _apply_migration(database, auth_models, tenant_service)

    if args.verify:
        result = _verify_schema(database, auth_models)
        print(f"VERIFY_OK={'true' if result.ok else 'false'}")
        print(f"VERIFY_DETAILS={result.details}")
        return 0 if result.ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
