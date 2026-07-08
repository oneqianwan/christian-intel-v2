from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

import config
from dependencies.auth import resolve_user_for_request
from models.auth import User
from models.database import get_db


def get_chat_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    if not bool(config.settings.CHAT_USER_OWNERSHIP_ENABLED):
        return None
    return resolve_user_for_request(request=request, db=db, touch_last_seen=True)
