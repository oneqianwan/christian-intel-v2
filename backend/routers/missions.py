from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db, Mission, JobRun, IntelligenceItem, Source
from queue_client import DEFAULT_COLLECTION_PRIORITY, HIGH_COLLECTION_PRIORITY
from services.mission_service import create_collection_mission

router = APIRouter()


@router.post("/missions")
def create_mission(
    query: str,
    country: str = "菲律宾",
    priority: int = HIGH_COLLECTION_PRIORITY,
    db: Session = Depends(get_db),
):
    mission = create_collection_mission(
        query=query,
        country=country,
        priority=priority or DEFAULT_COLLECTION_PRIORITY,
        db=db,
    )
    mission_id = mission.id if mission else None
    if not mission_id:
        return {"mission_id": None, "status": "skipped", "priority": priority or DEFAULT_COLLECTION_PRIORITY}
    return {"mission_id": mission_id, "status": "queued", "priority": priority or DEFAULT_COLLECTION_PRIORITY}


@router.get("/missions/{mission_id}")
def get_mission(mission_id: str, db: Session = Depends(get_db)):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        return {"error": "mission not found"}

    jobs = db.query(JobRun).filter(JobRun.mission_id == mission_id).all()

    # 统计情报条目
    item_count = db.query(IntelligenceItem).join(Source).filter(
        Source.country == mission.country,
        IntelligenceItem.ingested_at >= mission.created_at
    ).count()

    return {
        "mission": {
            "id": mission.id,
            "query": mission.query,
            "country": mission.country,
            "status": mission.status,
            "created_at": mission.created_at.isoformat(),
        },
        "jobs": [{"id": j.id, "type": j.job_type, "status": j.status} for j in jobs],
        "intelligence_count": item_count
    }
