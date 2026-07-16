from __future__ import annotations

import hashlib
import secrets
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta

import config
from models.auth import AccountToken, User
from services.auth_service import (
    AuthError,
    hash_password,
    normalize_email,
    revoke_all_user_sessions,
    validate_new_password,
)
from services import tenant_service


ACCOUNT_TOKEN_PURPOSE_SETUP_PASSWORD = "setup_password"
ACCOUNT_TOKEN_PURPOSE_PASSWORD_RESET = "password_reset"

ACCOUNT_TOKEN_STATUS_ACTIVE = "active"
ACCOUNT_TOKEN_STATUS_USED = "used"
ACCOUNT_TOKEN_STATUS_REVOKED = "revoked"
ACCOUNT_TOKEN_STATUS_EXPIRED = "expired"

ROLE_VALUES = frozenset({"super_admin", "admin", "analyst", "viewer"})
CREATABLE_USER_STATUS_VALUES = frozenset({"active", "pending"})


@dataclass
class AccountLifecycleError(Exception):
    status_code: int
    error_code: str
    message: str


def hash_account_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()


def generate_account_token() -> str:
    return secrets.token_urlsafe(32)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_role(role: str | None) -> str | None:
    normalized = str(role or "").strip().lower()
    if normalized not in ROLE_VALUES:
        return None
    return normalized


def _normalize_creatable_status(status: str | None) -> str | None:
    normalized = str(status or "").strip().lower()
    if normalized not in CREATABLE_USER_STATUS_VALUES:
        return None
    return normalized


def _validate_email(email: str) -> str:
    normalized = normalize_email(email)
    local_part, separator, domain = normalized.partition("@")
    if not normalized or separator != "@" or not local_part or not domain or "." not in domain:
        raise AccountLifecycleError(422, "INVALID_EMAIL", "Invalid email")
    return normalized


def _active_token_query(db, *, purpose: str, user_id: str):
    return (
        db.query(AccountToken)
        .filter(
            AccountToken.user_id == str(user_id),
            AccountToken.purpose == str(purpose),
            AccountToken.status == ACCOUNT_TOKEN_STATUS_ACTIVE,
        )
    )


def revoke_active_account_tokens(db, *, user_id: str, purpose: str) -> int:
    now = _utcnow()
    rowcount = _active_token_query(db, purpose=purpose, user_id=user_id).update(
        {
            "status": ACCOUNT_TOKEN_STATUS_REVOKED,
            "revoked_at": now,
        },
        synchronize_session=False,
    )
    return int(rowcount or 0)


