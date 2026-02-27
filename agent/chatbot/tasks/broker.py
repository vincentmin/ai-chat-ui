from __future__ import annotations

from taskiq_redis import ListQueueBroker

from ..settings import get_settings


def _make_broker() -> ListQueueBroker:
    settings = get_settings()
    return ListQueueBroker(
        url=settings.redis_url,
        queue_name=settings.taskiq_queue_name,
    )


broker = _make_broker()


def get_taskiq_redis_url() -> str:
    return get_settings().redis_url
