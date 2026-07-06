from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError
from argon2.low_level import Type
from sqlalchemy.orm import Session

from config import settings
from models.auth import AuthSession, User


@dataclass(frozen=True)
class AuthError(Exception):
    status_code: int
    error_code: str
    message: str
    retry_after_seconds: int | None = None


def normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _password_hasher() -> PasswordHasher:
    return PasswordHasher(
        time_cost=int(settings.AUTH_PASSWORD_TIME_COST),
        memory_cost=int(settings.AUTH_PASSWORD_MEMORY_COST_KIB),
        parallelism=int(settings.AUTH_PASSWORD_PARALLELISM),
        hash_len=int(settings.AUTH_PASSWORD_HASH_LEN),
        salt_len=int(settings.AUTH_PASSWORD_SALT_LEN),
        type=Type.ID,
    )


_DUMMY_PASSWORD_HASH = _password_hasher().hash("dummy-password")


def hash_password(password: str) -> str:
    return _password_hasher().hash(str(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return bool(_password_hasher().verify(str(password_hash), str(password)))
    except (VerifyMismatchError, InvalidHash, VerificationError):
        return False
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return bool(_password_hasher().check_needs_rehash(str(password_hash)))
    except Exception:
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token).encode("utf-8")).hexdigest()


class LoginRateLimiter:
    def __init__(self, *, max_attempts: int, window_seconds: int):
        self._max_attempts = int(max_attempts)
        self._window_seconds = int(window_seconds)
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def _cleanup_locked(self, *, now: float) -> None:
        cutoff = now - self._window_seconds
        keys = list(self._attempts.keys())
        for key in keys:
            remaining = [ts for ts in self._attempts.get(key, []) if ts >= cutoff]
            if remaining:
                self._attempts[key] = remaining
            else:
                self._attempts.pop(key, None)

    def is_limited(self, *, key: str) -> int | None:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now=now)
            history = list(self._attempts.get(key, []))
            if len(history) < self._max_attempts:
                return None
            oldest = history[0] if history else now
            retry_after = int(max(1, (oldest + self._window_seconds) - now))
            return retry_after

    def record_failure(self, *, key: str) -> int | None:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now=now)
            history = list(self._attempts.get(key, []))
            history.append(now)
            self._attempts[key] = history
            if len(history) < self._max_attempts:
                return None
            oldest = history[0]
            retry_after = int(max(1, (oldest + self._window_seconds) - now))
            return retry_after

    def clear(self, *, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


_default_rate_limiter = LoginRateLimiter(
    max_attempts=int(settings.AUTH_LOGIN_MAX_ATTEMPTS),
    window_seconds=int(settings.AUTH_LOGIN_WINDOW_SECONDS),
)


def _client_key(*, normalized_email: str, client_fingerprint: str) -> str:
    digest = hashlib.sha256(str(client_fingerprint).encode("utf-8")).hexdigest()
    return f"{normalized_email}:{digest}"


def authenticate_user(
    db: Session,
    *,
    email: str,
    password: str,
    client_fingerprint: str,
) -> User:
    normalized = normalize_email(email)
    if not normalized:
        raise AuthError(401, "INVALID_CREDENTIALS", "Invalid credentials")

    if not password:
        raise AuthError(401, "INVALID_CREDENTIALS", "Invalid credentials")

    limiter_key = _client_key(normalized_email=normalized, client_fingerprint=client_fingerprint)
    if bool(settings.AUTH_LOGIN_RATE_LIMIT_ENABLED):
        retry_after = _default_rate_limiter.is_limited(key=limiter_key)
        if retry_after is not None:
            raise AuthError(429, "LOGIN_RATE_LIMITED", "Too many login attempts", retry_after_seconds=retry_after)

    user: User | None = db.query(User).filter(User.email_normalized == normalized).first()

    if user is None:
        verify_password(_DUMMY_PASSWORD_HASH, password)
        if bool(settings.AUTH_LOGIN_RATE_LIMIT_ENABLED):
            _default_rate_limiter.record_failure(key=limiter_key)
        raise AuthError(401, "INVALID_CREDENTIALS", "Invalid credentials")

    if user.deleted_at is not None:
        raise AuthError(403, "ACCOUNT_DISABLED", "Account is disabled")

    status_value = str(user.status or "").strip().lower()
    if status_value == "disabled":
        raise AuthError(403, "ACCOUNT_DISABLED", "Account is disabled")
    if status_value == "pending":
        raise AuthError(403, "ACCOUNT_PENDING", "Account is pending")

    if not verify_password(user.password_hash, password):
        if bool(settings.AUTH_LOGIN_RATE_LIMIT_ENABLED):
            _default_rate_limiter.record_failure(key=limiter_key)
        raise AuthError(401, "INVALID_CREDENTIALS", "Invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = datetime.utcnow()
    db.add(user)
    db.flush()
    db.commit()

    if bool(settings.AUTH_LOGIN_RATE_LIMIT_ENABLED):
        _default_rate_limiter.clear(key=limiter_key)

    return user


def create_auth_session(db: Session, *, user: User) -> tuple[AuthSession, str]:
    raw_token = generate_session_token()
    token_hash = hash_session_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(seconds=int(settings.AUTH_SESSION_TTL_SECONDS))

    session = AuthSession(
        id=str(uuid.uuid4()),
        public_id=str(uuid.uuid4()),
        user_id=str(user.id),
        token_hash=token_hash,
        status="active",
        created_at=datetime.utcnow(),
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, raw_token


def resolve_auth_session(db: Session, *, raw_token: str) -> AuthSession:
    if not raw_token:
        raise AuthError(401, "AUTH_REQUIRED", "Authentication required")
    token_hash = hash_session_token(raw_token)
    session: AuthSession | None = db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()
    if session is None:
        raise AuthError(401, "INVALID_SESSION", "Invalid session")
    return session


def revoke_auth_session(db: Session, *, session: AuthSession) -> None:
    if not session:
        return
    if str(session.status) != "revoked":
        session.status = "revoked"
        session.revoked_at = datetime.utcnow()
        db.add(session)
        db.commit()


def touch_session_last_seen(db: Session, *, session: AuthSession) -> None:
    now = datetime.utcnow()
    threshold_seconds = int(settings.AUTH_SESSION_LAST_SEEN_UPDATE_SECONDS)
    last_seen = session.last_seen_at
    if last_seen is not None:
        age_seconds = int((now - last_seen).total_seconds())
        if age_seconds < threshold_seconds:
            return
    session.last_seen_at = now
    db.add(session)
    db.commit()
