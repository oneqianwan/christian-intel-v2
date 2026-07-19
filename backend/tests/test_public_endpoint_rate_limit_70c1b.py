from __future__ import annotations

import importlib
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "config",
    "dependencies",
    "services",
    "routers",
    "models",
    "main",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "routers.url_analysis",
    "routers.search",
    "routers.collection",
    "routers.missions",
    "dependencies.rate_limit",
    "services.rate_limiter",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def public_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"public_rate_limit_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    main = importlib.import_module("main")
    rate_limit_module = importlib.import_module("dependencies.rate_limit")
    services_module = importlib.import_module("services.rate_limiter")
    url_analysis_module = importlib.import_module("routers.url_analysis")
    collection_module = importlib.import_module("routers.collection")
    missions_module = importlib.import_module("routers.missions")

    client_ctx = TestClient(main.app)
    client = client_ctx.__enter__()
    try:
        yield {
            "client": client,
            "rate_limit_module": rate_limit_module,
            "services_module": services_module,
            "url_analysis_module": url_analysis_module,
            "collection_module": collection_module,
            "missions_module": missions_module,
        }
    finally:
        client_ctx.__exit__(None, None, None)
        _purge_modules()
        if test_db_path.exists():
            test_db_path.unlink()


def _patch_public_limiter(public_runtime, monkeypatch):
    services_module = public_runtime["services_module"]
    limiter = services_module.InMemoryRateLimiter(
        rules={
            "analyze_url": services_module.RateLimitRule(
                name="analyze_url",
                limit=1,
                window_seconds=60,
                key_parts=("ip", "method", "route"),
            ),
            "public_high_cost": services_module.RateLimitRule(
                name="public_high_cost",
                limit=1,
                window_seconds=60,
                key_parts=("ip", "method", "route"),
            ),
        }
    )
    limiter.set_time_for_tests(1000)
    monkeypatch.setattr(public_runtime["rate_limit_module"], "get_rate_limiter", lambda: limiter)
    return limiter


def _patch_public_dependencies(public_runtime, monkeypatch):
    async def fake_llm_analyze_url(prompt: str, payload: list[dict]):
        return "fake-llm-summary"

    def fake_analyze_url(url: str):
        return {
            "status": "success",
            "title": "Example",
            "description": "Example description",
            "author": "Author",
            "platform": "web",
            "site_name": "example",
        }

    mission_counter = {"value": 0}

    def fake_create_collection_mission(*args, **kwargs):
        mission_counter["value"] += 1
        return SimpleNamespace(id=f"mission-{mission_counter['value']}")

    monkeypatch.setattr(public_runtime["url_analysis_module"], "analyze_url", fake_analyze_url)
    monkeypatch.setattr(public_runtime["url_analysis_module"].llm, "analyze_url", fake_llm_analyze_url)
    monkeypatch.setattr(public_runtime["collection_module"], "create_collection_mission", fake_create_collection_mission)
    monkeypatch.setattr(public_runtime["missions_module"], "create_collection_mission", fake_create_collection_mission)


def test_public_high_cost_endpoints_are_rate_limited_without_real_network_or_llm(public_runtime, monkeypatch):
    client = public_runtime["client"]
    _patch_public_limiter(public_runtime, monkeypatch)
    _patch_public_dependencies(public_runtime, monkeypatch)

    analyze_ok = client.post(
        "/api/analyze-url",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"url": "https://example.test"},
    )
    analyze_limited = client.post(
        "/api/analyze-url",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"url": "https://example.test"},
    )
    search_ok = client.get("/api/search", headers={"X-Forwarded-For": "198.51.100.20"}, params={"q": "victory"})
    search_limited = client.get("/api/search", headers={"X-Forwarded-For": "198.51.100.20"}, params={"q": "victory"})
    collection_ok = client.post(
        "/api/collection/start",
        headers={"X-Forwarded-For": "198.51.100.30"},
        json={"keywords": ["victory"], "source": "newsapi"},
    )
    collection_limited = client.post(
        "/api/collection/start",
        headers={"X-Forwarded-For": "198.51.100.30"},
        json={"keywords": ["victory"], "source": "newsapi"},
    )
    missions_ok = client.post(
        "/api/missions",
        headers={"X-Forwarded-For": "198.51.100.40"},
        params={"query": "victory"},
    )
    missions_limited = client.post(
        "/api/missions",
        headers={"X-Forwarded-For": "198.51.100.40"},
        params={"query": "victory"},
    )

    assert analyze_ok.status_code == 200
    assert analyze_limited.status_code == 429
    assert analyze_limited.headers["Retry-After"] == "60"
    assert analyze_limited.json()["detail"]["error_code"] == "RATE_LIMITED"

    assert search_ok.status_code == 200
    assert search_limited.status_code == 429
    assert search_limited.headers["Retry-After"] == "60"

    assert collection_ok.status_code == 200
    assert collection_limited.status_code == 429
    assert collection_limited.headers["Retry-After"] == "60"

    assert missions_ok.status_code == 200
    assert missions_limited.status_code == 429
    assert missions_limited.headers["Retry-After"] == "60"


def test_public_rate_limit_keys_are_independent_per_ip(public_runtime, monkeypatch):
    client = public_runtime["client"]
    _patch_public_limiter(public_runtime, monkeypatch)
    _patch_public_dependencies(public_runtime, monkeypatch)

    first_ip = client.get("/api/search", headers={"X-Forwarded-For": "203.0.113.10"}, params={"q": "victory"})
    blocked_first_ip = client.get("/api/search", headers={"X-Forwarded-For": "203.0.113.10"}, params={"q": "victory"})
    second_ip = client.get("/api/search", headers={"X-Forwarded-For": "203.0.113.11"}, params={"q": "victory"})

    assert first_ip.status_code == 200
    assert blocked_first_ip.status_code == 429
    assert second_ip.status_code == 200
