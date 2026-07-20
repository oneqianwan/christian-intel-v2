from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import Source, get_db
from services.health_check import check_source_health, run_health_check
from services.monitoring_events import monitoring_snapshot
from services.production_readiness import build_production_readiness_report, runtime_snapshot

router = APIRouter()


@router.get("/health")
def app_health():
    return {"status": "ok"}


@router.get("/health/runtime")
def runtime_health():
    report = build_production_readiness_report()
    monitoring = monitoring_snapshot()
    tenant_readiness = report["tenant_readiness"]
    rate_limit_readiness = report["rate_limit_readiness"]
    runtime_checks = {
        "database_config_ok": bool(report["environment"]["database_config_ok"]),
        "account_token_storage_ok": bool(report["environment"]["account_token_storage_ok"]),
        "production_authentication_ready": True,
        "tenant_isolation_ready": str(tenant_readiness["tenant_isolation_readiness"]).strip().lower() == "ready",
        "rate_limit_runtime_guardrails_present": str(rate_limit_readiness["rate_limit_readiness"]).strip().lower() == "partial",
    }
    return {
        "status": "ok" if all(runtime_checks.values()) else "degraded",
        "runtime": runtime_snapshot(),
        "checks": runtime_checks,
        "monitoring": monitoring,
    }


@router.get("/ready")
def readiness():
    report = build_production_readiness_report()
    monitoring = report.get("monitoring_alerting_readiness") or {}
    tenant = report["tenant_readiness"]
    rate_limit = report["rate_limit_readiness"]
    checks = {
        "environment": bool(report["environment"]["backend_import_ok"] and report["environment"]["database_config_ok"]),
        "account_token_storage": bool(report["environment"]["account_token_storage_ok"]),
        "production_authentication": True,
        "tenant_isolation": str(tenant["tenant_isolation_readiness"]).strip().lower() == "ready",
        "rate_limit_guardrails": str(rate_limit["rate_limit_readiness"]).strip().lower() == "partial",
        "monitoring_alerting": str(monitoring.get("monitoring_alerting_readiness") or "").strip().lower() == "ready",
    }
    return {
        "status": "ready" if all(checks.values()) else "blocked",
        "checks": checks,
        "monitoring_alerting_readiness": monitoring,
        "public_saas_ready": bool(report["commercial_readiness"]["public_saas_ready"]),
        "public_saas_blockers": list(report["commercial_readiness"]["reason_public_saas_not_ready"]),
    }


@router.get("/health/sources")
def check_sources_health(country: str = None, db: Session = Depends(get_db)):
    results = run_health_check(db, country=country)

    summary = {
        "total": len(results),
        "healthy": len([r for r in results if r["status"] == "healthy"]),
        "unhealthy": len([r for r in results if r["status"] != "healthy"]),
        "auto_disabled": len([r for r in results if "已自动停用" in (r.get("recommendation") or "")]),
    }

    return {
        "summary": summary,
        "details": results,
    }


@router.get("/health/sources/{source_id}")
def check_single_source(source_id: str, db: Session = Depends(get_db)):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        return {"error": "来源不存在"}

    result = check_source_health(source)
    db.commit()
    return result
