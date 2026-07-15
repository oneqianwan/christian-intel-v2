from __future__ import annotations

import importlib
import os
import platform
import sys
from pathlib import Path
from typing import Any, Optional

from .audit_trail import AuditTrailRedactor
from .observability import ResponseObservabilityBuilder
from .response_contract import ResponseContractBuilder


class ProductionReadinessChecker:
    READINESS_VERSION = "6.0F"
    STATUS_VALUES = {"ready", "degraded", "blocked"}
    MODULE_STATUS_PASS = "pass"
    MODULE_STATUS_FAIL = "fail"
    CONTRACT_STATUS_PASS = "pass"
    CONTRACT_STATUS_FAIL = "fail"
    MODULE_PAYLOAD_MAP = {
        "score_lookup": "score_snapshot",
        "relationship_graph": "relationship_graph",
        "contact_intelligence": "contact_intelligence",
        "partnership_recommendation": "partnership_recommendation",
        "partnership_action_plan": "partnership_action_plan",
        "partnership_evidence_brief": "partnership_evidence_brief",
    }
    REQUIRED_MODULES = {
        "config": "config",
        "brain": "services.brain",
        "intent_router": "services.intent_router_final",
        "organization_resolver": "services.organization_resolver",
        "brain_orchestrator": "services.brain_orchestrator",
        "response_contract": "services.response_contract",
        "observability": "services.observability",
        "audit_trail": "services.audit_trail",
        "production_readiness": "services.production_readiness",
    }
    REQUIRED_FILES = [
        "services/brain.py",
        "services/brain_orchestrator.py",
        "services/response_contract.py",
        "services/observability.py",
        "services/audit_trail.py",
    ]

    def __init__(self) -> None:
        self.redactor = AuditTrailRedactor()

    def build_report(self, *, contracts: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        contracts = [item for item in (contracts or []) if isinstance(item, dict)]
        imports = self._collect_imports()
        settings = imports.get("settings")
        environment = self._build_environment(imports=imports, settings=settings)
        core_brain = self._build_core_brain(imports=imports, contracts=contracts)
        safety = self._build_safety(contracts=contracts)
        modules = self._build_modules(contracts=contracts)
        contracts_status = self._build_contracts(contracts=contracts)

        warnings: list[str] = []
        errors: list[str] = []
        risk_notes: list[str] = []

        if environment["dangerous_debug_mode"]:
            warnings.append("dangerous_debug_mode_detected")
        if not environment["required_env_present"]:
            errors.append("required_environment_missing")
        if not environment["backend_import_ok"]:
            errors.append("backend_import_failed")
        if not environment["database_config_ok"]:
            errors.append("database_config_invalid")

        if not safety["redaction_enabled"]:
            errors.append("redaction_disabled")
        if not safety["no_llm_for_structured_lookup"]:
            errors.append("structured_lookup_llm_guard_missing")
        if not safety["no_network_for_structured_lookup"]:
            errors.append("structured_lookup_network_guard_missing")
        if not safety["no_fabrication"]:
            errors.append("fabrication_guard_missing")

        commercial_readiness = self._build_commercial_readiness()
        risk_notes.extend(commercial_readiness["reason_public_saas_not_ready"])

        critical_groups = [
            all(environment.values()) or (
                environment["python_ok"]
                and environment["backend_import_ok"]
                and environment["database_config_ok"]
                and environment["required_env_present"]
            ),
            all(core_brain.values()),
            all(safety.values()),
            all(value == self.MODULE_STATUS_PASS for value in modules.values()),
            all(value == self.CONTRACT_STATUS_PASS for value in contracts_status.values()),
        ]
        if errors or not all(critical_groups):
            status = "blocked"
        elif warnings:
            status = "degraded"
        else:
            status = "ready"
        if status not in self.STATUS_VALUES:
            status = "blocked"

        return {
            "readiness_version": self.READINESS_VERSION,
            "status": status,
            "environment": environment,
            "core_brain": core_brain,
            "safety": safety,
            "modules": modules,
            "contracts": contracts_status,
            "warnings": warnings,
            "errors": errors,
            "risk_notes": risk_notes,
            "commercial_readiness": commercial_readiness,
        }

    def _collect_imports(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "imports": {},
            "errors": {},
            "settings": None,
        }
        for key, module_name in self.REQUIRED_MODULES.items():
            try:
                result["imports"][key] = importlib.import_module(module_name)
            except Exception as exc:
                result["imports"][key] = None
                result["errors"][key] = str(exc.__class__.__name__)
        config_module = result["imports"].get("config")
        if config_module is not None:
            try:
                result["settings"] = config_module.Settings()
            except Exception as exc:
                result["errors"]["settings"] = str(exc.__class__.__name__)
        return result

    def _build_environment(self, *, imports: dict[str, Any], settings: Any) -> dict[str, bool]:
        backend_root = Path(__file__).resolve().parents[1]
        files_ok = all((backend_root / relative_path).exists() for relative_path in self.REQUIRED_FILES)
        backend_import_ok = files_ok and all(imports["imports"].get(key) is not None for key in self.REQUIRED_MODULES)
        database_url = str(getattr(settings, "DATABASE_URL", "") or "").strip()
        python_ok = sys.version_info >= (3, 10)
        required_env_present = bool(database_url)
        database_config_ok = bool(database_url and "://" in database_url)
        dangerous_debug_mode = self._detect_dangerous_debug_mode()
        return {
            "python_ok": python_ok,
            "backend_import_ok": backend_import_ok,
            "database_config_ok": database_config_ok,
            "required_env_present": required_env_present,
            "dangerous_debug_mode": dangerous_debug_mode,
        }

    def _build_core_brain(self, *, imports: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, bool]:
        intent_router_ok = imports["imports"].get("intent_router") is not None
        organization_resolver_ok = imports["imports"].get("organization_resolver") is not None
        brain_orchestrator_ok = imports["imports"].get("brain_orchestrator") is not None
        response_contract_ok = imports["imports"].get("response_contract") is not None and (
            not contracts or any(self._is_response_contract_ok(contract) for contract in contracts)
        )
        observability_ok = imports["imports"].get("observability") is not None and (
            not contracts or all(self._has_observability(contract) for contract in contracts)
        )
        return {
            "intent_router_ok": intent_router_ok,
            "organization_resolver_ok": organization_resolver_ok,
            "brain_orchestrator_ok": brain_orchestrator_ok,
            "response_contract_ok": response_contract_ok,
            "observability_ok": observability_ok,
        }

    def _build_safety(self, *, contracts: list[dict[str, Any]]) -> dict[str, bool]:
        payload_whitelist_ok = all(
            str(contract.get("payload_type") or "") in ResponseContractBuilder.PAYLOAD_TYPES for contract in contracts
        ) if contracts else True
        selected_module_ok = all(
            contract.get("selected_module") in ResponseContractBuilder.SELECTED_MODULES for contract in contracts
        ) if contracts else True
        source_ok = all(str(contract.get("source") or "") != "llm" for contract in contracts) if contracts else True
        contract_safety_ok = all(
            ((contract.get("policy") or {}).get("db_first") is True)
            and ((contract.get("policy") or {}).get("allow_llm") is False)
            and ((contract.get("policy") or {}).get("allow_network") is False)
            and ((contract.get("policy") or {}).get("allow_fabrication") is False)
            and ((contract.get("audit") or {}).get("no_llm") is True)
            and ((contract.get("audit") or {}).get("no_network") is True)
            and ((contract.get("audit") or {}).get("no_fabrication") is True)
            for contract in contracts
        ) if contracts else True
        safe_fallback_enabled = any(str(contract.get("route_status") or "") != "ready" for contract in contracts) if contracts else True
        redaction_enabled = self.redactor.redact_text("contact test@example.com") != "contact test@example.com"
        return {
            "db_first": contract_safety_ok,
            "no_llm_for_structured_lookup": contract_safety_ok and source_ok and payload_whitelist_ok and selected_module_ok,
            "no_network_for_structured_lookup": contract_safety_ok,
            "no_fabrication": contract_safety_ok,
            "safe_fallback_enabled": safe_fallback_enabled,
            "redaction_enabled": redaction_enabled,
        }

    def _build_modules(self, *, contracts: list[dict[str, Any]]) -> dict[str, str]:
        result: dict[str, str] = {}
        for module_name, payload_type in self.MODULE_PAYLOAD_MAP.items():
            matched = any(
                str(contract.get("payload_type") or "") == payload_type
                and self._normalize_module_name(str(contract.get("selected_module") or "")) == module_name
                for contract in contracts
            )
            result[module_name] = self.MODULE_STATUS_PASS if matched or not contracts else self.MODULE_STATUS_FAIL
        return result

    def _build_contracts(self, *, contracts: list[dict[str, Any]]) -> dict[str, str]:
        has_any = bool(contracts)
        return {
            "intent_result": self.CONTRACT_STATUS_PASS if (not has_any or all(contract.get("intent") for contract in contracts)) else self.CONTRACT_STATUS_FAIL,
            "organization_resolve_result": self.CONTRACT_STATUS_PASS if (
                not has_any or all(isinstance(contract.get("organization"), dict) for contract in contracts)
            ) else self.CONTRACT_STATUS_FAIL,
            "brain_orchestration_result": self.CONTRACT_STATUS_PASS if (
                not has_any or all(isinstance(contract.get("trace"), list) and contract.get("route_status") for contract in contracts)
            ) else self.CONTRACT_STATUS_FAIL,
            "unified_response_contract": self.CONTRACT_STATUS_PASS if (
                not has_any or all(self._is_response_contract_ok(contract) for contract in contracts)
            ) else self.CONTRACT_STATUS_FAIL,
            "observability_contract": self.CONTRACT_STATUS_PASS if (
                not has_any or all(self._has_observability(contract) for contract in contracts)
            ) else self.CONTRACT_STATUS_FAIL,
        }

    def _build_commercial_readiness(self) -> dict[str, Any]:
        reasons = [
            "production_authentication_not_fully_validated",
            "multi_tenant_isolation_not_fully_validated",
            "billing_not_implemented",
            "rate_limit_not_fully_validated",
            "monitoring_alerting_not_fully_validated",
            "backup_recovery_not_fully_validated",
            "deployment_health_checks_not_fully_validated",
        ]
        return {
            "demo_ready": True,
            "internal_beta_ready": True,
            "public_saas_ready": False,
            "reason_public_saas_not_ready": reasons,
        }

    def _is_response_contract_ok(self, contract: dict[str, Any]) -> bool:
        return (
            str(contract.get("response_contract_version") or "") == ResponseContractBuilder.RESPONSE_CONTRACT_VERSION
            and str(contract.get("payload_type") or "") in ResponseContractBuilder.PAYLOAD_TYPES
            and str(contract.get("source") or "") in ResponseContractBuilder.SOURCES
            and contract.get("selected_module") in ResponseContractBuilder.SELECTED_MODULES
        )

    def _has_observability(self, contract: dict[str, Any]) -> bool:
        observability = contract.get("observability") or {}
        audit_summary = observability.get("audit_summary") or {}
        trace_events = observability.get("trace_events") or []
        return (
            isinstance(observability, dict)
            and str(audit_summary.get("audit_version") or "") == ResponseObservabilityBuilder.AUDIT_VERSION
            and bool(audit_summary.get("trace_id"))
            and bool(audit_summary.get("response_id"))
            and isinstance(trace_events, list)
            and len(trace_events) >= 1
        )

    def _normalize_module_name(self, module_name: str) -> str:
        mapping = {
            "partnership_recommender": "partnership_recommendation",
            "partnership_action_planner": "partnership_action_plan",
        }
        return mapping.get(module_name, module_name)

    def _detect_dangerous_debug_mode(self) -> bool:
        debug_values = {
            str(os.getenv("DEBUG", "")).strip().lower(),
            str(os.getenv("FLASK_DEBUG", "")).strip().lower(),
            str(os.getenv("PYTHON_ENV", "")).strip().lower(),
            str(os.getenv("ENV", "")).strip().lower(),
        }
        return any(value in {"1", "true", "debug", "development"} for value in debug_values)


def build_production_readiness_report(*, contracts: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return ProductionReadinessChecker().build_report(contracts=contracts)


def runtime_snapshot() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
