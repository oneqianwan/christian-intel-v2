from __future__ import annotations

import hashlib
import re
from typing import Any


class AuditTrailRedactor:
    REDACTED_EMAIL = "[REDACTED_EMAIL]"
    REDACTED_PHONE = "[REDACTED_PHONE]"
    REDACTED_SECRET = "[REDACTED_SECRET]"

    _EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)
    _PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\-\s()]{7,}\d)(?!\w)")
    _AUTH_BEARER_RE = re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[^\s,;]+")
    _COOKIE_HEADER_RE = re.compile(r"(?i)\bCookie\s*:\s*[^\n]+")
    _SESSION_RE = re.compile(r"(?i)\b(?:cookie|session|token|api[_-]?key|password|secret)\s*=\s*[^\s,;]+")
    _KEY_VALUE_RE = re.compile(
        r"(?i)\b(?:authorization|cookie|session|token|api[_-]?key|password|secret)\s*:\s*[^\s,;]+"
    )
    _LONG_SECRET_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

    _SENSITIVE_KEYS = {
        "authorization",
        "cookie",
        "cookies",
        "session",
        "session_id",
        "token",
        "api_key",
        "apikey",
        "secret",
        "password",
    }

    def redact_text(self, text: str) -> str:
        redacted = str(text or "")
        redacted = self._AUTH_BEARER_RE.sub(f"Authorization: {self.REDACTED_SECRET}", redacted)
        redacted = self._COOKIE_HEADER_RE.sub(f"Cookie: {self.REDACTED_SECRET}", redacted)
        redacted = self._SESSION_RE.sub(lambda _m: self.REDACTED_SECRET, redacted)
        redacted = self._KEY_VALUE_RE.sub(lambda _m: self.REDACTED_SECRET, redacted)
        redacted = self._EMAIL_RE.sub(self.REDACTED_EMAIL, redacted)
        redacted = self._PHONE_RE.sub(self.REDACTED_PHONE, redacted)
        redacted = self._LONG_SECRET_RE.sub(self.REDACTED_SECRET, redacted)
        return redacted

    def fingerprint(self, text: str) -> str:
        value = str(text or "")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def sanitize_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key or "").strip().lower()
                if normalized_key in self._SENSITIVE_KEYS:
                    sanitized[str(key)] = self.REDACTED_SECRET
                    continue
                sanitized[str(key)] = self.sanitize_metadata(item)
            return sanitized
        if isinstance(value, list):
            return [self.sanitize_metadata(item) for item in value]
        if isinstance(value, tuple):
            return [self.sanitize_metadata(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value


_DEFAULT_REDACTOR = AuditTrailRedactor()


def redact_text(text: str) -> str:
    return _DEFAULT_REDACTOR.redact_text(text)


def fingerprint(text: str) -> str:
    return _DEFAULT_REDACTOR.fingerprint(text)


def sanitize_metadata(value: Any) -> Any:
    return _DEFAULT_REDACTOR.sanitize_metadata(value)
