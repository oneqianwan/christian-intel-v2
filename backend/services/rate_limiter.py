from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int
    key_parts: tuple[str, ...]


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int
    reset_after_seconds: int
    rule_name: str
    fail_open: bool = False


DEFAULT_RATE_LIMIT_RULES: dict[str, RateLimitRule] = {
    "auth_login": RateLimitRule(
        name="auth_login",
        limit=10,
        window_seconds=300,
        key_parts=("normalized_email", "ip"),
    ),
    "public_read": RateLimitRule(
        name="public_read",
        limit=60,
        window_seconds=60,
        key_parts=("ip", "method", "route"),
    ),
    "public_high_cost": RateLimitRule(
        name="public_high_cost",
        limit=10,
        window_seconds=60,
        key_parts=("ip", "method", "route"),
    ),
    "analyze_url": RateLimitRule(
        name="analyze_url",
        limit=5,
        window_seconds=60,
        key_parts=("ip", "method", "route"),
    ),
    "chat_simple": RateLimitRule(
        name="chat_simple",
        limit=20,
        window_seconds=60,
        key_parts=("tenant_id", "user_id", "route"),
    ),
    "chat_stream": RateLimitRule(
        name="chat_stream",
        limit=10,
        window_seconds=60,
        key_parts=("tenant_id", "user_id", "route"),
    ),
    "watch_run": RateLimitRule(
        name="watch_run",
        limit=5,
        window_seconds=600,
        key_parts=("tenant_id", "user_id", "resource_id"),
    ),
    "diagnostics": RateLimitRule(
        name="diagnostics",
        limit=30,
        window_seconds=60,
        key_parts=("tenant_id", "user_id", "route"),
    ),
    "admin_ops": RateLimitRule(
        name="admin_ops",
        limit=30,
        window_seconds=60,
        key_parts=("user_id", "route"),
    ),
    "export": RateLimitRule(
        name="export",
        limit=10,
        window_seconds=60,
        key_parts=("user_id", "route"),
    ),
}


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        rules: dict[str, RateLimitRule] | None = None,
        now_func=None,
        max_entries: int = 4096,
    ) -> None:
        self._rules = dict(rules or DEFAULT_RATE_LIMIT_RULES)
        self._now_func = now_func or time.time
        self._max_entries = max(64, int(max_entries))
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], dict[str, float | int]] = {}
        self._test_time: float | None = None
        self._last_error: str | None = None

    @property
    def rules(self) -> dict[str, RateLimitRule]:
        return dict(self._rules)

    def get_rule(self, rule_name: str) -> RateLimitRule:
        rule = self._rules.get(str(rule_name or "").strip())
        if rule is None:
            raise KeyError(f"unknown rate limit rule: {rule_name}")
        return rule

    def _now(self) -> float:
        if self._test_time is not None:
            return float(self._test_time)
        return float(self._now_func())

    def _record_error(self, exc: Exception) -> None:
        self._last_error = str(exc)
        logger.exception("rate limiter fail-open: %s", exc)

    def _cleanup_locked(self, *, now: float) -> None:
        expired_keys = [
            entry_key
            for entry_key, entry in self._windows.items()
            if float(entry.get("reset_at", 0)) <= now
        ]
        for entry_key in expired_keys:
            self._windows.pop(entry_key, None)

        if len(self._windows) <= self._max_entries:
            return

        overflow = len(self._windows) - self._max_entries
        eviction_order = sorted(
            self._windows.items(),
            key=lambda item: (
                float(item[1].get("reset_at", 0)),
                float(item[1].get("window_start", 0)),
            ),
        )
        for entry_key, _ in eviction_order[:overflow]:
            self._windows.pop(entry_key, None)

    def allow(
        self,
        *,
        key: str,
        rule_name: str | None = None,
        rule: RateLimitRule | None = None,
    ) -> RateLimitDecision:
        resolved_rule = rule or self.get_rule(str(rule_name or "").strip())
        normalized_key = str(key or "").strip() or "unknown"
        now = self._now()

        try:
            with self._lock:
                self._cleanup_locked(now=now)
                bucket_key = (resolved_rule.name, normalized_key)
                entry = self._windows.get(bucket_key)

                if entry is None or float(entry.get("reset_at", 0)) <= now:
                    window_start = float(now)
                    reset_at = float(window_start + int(resolved_rule.window_seconds))
                    entry = {
                        "count": 0,
                        "window_start": float(window_start),
                        "reset_at": reset_at,
                    }
                    self._windows[bucket_key] = entry

                count = int(entry.get("count", 0))
                reset_at = float(entry.get("reset_at", now + int(resolved_rule.window_seconds)))
                retry_after = int(max(1, math.ceil(reset_at - now)))

                if count >= int(resolved_rule.limit):
                    return RateLimitDecision(
                        allowed=False,
                        limit=int(resolved_rule.limit),
                        remaining=0,
                        retry_after_seconds=retry_after,
                        reset_after_seconds=retry_after,
                        rule_name=resolved_rule.name,
                    )

                count += 1
                entry["count"] = count
                remaining = max(0, int(resolved_rule.limit) - count)
                return RateLimitDecision(
                    allowed=True,
                    limit=int(resolved_rule.limit),
                    remaining=remaining,
                    retry_after_seconds=0,
                    reset_after_seconds=retry_after,
                    rule_name=resolved_rule.name,
                )
        except Exception as exc:
            with self._lock:
                self._record_error(exc)
            return RateLimitDecision(
                allowed=True,
                limit=int(resolved_rule.limit),
                remaining=max(0, int(resolved_rule.limit) - 1),
                retry_after_seconds=0,
                reset_after_seconds=int(resolved_rule.window_seconds),
                rule_name=resolved_rule.name,
                fail_open=True,
            )

    def reset_for_tests(self) -> None:
        with self._lock:
            self._windows.clear()
            self._last_error = None

    def set_time_for_tests(self, current_time: float) -> None:
        with self._lock:
            self._test_time = float(current_time)

    def advance_time_for_tests(self, delta_seconds: float) -> None:
        with self._lock:
            base_time = self._test_time if self._test_time is not None else self._now_func()
            self._test_time = float(base_time) + float(delta_seconds)

    def clear_test_time_for_tests(self) -> None:
        with self._lock:
            self._test_time = None


_default_limiter = InMemoryRateLimiter()


def get_default_rate_limiter() -> InMemoryRateLimiter:
    return _default_limiter


def reset_rate_limiter_for_tests() -> None:
    _default_limiter.reset_for_tests()
    _default_limiter.clear_test_time_for_tests()


def set_rate_limiter_time_for_tests(current_time: float) -> None:
    _default_limiter.set_time_for_tests(current_time)


def advance_rate_limiter_time_for_tests(delta_seconds: float) -> None:
    _default_limiter.advance_time_for_tests(delta_seconds)


def clear_rate_limiter_time_for_tests() -> None:
    _default_limiter.clear_test_time_for_tests()
