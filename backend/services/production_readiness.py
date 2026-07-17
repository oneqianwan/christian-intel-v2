from __future__ import annotations

import importlib
import inspect as pyinspect
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
        private_tenant_schema = self._check_private_tenant_schema(imports=imports)
        private_router_binding = self._check_private_router_tenant_binding(imports=imports)
        tenant_context_ready = self._check_tenant_context_ready()
        tenant_scope_helper_ready = self._check_tenant_scope_helper_ready()
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
        conversation_router_tenant_scoped = bool(private_router_binding["conversation_router_tenant_scoped_ready"])
        message_router_tenant_scoped = bool(private_router_binding["message_router_tenant_scoped_ready"])
        chat_message_tenant_write_ready = bool(private_router_binding["chat_message_tenant_write_ready"])
        conversation_cross_tenant_isolation_ready = bool(
            conversation_router_tenant_scoped and private_tenant_schema["conversation_tenant_id_ready"] == "yes"
        )
        message_cross_tenant_isolation_ready = bool(
            message_router_tenant_scoped and private_tenant_schema["message_tenant_id_ready"] == "yes"
        )
        private_router_tenant_binding_ready = (
            "partial"
            if conversation_cross_tenant_isolation_ready and message_cross_tenant_isolation_ready and chat_message_tenant_write_ready
            else "no"
        )
        tenant_isolation_readiness = "blocked"
        reason_tenant_isolation_not_ready = [
            "remaining_private_routers_not_yet_tenant_scoped",
            "cross_tenant_private_data_tests_not_completed",
        ]
        return {
            "tenant_core_models_ready": tenant_core_models_ready,
            "tenant_context_ready": bool(tenant_context_ready),
            "tenant_membership_ready": tenant_membership_ready,
            "tenant_scope_helper_ready": bool(tenant_scope_helper_ready),
            "tenant_user_default_tenant_ready": tenant_user_default_tenant_ready,
            "private_tenant_schema_ready": private_tenant_schema["private_tenant_schema_ready"],
            "private_tenant_migration_ready": private_tenant_schema["private_tenant_migration_ready"],
            "conversation_tenant_id_ready": private_tenant_schema["conversation_tenant_id_ready"],
            "message_tenant_id_ready": private_tenant_schema["message_tenant_id_ready"],
            "bookmark_tenant_id_ready": private_tenant_schema["bookmark_tenant_id_ready"],
            "feedback_tenant_id_ready": private_tenant_schema["feedback_tenant_id_ready"],
            "watch_alert_tenant_id_ready": private_tenant_schema["watch_alert_tenant_id_ready"],
            "diagnostics_tenant_id_ready": private_tenant_schema["diagnostics_tenant_id_ready"],
            "user_profile_tenant_id_ready": private_tenant_schema["user_profile_tenant_id_ready"],
            "task_tenant_id_ready": private_tenant_schema["task_tenant_id_ready"],
            "public_tables_remain_global": private_tenant_schema["public_tables_remain_global"],
            "conversation_router_tenant_scoped_ready": conversation_router_tenant_scoped,
            "message_router_tenant_scoped_ready": message_router_tenant_scoped,
            "conversation_cross_tenant_isolation_ready": conversation_cross_tenant_isolation_ready,
            "message_cross_tenant_isolation_ready": message_cross_tenant_isolation_ready,
            "chat_message_tenant_write_ready": chat_message_tenant_write_ready,
            "private_router_tenant_binding_ready": private_router_tenant_binding_ready,
            "tenant_admin_boundary_ready": "partial" if tenant_context_ready and tenant_scope_helper_ready else "no",
            "tenant_isolation_readiness": tenant_isolation_readiness,
            "controlled_beta_tenant_ready": False,
            "reason_tenant_isolation_not_ready": reason_tenant_isolation_not_ready,
            "schema": tenant_schema,
            "private_schema": private_tenant_schema["schema"],
            "private_router_binding": private_router_binding,
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

    def _check_tenant_context_ready(self) -> bool:
        try:
            module = importlib.import_module("dependencies.tenant_context")
            required = (
                "TenantRequestContext",
                "get_current_tenant_context",
                "get_current_tenant",
                "get_current_membership",
                "require_tenant_member",
                "require_tenant_admin",
                "require_tenant_role",
            )
            return all(hasattr(module, name) for name in required)
        except Exception:
            return False

    def _check_tenant_scope_helper_ready(self) -> bool:
        try:
            module = importlib.import_module("services.tenant_scope")
            required = (
                "filter_by_tenant",
                "assert_same_tenant",
                "ensure_tenant_id_for_create",
                "require_record_tenant",
                "build_tenant_scope_metadata",
            )
            return all(hasattr(module, name) for name in required)
        except Exception:
            return False

    def _check_private_tenant_schema(self, *, imports: dict[str, Any]) -> dict[str, Any]:
        database_module = imports["imports"].get("config")
        if database_module is None:
            return {
                "private_tenant_schema_ready": "no",
                "private_tenant_migration_ready": "no",
                "conversation_tenant_id_ready": "no",
                "message_tenant_id_ready": "no",
                "bookmark_tenant_id_ready": "no",
                "feedback_tenant_id_ready": "no",
                "watch_alert_tenant_id_ready": "no",
                "diagnostics_tenant_id_ready": "no",
                "user_profile_tenant_id_ready": "no",
                "task_tenant_id_ready": "no",
                "public_tables_remain_global": False,
                "schema": {},
            }

        required_indexes = {
            "conversations": {
                "ix_conversations_tenant_id",
                "ix_conversations_tenant_id_created_at",
                "ix_conversations_tenant_owner_user_id",
            },
            "messages": {
                "ix_messages_tenant_id",
                "ix_messages_tenant_id_created_at",
                "ix_messages_tenant_conversation_id",
            },
            "bookmarks": {
                "ix_bookmarks_tenant_id",
                "ix_bookmarks_tenant_id_created_at",
                "ix_bookmarks_tenant_user_id",
            },
            "user_feedbacks": {
                "ix_user_feedbacks_tenant_id",
                "ix_user_feedbacks_tenant_id_created_at",
                "ix_user_feedbacks_tenant_user_id",
            },
            "watch_targets": {
                "ix_watch_targets_tenant_id",
                "ix_watch_targets_tenant_created_at",
                "ix_watch_targets_tenant_user_id",
                "ix_watch_targets_tenant_owner_user_id",
                "ix_watch_targets_tenant_entity_id",
            },
            "signals": {
                "ix_signals_tenant_id",
                "ix_signals_tenant_detected_at",
                "ix_signals_tenant_owner_user_id",
                "ix_signals_tenant_watch_target_id",
                "ix_signals_tenant_entity_id",
            },
            "alert_rules": {
                "ix_alert_rules_tenant_id",
                "ix_alert_rules_tenant_created_at",
                "ix_alert_rules_tenant_user_id",
            },
            "alerts": {
                "ix_alerts_tenant_id",
                "ix_alerts_tenant_created_at",
                "ix_alerts_tenant_user_id",
                "ix_alerts_tenant_owner_user_id",
                "ix_alerts_tenant_watch_target_id",
                "ix_alerts_tenant_signal_id",
            },
            "request_traces": {
                "ix_request_traces_tenant_id",
                "ix_request_traces_tenant_id_created_at",
            },
            "user_profiles": {
                "ix_user_profiles_tenant_id",
                "ix_user_profiles_tenant_id_created_at",
                "ix_user_profiles_tenant_session_id",
            },
            "tasks": {
                "ix_tasks_tenant_id",
                "ix_tasks_tenant_id_created_at",
                "ix_tasks_tenant_entity_id",
            },
        }
        public_tables = {
            "organization_profiles",
            "knowledge_entities",
            "sources",
            "pages",
            "intelligence_items",
            "relation_edges",
            "funding_rounds",
            "investments",
            "organization_types",
            "theological_positions",
        }

        try:
            import models.database as runtime_database

            inspector = inspect(runtime_database.engine)
            tables = set(inspector.get_table_names())

            def _table_ready(table_name: str) -> bool:
                if table_name not in tables:
                    return False
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                indexes = {index["name"] for index in inspector.get_indexes(table_name)}
                return "tenant_id" in columns and required_indexes.get(table_name, set()).issubset(indexes)

            conversation_ready = _table_ready("conversations")
            message_ready = _table_ready("messages")
            bookmark_ready = _table_ready("bookmarks")
            feedback_ready = _table_ready("user_feedbacks")
            watch_target_ready = _table_ready("watch_targets")
            signal_ready = _table_ready("signals")
            alert_rule_ready = _table_ready("alert_rules")
            alert_ready = _table_ready("alerts")
            request_trace_ready = _table_ready("request_traces")
            user_profile_ready = _table_ready("user_profiles")
            task_ready = _table_ready("tasks")

            public_tables_remain_global = True
            public_table_violations: list[str] = []
            for table_name in sorted(public_tables & tables):
                columns = {column["name"] for column in inspector.get_columns(table_name)}
                if "tenant_id" in columns:
                    public_tables_remain_global = False
                    public_table_violations.append(table_name)

            migration_file_found = (Path(__file__).resolve().parents[1] / "scripts" / "migrate_tenant_private_v1.py").exists()
            all_private_tables_ready = all(
                (
                    conversation_ready,
                    message_ready,
                    bookmark_ready,
                    feedback_ready,
                    watch_target_ready,
                    signal_ready,
                    alert_rule_ready,
                    alert_ready,
                    request_trace_ready,
                    user_profile_ready,
                    task_ready,
                )
            )
            private_tenant_schema_ready = (
                "yes" if all_private_tables_ready and public_tables_remain_global else "partial" if public_tables_remain_global else "no"
            )
            private_tenant_migration_ready = (
                "partial"
                if migration_file_found and private_tenant_schema_ready in {"yes", "partial"}
                else "no"
            )
            watch_alert_ready = (
                "yes" if all((watch_target_ready, signal_ready, alert_rule_ready, alert_ready)) else "partial" if any((watch_target_ready, signal_ready, alert_rule_ready, alert_ready)) else "no"
            )
            return {
                "private_tenant_schema_ready": private_tenant_schema_ready,
                "private_tenant_migration_ready": private_tenant_migration_ready,
                "conversation_tenant_id_ready": "yes" if conversation_ready else "no",
                "message_tenant_id_ready": "yes" if message_ready else "no",
                "bookmark_tenant_id_ready": "yes" if bookmark_ready else "no",
                "feedback_tenant_id_ready": "yes" if feedback_ready else "no",
                "watch_alert_tenant_id_ready": watch_alert_ready,
                "diagnostics_tenant_id_ready": "partial" if request_trace_ready else "no",
                "user_profile_tenant_id_ready": "partial" if user_profile_ready else "no",
                "task_tenant_id_ready": "partial" if task_ready else "no",
                "public_tables_remain_global": public_tables_remain_global,
                "schema": {
                    "migration_file_found": migration_file_found,
                    "public_table_violations": public_table_violations,
                    "conversation_ready": conversation_ready,
                    "message_ready": message_ready,
                    "bookmark_ready": bookmark_ready,
                    "feedback_ready": feedback_ready,
                    "watch_target_ready": watch_target_ready,
                    "signal_ready": signal_ready,
                    "alert_rule_ready": alert_rule_ready,
                    "alert_ready": alert_ready,
                    "request_trace_ready": request_trace_ready,
                    "user_profile_ready": user_profile_ready,
                    "task_ready": task_ready,
                },
            }
        except Exception:
            return {
                "private_tenant_schema_ready": "no",
                "private_tenant_migration_ready": "no",
                "conversation_tenant_id_ready": "no",
                "message_tenant_id_ready": "no",
                "bookmark_tenant_id_ready": "no",
                "feedback_tenant_id_ready": "no",
                "watch_alert_tenant_id_ready": "no",
                "diagnostics_tenant_id_ready": "no",
                "user_profile_tenant_id_ready": "no",
                "task_tenant_id_ready": "no",
                "public_tables_remain_global": False,
                "schema": {},
            }

    def _check_private_router_tenant_binding(self, *, imports: dict[str, Any]) -> dict[str, Any]:
        try:
            conversations_module = importlib.import_module("routers.conversations")
            chat_module = importlib.import_module("routers.chat")
            chat_ownership_module = importlib.import_module("services.chat_ownership")
            tenant_context_module = importlib.import_module("dependencies.tenant_context")
            tenant_scope_module = importlib.import_module("services.tenant_scope")

            conversations_source = Path(conversations_module.__file__).read_text(encoding="utf-8")
            chat_source = Path(chat_module.__file__).read_text(encoding="utf-8")
            chat_ownership_source = Path(chat_ownership_module.__file__).read_text(encoding="utf-8")

            chat_simple_signature = pyinspect.signature(chat_module.chat_simple)
            chat_stream_signature = pyinspect.signature(chat_module.chat_stream)
            request_signature_ready = "raw_request" in chat_simple_signature.parameters and "request" in chat_stream_signature.parameters

            helper_ready = all(
                hasattr(chat_ownership_module, name)
                for name in (
                    "resolve_chat_tenant_context",
                    "apply_conversation_access_scope",
                    "list_messages_for_conversation",
                )
            )
            tenant_dependency_ready = hasattr(tenant_context_module, "resolve_tenant_request_context")
            tenant_scope_ready = all(
                hasattr(tenant_scope_module, name)
                for name in ("filter_by_tenant", "ensure_tenant_id_for_create", "require_record_tenant")
            )
            conversation_router_tenant_scoped = bool(
                helper_ready
                and tenant_dependency_ready
                and tenant_scope_ready
                and "resolve_chat_tenant_context(" in conversations_source
                and "apply_conversation_access_scope(" in conversations_source
                and "current_tenant=current_tenant_id" in conversations_source
            )
            message_router_tenant_scoped = bool(
                helper_ready
                and tenant_scope_ready
                and "list_messages_for_conversation(" in conversations_source
                and "filter_by_tenant(query, Message" in chat_ownership_source
            )
            chat_message_tenant_write_ready = bool(
                request_signature_ready
                and helper_ready
                and tenant_scope_ready
                and "resolve_chat_tenant_context(" in chat_source
                and 'tenant_id=message_tenant_payload.get("tenant_id")' in chat_source
                and 'tenant_id=assistant_message_tenant_payload.get("tenant_id")' in chat_source
            )
            return {
                "conversation_router_tenant_scoped_ready": conversation_router_tenant_scoped,
                "message_router_tenant_scoped_ready": message_router_tenant_scoped,
                "chat_message_tenant_write_ready": chat_message_tenant_write_ready,
                "tenant_context_dependency_used": tenant_dependency_ready,
                "tenant_scope_helper_used": tenant_scope_ready,
            }
        except Exception:
            return {
                "conversation_router_tenant_scoped_ready": False,
                "message_router_tenant_scoped_ready": False,
                "chat_message_tenant_write_ready": False,
                "tenant_context_dependency_used": False,
                "tenant_scope_helper_used": False,
            }


def build_production_readiness_report(*, contracts: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return ProductionReadinessChecker().build_report(contracts=contracts)


def runtime_snapshot() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
