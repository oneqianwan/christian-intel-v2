from __future__ import annotations

import importlib
import os
import socket
import sys
import uuid
from pathlib import Path

import httpx
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


MODULES_TO_PURGE = [
    "models",
    "models.database",
    "models.auth",
    "models.watch_alert",
    "services",
    "services.organization_resolver",
]


def _purge_modules() -> None:
    for module_name in MODULES_TO_PURGE:
        sys.modules.pop(module_name, None)


@pytest.fixture()
def resolver_runtime(tmp_path: Path):
    test_db_path = tmp_path / f"organization_resolver_contract_{uuid.uuid4().hex}.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    _purge_modules()

    database = importlib.import_module("models.database")
    importlib.import_module("models.auth")
    importlib.import_module("models.watch_alert")
    resolver_module = importlib.import_module("services.organization_resolver")
    database.init_db()

    yield {
        "database": database,
        "resolver_module": resolver_module,
    }

    database.engine.dispose()
    _purge_modules()
    if test_db_path.exists():
        test_db_path.unlink()


def test_result_contract_contains_expected_fields_and_confidence_range(resolver_runtime):
    resolver = resolver_runtime["resolver_module"].OrganizationResolver()

    result = resolver.resolve_organization("Give me Victory Philippines contact info")

    assert set(result.keys()) >= {
        "input_query",
        "normalized_query",
        "organization_name",
        "organization_id",
        "canonical_name",
        "target_organization_name",
        "target_organization_id",
        "target_canonical_name",
        "resolution_status",
        "confidence",
        "candidates",
        "target_candidates",
        "missing_parameters",
        "context_reference",
        "requires_previous_organization",
        "reason_codes",
        "warnings",
    }
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["resolution_status"] == "resolved"
    assert result["organization_name"] == "Victory Philippines"
    assert result["candidates"][0]["match_type"] == "extracted_only"
    assert 0.0 <= result["candidates"][0]["confidence"] <= 1.0


def test_missing_organization_returns_missing_parameters(resolver_runtime):
    resolver = resolver_runtime["resolver_module"].OrganizationResolver()

    result = resolver.resolve_organization("推荐合作对象有哪些？")

    assert result["organization_name"] is None
    assert result["resolution_status"] == "missing"
    assert "organization_name" in result["missing_parameters"]


def test_context_reference_returns_context_required(resolver_runtime):
    resolver = resolver_runtime["resolver_module"].OrganizationResolver()

    result = resolver.resolve_organization("Contact info for this organization")

    assert result["organization_name"] is None
    assert result["resolution_status"] == "context_required"
    assert result["context_reference"] is True
    assert result["requires_previous_organization"] is True
    assert "context_reference_requires_previous_organization" in result["warnings"]


def test_resolver_does_not_call_network_or_llm(monkeypatch, resolver_runtime):
    resolver = resolver_runtime["resolver_module"].OrganizationResolver()

    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network not allowed")))
    monkeypatch.setattr(httpx, "request", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("httpx not allowed")))

    result = resolver.resolve_organization("Victory Philippines 怎么联系")

    assert result["organization_name"] == "Victory Philippines"
    assert result["resolution_status"] == "resolved"
