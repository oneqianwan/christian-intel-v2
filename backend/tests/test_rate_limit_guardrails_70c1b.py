from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_fixed_window_allows_until_limit_and_then_blocks():
    from services.rate_limiter import InMemoryRateLimiter, RateLimitRule

    limiter = InMemoryRateLimiter(
        rules={
            "test": RateLimitRule(
                name="test",
                limit=2,
                window_seconds=60,
                key_parts=("ip", "route"),
            )
        }
    )
    limiter.set_time_for_tests(1000)

    first = limiter.allow(key="ip=1|route=/test", rule_name="test")
    second = limiter.allow(key="ip=1|route=/test", rule_name="test")
    blocked = limiter.allow(key="ip=1|route=/test", rule_name="test")

    assert first.allowed is True
    assert first.remaining == 1
    assert second.allowed is True
    assert second.remaining == 0
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after_seconds == 60
    assert blocked.reset_after_seconds == 60


def test_window_expiry_and_reset_for_tests_restore_capacity():
    from services.rate_limiter import InMemoryRateLimiter, RateLimitRule

    limiter = InMemoryRateLimiter(
        rules={
            "test": RateLimitRule(
                name="test",
                limit=1,
                window_seconds=30,
                key_parts=("ip",),
            )
        }
    )
    limiter.set_time_for_tests(100)

    assert limiter.allow(key="ip=1", rule_name="test").allowed is True
    assert limiter.allow(key="ip=1", rule_name="test").allowed is False

    limiter.advance_time_for_tests(31)
    assert limiter.allow(key="ip=1", rule_name="test").allowed is True

    limiter.reset_for_tests()
    assert limiter.allow(key="ip=1", rule_name="test").allowed is True


def test_different_keys_do_not_interfere_by_user_tenant_and_route():
    from dependencies.rate_limit import build_rate_limit_key
    from services.rate_limiter import InMemoryRateLimiter, RateLimitRule

    limiter = InMemoryRateLimiter(
        rules={
            "test": RateLimitRule(
                name="test",
                limit=1,
                window_seconds=60,
                key_parts=("tenant_id", "user_id", "route", "resource_id"),
            )
        }
    )
    limiter.set_time_for_tests(500)

    key_a = build_rate_limit_key(tenant_id="tenant-a", user_id="user-a", route="/api/chat/simple")
    key_b = build_rate_limit_key(tenant_id="tenant-b", user_id="user-a", route="/api/chat/simple")
    key_c = build_rate_limit_key(tenant_id="tenant-a", user_id="user-b", route="/api/chat/simple")
    key_d = build_rate_limit_key(tenant_id="tenant-a", user_id="user-a", route="/api/chat/stream")
    key_e = build_rate_limit_key(tenant_id="tenant-a", user_id="user-a", resource_id="watch-2")

    assert limiter.allow(key=key_a, rule_name="test").allowed is True
    assert limiter.allow(key=key_a, rule_name="test").allowed is False

    assert limiter.allow(key=key_b, rule_name="test").allowed is True
    assert limiter.allow(key=key_c, rule_name="test").allowed is True
    assert limiter.allow(key=key_d, rule_name="test").allowed is True
    assert limiter.allow(key=key_e, rule_name="test").allowed is True


def test_429_response_contains_retry_after_header():
    rate_limit_module = importlib.import_module("dependencies.rate_limit")
    services_module = importlib.import_module("services.rate_limiter")

    limiter = services_module.InMemoryRateLimiter(
        rules={
            "test": services_module.RateLimitRule(
                name="test",
                limit=1,
                window_seconds=60,
                key_parts=("ip", "route"),
            )
        }
    )
    limiter.set_time_for_tests(1000)

    original_get_rate_limiter = rate_limit_module.get_rate_limiter
    rate_limit_module.get_rate_limiter = lambda: limiter
    try:
        app = FastAPI()

        @app.get("/limited")
        def limited(request: Request):
            rate_limit_module.enforce_rate_limit_for_request(request, rule_name="test")
            return {"ok": True}

        client = TestClient(app)
        allowed = client.get("/limited", headers={"X-Forwarded-For": "198.51.100.10"})
        blocked = client.get("/limited", headers={"X-Forwarded-For": "198.51.100.10"})
    finally:
        rate_limit_module.get_rate_limiter = original_get_rate_limiter

    assert allowed.status_code == 200
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["error_code"] == "RATE_LIMITED"
    assert blocked.json()["detail"]["message"] == "Too many requests"
    assert blocked.json()["detail"]["retry_after_seconds"] == 60
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.headers["X-RateLimit-Limit"] == "1"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert blocked.headers["X-RateLimit-Reset"] == "60"
