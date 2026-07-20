from __future__ import annotations

from test_production_readiness_startup_checks import startup_runtime


def test_monitoring_readiness_is_ready_and_blocker_is_removed(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()

    monitoring = report["monitoring_alerting_readiness"]
    tenant = report["tenant_readiness"]
    rate_limit = report["rate_limit_readiness"]
    blockers = set(report["commercial_readiness"]["reason_public_saas_not_ready"])

    assert monitoring["monitoring_alerting_readiness"] == "ready"
    assert monitoring["runtime_health_endpoint_ready"] == "yes"
    assert monitoring["readiness_endpoint_ready"] == "yes"
    assert monitoring["metrics_snapshot_ready"] == "yes"
    assert monitoring["internal_monitoring_event_sink_ready"] == "yes"
    assert monitoring["internal_alert_sink_ready"] == "yes"
    assert monitoring["rate_limit_trip_monitoring_ready"] == "yes"
    assert monitoring["auth_failure_monitoring_ready"] == "yes"
    assert monitoring["tenant_isolation_denial_monitoring_ready"] == "yes"
    assert monitoring["background_job_failure_monitoring_ready"] == "yes"

    assert tenant["tenant_isolation_readiness"] == "ready"
    assert rate_limit["rate_limit_readiness"] == "partial"
    assert tenant["controlled_beta_tenant_ready"] is False
    assert report["commercial_readiness"]["public_saas_ready"] is False

    assert "monitoring_alerting_not_fully_validated" not in blockers
    assert "billing_not_implemented" in blockers
    assert "rate_limit_not_fully_validated" in blockers
    assert "backup_recovery_not_fully_validated" in blockers
    assert "deployment_health_checks_not_fully_validated" in blockers
    assert "production_authentication_not_fully_validated" not in blockers
    assert "multi_tenant_isolation_not_fully_validated" not in blockers
