from __future__ import annotations

from taskiq_redis import ListQueueBroker

from ..settings import get_settings

settings = get_settings()

broker = ListQueueBroker(
    url=settings.redis_url,
    queue_name=settings.taskiq_queue_name,
)


def get_taskiq_redis_url() -> str:
    return settings.redis_url
