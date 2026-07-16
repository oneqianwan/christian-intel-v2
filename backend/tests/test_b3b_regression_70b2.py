from __future__ import annotations

import importlib

from test_production_readiness_startup_checks import startup_runtime


def test_b3b_keeps_b2_tenant_context_and_scope_ready(startup_runtime):
    tenant_context = importlib.import_module("dependencies.tenant_context")
    tenant_scope = importlib.import_module("services.tenant_scope")
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()

    assert hasattr(tenant_context, "get_current_tenant_context")
    assert hasattr(tenant_context, "require_tenant_admin")
    assert hasattr(tenant_scope, "filter_by_tenant")
    assert hasattr(tenant_scope, "ensure_tenant_id_for_create")
    assert report["tenant_readiness"]["tenant_context_ready"] is True
    assert report["tenant_readiness"]["tenant_scope_helper_ready"] is True


def test_b3b_keeps_b1_core_and_a3_auth_readiness(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )
    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])

    assert report["tenant_readiness"]["tenant_core_models_ready"] is True
    assert report["tenant_readiness"]["tenant_membership_ready"] is True
    assert report["tenant_readiness"]["tenant_user_default_tenant_ready"] is True
    assert controlled_beta_auth_ready is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert "production_authentication_not_fully_validated" not in reasons
