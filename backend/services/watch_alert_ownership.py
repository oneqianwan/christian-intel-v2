from __future__ import annotations

from config import settings


def ownership_enabled() -> bool:
    return bool(settings.feature_flag("WATCH_ALERT_USER_OWNERSHIP_ENABLED"))
