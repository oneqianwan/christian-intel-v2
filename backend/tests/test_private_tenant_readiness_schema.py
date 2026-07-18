from __future__ import annotations

from test_production_readiness_startup_checks import startup_runtime


def test_private_tenant_readiness_flags_are_present(startup_runtime):
    checker = startup_runtime["readiness_module"].ProductionReadinessChecker()
    report = checker.build_report()
    tenant_readiness = report["tenant_readiness"]

    assert tenant_readiness["private_tenant_schema_ready"] in {"yes", "partial"}
    assert tenant_readiness["private_tenant_migration_ready"] in {"yes", "partial"}
    assert tenant_readiness["conversation_tenant_id_ready"] == "yes"
    assert tenant_readiness["message_tenant_id_ready"] == "yes"
    assert tenant_readiness["bookmark_tenant_id_ready"] == "yes"
    assert tenant_readiness["feedback_tenant_id_ready"] == "yes"
    assert tenant_readiness["watch_alert_tenant_id_ready"] in {"yes", "partial"}
    assert tenant_readiness["diagnostics_tenant_id_ready"] in {"yes", "partial"}
    assert tenant_readiness["user_profile_tenant_id_ready"] in {"yes", "partial"}
    assert tenant_readiness["task_tenant_id_ready"] in {"yes", "partial"}
    assert tenant_readiness["public_tables_remain_global"] is True
    assert tenant_readiness["tenant_isolation_readiness"] == "partial"
    assert tenant_readiness["controlled_beta_tenant_ready"] is False


def test_public_saas_blockers_remain_correct_after_private_schema_work(startup_runtime):
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
    assert report["tenant_readiness"]["tenant_isolation_readiness"] == "partial"
    assert "production_authentication_not_fully_validated" not in reasons
    assert "multi_tenant_isolation_not_fully_validated" in reasons
