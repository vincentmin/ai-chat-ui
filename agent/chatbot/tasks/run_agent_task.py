from __future__ import annotations

import logging
from typing import Any

from pydantic_ai.agent import AgentRunResult
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, ErrorChunk
from redis import asyncio as redis

from ..db import ChatRunStatus, to_json_value
from ..db.runtime import DatabaseRuntime
from ..db.service import save_run_snapshot, update_run_status
from ..settings import get_settings
from ..streaming.redis_stream import (
    chat_run_stream_key,
    publish_chunk,
    publish_terminal,
)
from .agent_registry import get_agent, resolve_model_ref
from .broker import broker

logger = logging.getLogger(__name__)


_worker_db_runtime: DatabaseRuntime | None = None


def _get_worker_db_runtime() -> DatabaseRuntime:
    global _worker_db_runtime
    if _worker_db_runtime is None:
        _worker_db_runtime = DatabaseRuntime(get_settings().resolved_database_url)
        _worker_db_runtime.startup()
    return _worker_db_runtime


async def _update_run_status(
    run_id: str, status: ChatRunStatus, error: str | None = None
) -> None:
    db_runtime = _get_worker_db_runtime()
    with db_runtime.session() as session:
        update_run_status(session, run_id, status, error)


@broker.task(task_name='chatbot.tasks.run_agent')
async def run_agent_task(
    run_id: str,
    conversation_id: str,
    agent_key: str,
    request_body: str,
    selected_model: str | None,
    system_prompt: str | None,
) -> None:
    db_runtime = _get_worker_db_runtime()
    redis_url = get_settings().redis_url
    stream_key = chat_run_stream_key(
        agent_key=agent_key,
        conversation_id=conversation_id,
        run_id=run_id,
    )

    redis_client = redis.from_url(redis_url, decode_responses=True)
    try:
        await _update_run_status(run_id, ChatRunStatus.RUNNING)

        agent = get_agent(agent_key)
        run_input = VercelAIAdapter[Any, Any].build_run_input(
            request_body.encode('utf-8')
        )
        adapter = VercelAIAdapter[Any, Any](
            agent=agent,
            run_input=run_input,
            accept='text/event-stream',
        )

        model_ref = resolve_model_ref(agent_key, selected_model)

        async def on_complete(result: AgentRunResult[Any]) -> None:
            with db_runtime.session() as session:
                save_run_snapshot(
                    session,
                    conversation_id=conversation_id,
                    run_id=result.run_id,
                    agent_key=agent_key,
                    model_messages_json=to_json_value(result.all_messages()),
                )

        event_stream = adapter.build_event_stream()
        async for chunk in adapter.run_stream(
            model=model_ref,
            instructions=system_prompt,
            on_complete=on_complete,
        ):
            await publish_chunk(
                redis_client, stream_key, event_stream.encode_event(chunk)
            )

        await _update_run_status(run_id, ChatRunStatus.COMPLETED)
    except Exception as exc:
        logger.exception('Taskiq worker failed to execute run %s', run_id)
        await _update_run_status(run_id, ChatRunStatus.FAILED, str(exc))
        await publish_chunk(
            redis_client,
            stream_key,
            f'data: {ErrorChunk(error_text=str(exc)).encode(5)}\\n\\n',
        )
        await publish_chunk(
            redis_client,
            stream_key,
            f'data: {DoneChunk().encode(5)}\n\n',
        )
    finally:
        await publish_terminal(redis_client, stream_key)
        await redis_client.aclose()
