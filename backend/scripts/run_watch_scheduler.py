from __future__ import annotations

import os
import sys

from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models.database import SessionLocal  # noqa: E402
from services.watch_scheduler import run_watch_scheduler_once  # noqa: E402


def main() -> int:
    limit = int(os.getenv("WATCH_ALERT_SCHEDULER_SCAN_LIMIT", "100") or "100")
    db = SessionLocal()
    try:
        run_watch_scheduler_once(db, limit=limit)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
