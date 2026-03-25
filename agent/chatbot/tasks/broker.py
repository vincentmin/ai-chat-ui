from __future__ import annotations

import logfire
from taskiq_redis import ListQueueBroker

from ..settings import get_settings

# 'if-token-present' means nothing will be sent (and the example will work) if you don't
# have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()


def _make_broker() -> ListQueueBroker:
    settings = get_settings()
    return ListQueueBroker(
        url=settings.redis_url,
        queue_name=settings.taskiq_queue_name,
    )


broker = _make_broker()


def get_taskiq_redis_url() -> str:
    return get_settings().redis_url
