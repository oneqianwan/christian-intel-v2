from __future__ import annotations

from test_production_readiness_startup_checks import startup_runtime


def test_private_tenant_readiness_final_flags_are_correct(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )
    tenant_readiness = report["tenant_readiness"]
    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])

    assert tenant_readiness["tenant_core_models_ready"] is True
    assert tenant_readiness["tenant_context_ready"] is True
    assert tenant_readiness["tenant_scope_helper_ready"] is True
    assert tenant_readiness["private_tenant_schema_ready"] == "yes"
    assert tenant_readiness["private_tenant_migration_ready"] == "partial"
    assert tenant_readiness["private_router_tenant_binding_ready"] == "yes"
    assert tenant_readiness["cross_tenant_leakage_tests_ready"] is True
    assert tenant_readiness["request_trace_create_injects_tenant_id"] == "yes"
    assert tenant_readiness["alert_runner_tenant_safe"] == "yes"
    assert tenant_readiness["tenant_isolation_readiness"] == "ready"
    assert tenant_readiness["controlled_beta_tenant_ready"] is False
    assert controlled_beta_auth_ready is True
    assert report["commercial_readiness"]["public_saas_ready"] is False
    assert "production_authentication_not_fully_validated" not in reasons
    assert "multi_tenant_isolation_not_fully_validated" not in reasons
    assert "billing_not_implemented" in reasons
    assert "rate_limit_not_fully_validated" in reasons
    assert "monitoring_alerting_not_fully_validated" in reasons
    assert "backup_recovery_not_fully_validated" in reasons
    assert "deployment_health_checks_not_fully_validated" in reasons
    assert "request_trace_create_tenant_injection_not_fully_validated" not in tenant_readiness["reason_tenant_isolation_not_ready"]
    assert "alert_runner_tenant_safety_not_fully_validated" not in tenant_readiness["reason_tenant_isolation_not_ready"]
