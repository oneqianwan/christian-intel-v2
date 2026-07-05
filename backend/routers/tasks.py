from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import Mission, Task, get_db

router = APIRouter()


def _serialize_task_view(task: Task, mission: Optional[Mission]) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "mission_id": task.mission_id,
        "mission": (
            {
                "id": mission.id,
                "query": mission.query,
                "country": mission.country,
                "status": mission.status,
                "priority": mission.priority,
                "target_entity": mission.target_entity,
                "created_at": mission.created_at.isoformat() if mission.created_at else None,
                "updated_at": mission.updated_at.isoformat() if mission.updated_at else None,
            }
            if task.mission_id and mission
            else None
        ),
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


@router.get("/tasks")
def list_tasks(
    limit: int = 20,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取任务列表"""
    rows = (
        db.query(Task, Mission)
        .outerjoin(Mission, Task.mission_id == Mission.id)
        .order_by(Task.created_at.desc())
        .limit(max(limit * 3, limit))
        .all()
    )
    items = [_serialize_task_view(task, mission) for task, mission in rows]
    if status:
        items = [
            item
            for item, (task, mission) in zip(items, rows)
            if ((mission.status if task.mission_id and mission else task.status) == status)
        ]
    items = items[:limit]
    return {
        "tasks": items,
        "total": len(items),
    }


@router.post("/tasks")
def create_task(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """创建任务"""
    title = (payload.get("title") or "").strip()
    description = payload.get("description") or ""
    priority = payload.get("priority") or "medium"
    entity_id = payload.get("entity_id")
    mission_id = payload.get("mission_id")

    if mission_id:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            raise HTTPException(status_code=404, detail="Mission not found")

    task = Task(
        title=title,
        description=description,
        priority=None if mission_id else priority,
        status=None if mission_id else "pending",
        entity_id=entity_id,
        mission_id=mission_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    return {
        "status": "created",
        "task_id": task.id,
        "title": task.title,
    }


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    """更新任务状态或优先级"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    status = payload.get("status")
    priority = payload.get("priority")

    if status and not task.mission_id:
        task.status = status
    if priority and not task.mission_id:
        task.priority = priority
    task.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(task)
    return {"status": "updated", "task_id": task_id}


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
):
    """删除任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()
    return {"status": "deleted", "task_id": task_id}
