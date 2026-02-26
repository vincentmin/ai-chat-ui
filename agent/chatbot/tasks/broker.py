from __future__ import annotations

from taskiq import TaskiqEvents
from taskiq_redis import ListQueueBroker

from ..settings import RedisRuntime, get_settings

settings = get_settings()
_redis_runtime: RedisRuntime | None = None


def get_redis_runtime() -> RedisRuntime:
    global _redis_runtime
    if _redis_runtime is None:
        _redis_runtime = RedisRuntime(settings)
        _redis_runtime.startup()
    return _redis_runtime


redis_runtime = get_redis_runtime()

if not redis_runtime.redis_url:
    raise RuntimeError('Redis URL is not available for Taskiq broker')

broker = ListQueueBroker(
    url=redis_runtime.redis_url,
    queue_name=settings.taskiq_queue_name,
)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _shutdown_redislite(_: object) -> None:
    # In development, workers may own the local redislite process.
    redis_runtime.shutdown()


def get_taskiq_redis_url() -> str:
    if not redis_runtime.redis_url:
        raise RuntimeError('Redis URL is not available for Taskiq runtime')
    return redis_runtime.redis_url