def _create_one_time_token(
    db,
    *,
    user: User,
    purpose: str,
    ttl_seconds: int,
    created_by_user_id: str | None = None,
) -> tuple[AccountToken, str]:
    revoke_active_account_tokens(db, user_id=str(user.id), purpose=purpose)
    raw_token = generate_account_token()
    token = AccountToken(
        id=str(uuid.uuid4()),
        public_id=str(uuid.uuid4()),
        user_id=str(user.id),
        created_by_user_id=str(created_by_user_id) if created_by_user_id else None,
        token_hash=hash_account_token(raw_token),
        purpose=purpose,
        status=ACCOUNT_TOKEN_STATUS_ACTIVE,
        created_at=_utcnow(),
        expires_at=_utcnow() + timedelta(seconds=int(ttl_seconds)),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token, raw_token


def provision_user_with_setup_token(
    db,
    *,
    actor: User,
    email: str,
    display_name: str,
    role: str,
    status: str,
    tenant_public_id: str | None = None,
) -> tuple[User, AccountToken, str]:
    normalized_email = _validate_email(email)
    normalized_role = _normalize_role(role)
    normalized_status = _normalize_creatable_status(status)
    actor_role = _normalize_role(getattr(actor, "role", None))

    if normalized_role is None:
        raise AccountLifecycleError(422, "INVALID_ROLE", "Invalid role")
    if normalized_status is None:
        raise AccountLifecycleError(422, "INVALID_STATUS", "Invalid status")
    if normalized_role == "super_admin" and actor_role != "super_admin":
        raise AccountLifecycleError(403, "ROLE_FORBIDDEN", "Insufficient permissions")
    if not str(display_name or "").strip():
        raise AccountLifecycleError(422, "INVALID_DISPLAY_NAME", "Display name required")

    existing = db.query(User).filter(User.email_normalized == normalized_email).first()
    if existing is not None:
        raise AccountLifecycleError(409, "EMAIL_ALREADY_EXISTS", "Email already exists")

    try:
        tenant = tenant_service.resolve_tenant_for_user_creation(
            db,
            actor=actor,
            tenant_public_id=tenant_public_id,
        )
    except tenant_service.TenantError as exc:
        raise AccountLifecycleError(int(exc.status_code), exc.error_code, exc.message)

    # Store an argon2 hash even before first password setup so no plaintext or fake sentinel is persisted.
    bootstrap_secret = secrets.token_urlsafe(24)
    user = User(
        id=str(uuid.uuid4()),
        public_id=str(uuid.uuid4()),
        email=normalized_email,
        email_normalized=normalized_email,
        password_hash=hash_password(bootstrap_secret),
        display_name=str(display_name).strip(),
        role=normalized_role,
        status=normalized_status,
        default_tenant_id=str(tenant.id),
    )
    try:
        db.add(user)
        db.flush()
        tenant_service.get_or_create_membership(
            db,
            tenant=tenant,
            user=user,
            role=tenant_service.map_user_role_to_membership_role(normalized_role),
            status="active" if normalized_status == "active" else "pending",
            created_by_user_id=str(actor.id),
        )
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    token, raw_token = _create_one_time_token(
        db,
        user=user,
        purpose=ACCOUNT_TOKEN_PURPOSE_SETUP_PASSWORD,
        ttl_seconds=int(config.settings.AUTH_SETUP_TOKEN_TTL_SECONDS),
        created_by_user_id=str(actor.id),
    )
    return user, token, raw_token


def _get_active_token_or_error(db, *, raw_token: str, purpose: str) -> AccountToken:
    hashed = hash_account_token(str(raw_token or "").strip())
    if not hashed:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")

    token: AccountToken | None = db.query(AccountToken).filter(AccountToken.token_hash == hashed).first()
    if token is None or token.purpose != purpose:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")

    if token.status == ACCOUNT_TOKEN_STATUS_USED:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")
    if token.status == ACCOUNT_TOKEN_STATUS_REVOKED:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")
    if token.status == ACCOUNT_TOKEN_STATUS_EXPIRED or (token.expires_at and token.expires_at <= _utcnow()):
        if token.status == ACCOUNT_TOKEN_STATUS_ACTIVE:
            token.status = ACCOUNT_TOKEN_STATUS_EXPIRED
            db.add(token)
            db.commit()
        raise AccountLifecycleError(400, "TOKEN_EXPIRED", "Token expired")
    if token.status != ACCOUNT_TOKEN_STATUS_ACTIVE:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")
    return token


def setup_password_with_token(
    db,
    *,
    raw_token: str,
    new_password: str,
) -> User:
    token = _get_active_token_or_error(
        db,
        raw_token=raw_token,
        purpose=ACCOUNT_TOKEN_PURPOSE_SETUP_PASSWORD,
    )
    user: User | None = db.query(User).filter(User.id == token.user_id).first()
    if user is None or user.deleted_at is not None:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")
    if str(user.status or "").strip().lower() == "disabled":
        raise AccountLifecycleError(403, "ACCOUNT_DISABLED", "Account is disabled")

    try:
        validate_new_password(new_password)
    except AuthError as exc:
        raise AccountLifecycleError(int(exc.status_code), exc.error_code, exc.message)
    user.password_hash = hash_password(new_password)
    if str(user.status or "").strip().lower() == "pending":
        user.status = "active"
    user.updated_at = _utcnow()
    token.status = ACCOUNT_TOKEN_STATUS_USED
    token.used_at = _utcnow()
    db.add(user)
    db.add(token)
    db.commit()
    db.refresh(user)
    return user


def request_password_reset(
    db,
    *,
    email: str,
) -> tuple[AccountToken | None, str | None]:
    normalized_email = normalize_email(email)
    if not normalized_email:
        return None, None

    user: User | None = db.query(User).filter(User.email_normalized == normalized_email).first()
    if user is None or user.deleted_at is not None:
        return None, None
    if str(user.status or "").strip().lower() == "disabled":
        return None, None

    return _create_one_time_token(
        db,
        user=user,
        purpose=ACCOUNT_TOKEN_PURPOSE_PASSWORD_RESET,
        ttl_seconds=int(config.settings.AUTH_PASSWORD_RESET_TOKEN_TTL_SECONDS),
        created_by_user_id=None,
    )


def confirm_password_reset(
    db,
    *,
    raw_token: str,
    new_password: str,
) -> int:
    token = _get_active_token_or_error(
        db,
        raw_token=raw_token,
        purpose=ACCOUNT_TOKEN_PURPOSE_PASSWORD_RESET,
    )
    user: User | None = db.query(User).filter(User.id == token.user_id).first()
    if user is None or user.deleted_at is not None:
        raise AccountLifecycleError(400, "TOKEN_INVALID", "Invalid token")
    if str(user.status or "").strip().lower() == "disabled":
        raise AccountLifecycleError(403, "ACCOUNT_DISABLED", "Account is disabled")

    try:
        validate_new_password(new_password)
    except AuthError as exc:
        raise AccountLifecycleError(int(exc.status_code), exc.error_code, exc.message)
    user.password_hash = hash_password(new_password)
    user.updated_at = _utcnow()
    token.status = ACCOUNT_TOKEN_STATUS_USED
    token.used_at = _utcnow()
    db.add(user)
    db.add(token)
    revoked_count = revoke_all_user_sessions(db, user_id=user.id)
    db.commit()
    return int(revoked_count)
