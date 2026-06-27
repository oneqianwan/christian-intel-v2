from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import Source, get_db
from services.health_check import check_source_health, run_health_check

router = APIRouter()


@router.get("/health")
def app_health():
    return {"status": "ok"}


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
