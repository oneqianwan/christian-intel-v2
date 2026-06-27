from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import ApiConfig, get_db


router = APIRouter()


@router.get("/configs/keys")
def list_api_keys(db: Session = Depends(get_db)):
    rows = db.query(ApiConfig).order_by(ApiConfig.api_name.asc()).all()
    return [
        {
            "api_name": row.api_name,
            "status": row.status or "unknown",
            "key_hint": row.key_hint or "",
            "usage_info": row.usage_info,
            "last_checked": row.last_checked.isoformat() if row.last_checked else None,
            "extra_config": row.extra_config or {},
        }
        for row in rows
    ]
