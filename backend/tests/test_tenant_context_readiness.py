from __future__ import annotations

from test_production_readiness_startup_checks import startup_runtime


def test_tenant_context_and_scope_readiness_flags(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()

    assert report["tenant_readiness"]["tenant_core_models_ready"] is True
    assert report["tenant_readiness"]["tenant_membership_ready"] is True
    assert report["tenant_readiness"]["tenant_user_default_tenant_ready"] is True
    assert report["tenant_readiness"]["tenant_context_ready"] is True
    assert report["tenant_readiness"]["tenant_scope_helper_ready"] is True
    assert report["tenant_readiness"]["tenant_admin_boundary_ready"] == "partial"
    assert report["tenant_readiness"]["tenant_isolation_readiness"] == "blocked"
    assert report["tenant_readiness"]["controlled_beta_tenant_ready"] is False


def test_production_auth_readiness_stays_ready_and_public_saas_blockers_stay_correct(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )

    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])
    assert controlled_beta_auth_ready is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert "production_authentication_not_fully_validated" not in reasons
    assert "multi_tenant_isolation_not_fully_validated" in reasons
