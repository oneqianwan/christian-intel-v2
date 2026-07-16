from __future__ import annotations

import importlib
import os
import platform
import sys
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import inspect

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
        if not environment["account_token_storage_ok"]:
            errors.append("account_token_storage_missing")

        if not safety["redaction_enabled"]:
            errors.append("redaction_disabled")
        if not safety["no_llm_for_structured_lookup"]:
            errors.append("structured_lookup_llm_guard_missing")
        if not safety["no_network_for_structured_lookup"]:
            errors.append("structured_lookup_network_guard_missing")
        if not safety["no_fabrication"]:
            errors.append("fabrication_guard_missing")

        commercial_readiness = self._build_commercial_readiness(settings=settings, environment=environment)
        tenant_readiness = self._build_tenant_readiness(imports=imports)
        risk_notes.extend(commercial_readiness["reason_public_saas_not_ready"])
        risk_notes.extend(tenant_readiness["reason_tenant_isolation_not_ready"])

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
            "tenant_readiness": tenant_readiness,
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
        account_token_storage_ok = self._check_account_token_storage(imports=imports)
        return {
            "python_ok": python_ok,
            "backend_import_ok": backend_import_ok,
            "database_config_ok": database_config_ok,
            "required_env_present": required_env_present,
            "dangerous_debug_mode": dangerous_debug_mode,
            "account_token_storage_ok": account_token_storage_ok,
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

    def _is_controlled_beta_auth_ready(self, *, settings: Any, environment: dict[str, bool]) -> bool:
        if settings is None:
            return False
        auth_v1_enabled = bool(getattr(settings, "AUTH_V1_ENABLED", False))
        cookie_required = bool(getattr(settings, "AUTH_COOKIE_REQUIRED", False))
        allow_public_flag = bool(getattr(settings, "ALLOW_PUBLIC_CORE_APIS", False))
        allow_public_method = False
        public_enabled = getattr(settings, "public_core_apis_enabled", None)
        if callable(public_enabled):
            try:
                allow_public_method = bool(public_enabled())
            except Exception:
                allow_public_method = False
        allow_public = bool(allow_public_flag or allow_public_method)
        auth_storage_ok = bool(environment.get("account_token_storage_ok"))
        return bool(auth_v1_enabled and cookie_required and (not allow_public) and auth_storage_ok)

    def _build_commercial_readiness(self, *, settings: Any, environment: dict[str, bool]) -> dict[str, Any]:
        controlled_beta_auth_ready = self._is_controlled_beta_auth_ready(settings=settings, environment=environment)
        reasons: list[str] = [
            *(["production_authentication_not_fully_validated"] if not controlled_beta_auth_ready else []),
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

    def _build_tenant_readiness(self, *, imports: dict[str, Any]) -> dict[str, Any]:
        tenant_schema = self._check_tenant_schema(imports=imports)
        tenant_core_models_ready = bool(
            tenant_schema["tenants_table_ok"]
            and tenant_schema["tenant_memberships_table_ok"]
            and tenant_schema["users_default_tenant_ok"]
            and tenant_schema["default_tenant_present"]
        )
        tenant_membership_ready = bool(tenant_schema["tenant_memberships_table_ok"])
        tenant_user_default_tenant_ready = bool(
            tenant_schema["users_default_tenant_ok"] and tenant_schema["default_tenant_present"]
        )
        return {
            "tenant_core_models_ready": tenant_core_models_ready,
            "tenant_membership_ready": tenant_membership_ready,
            "tenant_user_default_tenant_ready": tenant_user_default_tenant_ready,
            "tenant_isolation_readiness": "blocked",
            "controlled_beta_tenant_ready": False,
            "reason_tenant_isolation_not_ready": [
                "private_data_not_yet_tenant_scoped",
                "cross_tenant_private_data_tests_not_completed",
            ],
            "schema": tenant_schema,
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

    def _check_account_token_storage(self, *, imports: dict[str, Any]) -> bool:
        database_module = imports["imports"].get("config")
        if database_module is None:
            return False

        try:
            import models.database as runtime_database

            inspector = inspect(runtime_database.engine)
            tables = set(inspector.get_table_names())
            if "account_tokens" not in tables:
                return False
            columns = {column["name"] for column in inspector.get_columns("account_tokens")}
            required_columns = {
                "id",
                "public_id",
                "user_id",
                "token_hash",
                "purpose",
                "status",
                "expires_at",
                "used_at",
                "created_at",
                "created_by_user_id",
            }
            return required_columns.issubset(columns)
        except Exception:
            return False

    def _check_tenant_schema(self, *, imports: dict[str, Any]) -> dict[str, bool]:
        database_module = imports["imports"].get("config")
        if database_module is None:
            return {
                "tenants_table_ok": False,
                "tenant_memberships_table_ok": False,
                "users_default_tenant_ok": False,
                "default_tenant_present": False,
                "default_membership_present": False,
            }

        try:
            import models.database as runtime_database

            inspector = inspect(runtime_database.engine)
            tables = set(inspector.get_table_names())
            users_columns = (
                {column["name"] for column in inspector.get_columns("users")}
                if "users" in tables
                else set()
            )
            tenants_ok = "tenants" in tables
            memberships_ok = "tenant_memberships" in tables
            default_tenant_present = False
            default_membership_present = False
            if tenants_ok:
                with runtime_database.engine.begin() as conn:
                    default_tenant_present = bool(
                        conn.execute(
                            importlib.import_module("sqlalchemy").text(
                                "SELECT 1 FROM tenants WHERE slug = :slug AND deleted_at IS NULL LIMIT 1"
                            ),
                            {"slug": "default"},
                        ).scalar()
                    )
            if memberships_ok:
                with runtime_database.engine.begin() as conn:
                    default_membership_present = bool(
                        conn.execute(
                            importlib.import_module("sqlalchemy").text(
                                "SELECT 1 FROM tenant_memberships WHERE deleted_at IS NULL LIMIT 1"
                            )
                        ).scalar()
                    )
            return {
                "tenants_table_ok": tenants_ok,
                "tenant_memberships_table_ok": memberships_ok,
                "users_default_tenant_ok": "default_tenant_id" in users_columns,
                "default_tenant_present": default_tenant_present,
                "default_membership_present": default_membership_present,
            }
        except Exception:
            return {
                "tenants_table_ok": False,
                "tenant_memberships_table_ok": False,
                "users_default_tenant_ok": False,
                "default_tenant_present": False,
                "default_membership_present": False,
            }


def build_production_readiness_report(*, contracts: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return ProductionReadinessChecker().build_report(contracts=contracts)


def runtime_snapshot() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
