import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from dependencies.auth import require_authenticated_user
from models.database import get_db, RequestTrace, Message, Mission, JobRun

router = APIRouter(dependencies=[Depends(require_authenticated_user)])


@router.get("/diagnostics/request/{request_id}")
def get_request_diagnostics(request_id: str, db: Session = Depends(get_db)):
    traces = db.query(RequestTrace).filter(RequestTrace.request_id == request_id).order_by(RequestTrace.created_at).all()

    if not traces:
        return {"request_id": request_id, "found": False, "message": "未找到该请求的追踪记录"}

    # 查找关联的消息
    messages = db.query(Message).filter(Message.content.contains(request_id[:8])).all()

    return {
        "request_id": request_id,
        "found": True,
        "trace_count": len(traces),
        "total_duration_ms": _calc_duration(traces),
        "events": [
            {
                "seq": i + 1,
                "time": t.created_at.isoformat(),
                "type": t.event_type,
                "data": t.event_data
            }
            for i, t in enumerate(traces)
        ],
        "summary": {
            "route": next((t.event_data for t in traces if t.event_type == "route_decided"), None),
            "knowledge_hits": next((t.event_data.get("results_count", 0) for t in traces if t.event_type == "knowledge_queried"), 0),
            "delivery_status": next((t.event_data.get("status") for t in traces if t.event_type == "delivery_emitted"), None),
        }
    }


def _calc_duration(traces):
    if len(traces) < 2:
        return 0
    first = traces[0].created_at
    last = traces[-1].created_at
    return int((last - first).total_seconds() * 1000)
