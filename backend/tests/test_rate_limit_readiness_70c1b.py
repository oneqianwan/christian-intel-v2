from __future__ import annotations

from test_production_readiness_startup_checks import startup_runtime


def test_rate_limit_readiness_is_partial_after_c1b(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    imports = checker._collect_imports()
    controlled_beta_auth_ready = checker._is_controlled_beta_auth_ready(
        settings=imports.get("settings"),
        environment=report["environment"],
    )

    tenant_readiness = report["tenant_readiness"]
    rate_limit_readiness = report["rate_limit_readiness"]
    reasons = set(report["commercial_readiness"]["reason_public_saas_not_ready"])

    assert rate_limit_readiness["expected_rate_limit_readiness_after_c1b"] == "partial"
    assert rate_limit_readiness["in_memory_rate_limiter_ready"] == "yes"
    assert rate_limit_readiness["rate_limit_429_contract_ready"] == "yes"
    assert rate_limit_readiness["auth_login_rate_limit_ready"] in {"yes", "partial"}
    assert rate_limit_readiness["public_high_cost_endpoint_rate_limit_ready"] in {"yes", "partial"}
    assert rate_limit_readiness["chat_rate_limit_ready"] == "yes"
    assert rate_limit_readiness["watch_run_rate_limit_ready"] == "yes"
    assert rate_limit_readiness["per_tenant_rate_limit_ready"] == "partial"
    assert rate_limit_readiness["per_user_rate_limit_ready"] == "partial"
    assert rate_limit_readiness["per_ip_rate_limit_ready"] == "partial"
    assert rate_limit_readiness["rate_limit_readiness"] == "partial"

    assert report["environment"]["account_token_storage_ok"] is True
    assert controlled_beta_auth_ready is True
    assert tenant_readiness["tenant_isolation_readiness"] == "ready"
    assert tenant_readiness["controlled_beta_tenant_ready"] is False
    assert report["commercial_readiness"]["public_saas_ready"] is False

    assert "billing_not_implemented" in reasons
    assert "rate_limit_not_fully_validated" in reasons
    assert "monitoring_alerting_not_fully_validated" not in reasons
    assert "backup_recovery_not_fully_validated" in reasons
    assert "deployment_health_checks_not_fully_validated" in reasons
    assert "production_authentication_not_fully_validated" not in reasons
    assert "multi_tenant_isolation_not_fully_validated" not in reasons
