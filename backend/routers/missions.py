import uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db, Mission, JobRun, IntelligenceItem, Source
from queue_client import DEFAULT_COLLECTION_PRIORITY, HIGH_COLLECTION_PRIORITY, enqueue_collection_mission

router = APIRouter()


@router.post("/missions")
def create_mission(
    query: str,
    country: str = "菲律宾",
    priority: int = HIGH_COLLECTION_PRIORITY,
    db: Session = Depends(get_db),
):
    mission = Mission(
        id=str(uuid.uuid4()),
        query=query,
        country=country,
        status="queued",
        priority=priority or DEFAULT_COLLECTION_PRIORITY,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)

    # 把采集任务放入队列
    enqueue_collection_mission(mission.id, mission.priority)

    return {"mission_id": mission.id, "status": "queued", "priority": mission.priority}


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
