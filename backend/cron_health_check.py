#!/usr/bin/env python3
"""
定时健康巡检脚本
建议运行方式：Windows任务计划程序 或 RQ Scheduler
频率：每6小时
"""

import logging
import os
import sys
import uuid
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "health_check.log")

sys.path.insert(0, BASE_DIR)

from models.database import RequestTrace, get_db, init_db
from services.health_check import run_health_check


def _configure_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


logger = _configure_logging()


def main() -> None:
    logger.info("=" * 60)
    logger.info("开始定时健康巡检")
    logger.info("时间: %s", datetime.now().isoformat())

    db = None
    try:
        init_db()
        db = next(get_db())

        countries = ["菲律宾", "美国"]
        total_unhealthy = 0

        for country in countries:
            logger.info("")
            logger.info("--- 检查 %s ---", country)
            results = run_health_check(db, country=country)

            healthy = sum(1 for item in results if item["status"] == "healthy")
            unhealthy = sum(1 for item in results if item["status"] != "healthy")
            total_unhealthy += unhealthy

            logger.info("%s: %s健康 / %s不健康", country, healthy, unhealthy)

            for item in results:
                if item["status"] != "healthy":
                    logger.warning(
                        "不健康来源: %s | 状态: %s | 建议: %s",
                        item["name"],
                        item["status"],
                        item.get("recommendation", "无"),
                    )

        trace = RequestTrace(
            id=str(uuid.uuid4()),
            request_id=f"health_check_{datetime.now().strftime('%Y%m%d_%H%M')}",
            event_type="health_check_completed",
            event_data={
                "timestamp": datetime.now().isoformat(),
                "countries_checked": countries,
                "total_unhealthy": total_unhealthy,
            },
        )
        db.add(trace)
        db.commit()

        logger.info("")
        logger.info("巡检完成，共%s个不健康来源", total_unhealthy)
        if total_unhealthy > 0:
            logger.warning("存在不健康来源，需要人工介入")

    except Exception as exc:
        logger.error("巡检失败: %s", str(exc), exc_info=True)
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    main()
