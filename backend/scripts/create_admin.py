from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _database_url_from_arg(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("DATABASE_REQUIRED")
    if "://" in raw:
        return raw
    path = Path(raw)
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    return f"sqlite:///{path.as_posix()}"


def _safe_database_display(database_url: str) -> str:
    parsed = urlparse(database_url)
    if parsed.scheme == "sqlite":
        return database_url
    if not parsed.scheme:
        return database_url
    netloc = ""
    if parsed.hostname:
        if parsed.username:
            netloc = f"{parsed.username}@{parsed.hostname}"
        else:
            netloc = parsed.hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _validate_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("INVALID_EMAIL")
    if any(ch.isspace() for ch in normalized):
        raise ValueError("INVALID_EMAIL")
    if len(normalized) > 320:
        raise ValueError("INVALID_EMAIL")
    return normalized


def _create_first_super_admin(*, database_url: str, email: str, display_name: str, password: str):
    os.environ["DATABASE_URL"] = str(database_url)

    from models.auth import User
    from models.database import SessionLocal, init_db
    from services.auth_service import hash_password, validate_new_password

    init_db()
    db = SessionLocal()
    try:
        normalized_email = _validate_email(email)
        existing_super_admin = (
            db.query(User)
            .filter(User.role == "super_admin", User.deleted_at.is_(None))
            .first()
        )
        if existing_super_admin is not None:
            raise ValueError("SUPER_ADMIN_ALREADY_EXISTS")

        existing_user = db.query(User).filter(User.email_normalized == normalized_email).first()
        if existing_user is not None:
            raise ValueError("USER_EMAIL_EXISTS")

        validate_new_password(password)
        user = User(
            email=str(email).strip(),
            email_normalized=normalized_email,
            password_hash=hash_password(password),
            display_name=str(display_name or "Admin").strip() or "Admin",
            role="super_admin",
            status="active",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run(argv: list[str] | None = None, *, print_fn=print, getpass_fn=getpass.getpass) -> int:
    parser = argparse.ArgumentParser(prog="create_admin")
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args(argv)

    database_url = _database_url_from_arg(args.database)
    print_fn(f"DATABASE={_safe_database_display(database_url)}")

    password = os.environ.get("CIO_BOOTSTRAP_ADMIN_PASSWORD")
    if password is None:
        password = getpass_fn("Password: ")
        confirm = getpass_fn("Confirm password: ")
        if password != confirm:
            print_fn("ERROR=PASSWORD_CONFIRMATION_MISMATCH")
            return 1
    else:
        confirm_env = os.environ.get("CIO_BOOTSTRAP_ADMIN_PASSWORD_CONFIRM")
        if confirm_env is not None and confirm_env != password:
            print_fn("ERROR=PASSWORD_CONFIRMATION_MISMATCH")
            return 1

    try:
        user = _create_first_super_admin(
            database_url=database_url,
            email=args.email,
            display_name=args.display_name,
            password=password,
        )
    except Exception as exc:
        code = getattr(exc, "error_code", None) or (str(exc) if str(exc) else exc.__class__.__name__)
        print_fn(f"ERROR={code}")
        return 1

    print_fn(
        f"CREATED_SUPER_ADMIN public_id={user.public_id} email={user.email} role={user.role} status={user.status}"
    )
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
