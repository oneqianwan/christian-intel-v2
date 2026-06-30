from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import Task, get_db

router = APIRouter()


@router.get("/tasks")
def list_tasks(
    limit: int = 20,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """获取任务列表"""
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)

    tasks = query.order_by(Task.created_at.desc()).limit(limit).all()
    return {
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "priority": task.priority,
                "status": task.status,
                "created_at": task.created_at.isoformat() if task.created_at else None,
            }
            for task in tasks
        ],
        "total": len(tasks),
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

    task = Task(
        title=title,
        description=description,
        priority=priority,
        status="pending",
        entity_id=entity_id,
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

    if status:
        task.status = status
        if status == "completed":
            task.completed_at = datetime.utcnow()
    if priority:
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
