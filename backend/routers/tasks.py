from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from dependencies.tenant_context import TenantRequestContext, require_tenant_member
from models.database import Mission, Task, get_db
from schemas.watch_alert import ApiErrorResponse
from services import tenant_scope

router = APIRouter()


def _raise_api_error(status_code: int, error_code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=ApiErrorResponse(error_code=error_code, message=message).model_dump(),
    )


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


def _task_query_for_tenant(db: Session, *, tenant_id: str):
    return tenant_scope.filter_by_tenant(db.query(Task), Task, tenant_id)


def _get_task_or_404(db: Session, *, task_id: int, tenant_id: str) -> Task:
    task = _task_query_for_tenant(db, tenant_id=tenant_id).filter(Task.id == task_id).first()
    if task is None:
        _raise_api_error(status.HTTP_404_NOT_FOUND, "TASK_NOT_FOUND", "Task not found")
    tenant_scope.require_record_tenant(task, tenant_id)
    return task


@router.get("/tasks")
def list_tasks(
    limit: int = 20,
    status: Optional[str] = None,
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    """获取任务列表"""
    current_tenant_id = str(context.tenant.id)
    rows = (
        _task_query_for_tenant(db, tenant_id=current_tenant_id)
        .with_entities(Task, Mission)
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
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    """创建任务"""
    title = (payload.get("title") or "").strip()
    description = payload.get("description") or ""
    priority = payload.get("priority") or "medium"
    entity_id = payload.get("entity_id")
    mission_id = payload.get("mission_id")
    tenant_payload = tenant_scope.ensure_tenant_id_for_create({}, str(context.tenant.id))

    if mission_id:
        mission = db.query(Mission).filter(Mission.id == mission_id).first()
        if not mission:
            _raise_api_error(status.HTTP_404_NOT_FOUND, "MISSION_NOT_FOUND", "Mission not found")

    task = Task(
        tenant_id=tenant_payload.get("tenant_id"),
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


@router.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    task = _get_task_or_404(db, task_id=task_id, tenant_id=str(context.tenant.id))
    mission = db.query(Mission).filter(Mission.id == task.mission_id).first() if task.mission_id else None
    return _serialize_task_view(task, mission)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    payload: dict = Body(...),
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    """更新任务状态或优先级"""
    task = _get_task_or_404(db, task_id=task_id, tenant_id=str(context.tenant.id))

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
    context: TenantRequestContext = Depends(require_tenant_member),
    db: Session = Depends(get_db),
):
    """删除任务"""
    task = _get_task_or_404(db, task_id=task_id, tenant_id=str(context.tenant.id))

    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
