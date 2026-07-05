import redis
from rq import Queue
import os
from services.mission_runner import run_mission

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
conn = redis.from_url(REDIS_URL)
collection_queue = Queue("collection", connection=conn)

DEFAULT_COLLECTION_PRIORITY = 5
HIGH_COLLECTION_PRIORITY = 8


def get_redis_connection():
    return conn


def get_collection_queue():
    return collection_queue


def enqueue_collection_mission(mission_id: str, priority: int = DEFAULT_COLLECTION_PRIORITY):
    return collection_queue.enqueue(
        run_mission,
        mission_id,
        job_timeout=300,
        result_ttl=3600,
        at_front=priority >= HIGH_COLLECTION_PRIORITY,
        meta={"priority": priority},
    )
