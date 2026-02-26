from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.agent import AgentRunResult
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, ErrorChunk
from sqlmodel import select

from ..db import AgentRunSnapshot, ChatRun, ChatRunStatus, to_json_value
from ..db.runtime import DatabaseRuntime
from ..settings import get_settings
from ..streaming.redis_stream import (
    chat_run_stream_key,
    publish_chunk,
    publish_terminal,
)
from .agent_registry import get_agent, resolve_model_ref
from .broker import broker, get_taskiq_redis_url

logger = logging.getLogger(__name__)


_db_runtime: DatabaseRuntime | None = None


def get_db_runtime() -> DatabaseRuntime:
    global _db_runtime
    if _db_runtime is None:
        _db_runtime = DatabaseRuntime(get_settings().resolved_database_url)
        _db_runtime.startup()
    return _db_runtime


async def _set_run_status(
    run_id: str,
    status: ChatRunStatus,
    error: str | None = None,
) -> None:
    db_runtime = get_db_runtime()
    with db_runtime.session() as session:
        run = session.exec(
            select(ChatRun).where(ChatRun.run_id == run_id)
        ).one_or_none()
        if run is None:
            return
        run.status = status.value
        run.error = error
        run.updated_at = datetime.now(UTC)
        session.add(run)
        session.commit()


@broker.task(task_name='chatbot.tasks.run_agent')
async def run_agent_task(
    run_id: str,
    conversation_id: str,
    agent_key: str,
    request_body: str,
    selected_model: str | None,
    system_prompt: str | None,
) -> None:
    db_runtime = get_db_runtime()
    redis_url = get_taskiq_redis_url()
    stream_key = chat_run_stream_key(
        agent_key=agent_key,
        conversation_id=conversation_id,
        run_id=run_id,
    )

    await _set_run_status(run_id, ChatRunStatus.RUNNING)

    try:
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
                session.add(
                    AgentRunSnapshot(
                        conversation_id=conversation_id,
                        run_id=result.run_id,
                        agent_key=agent_key,
                        model_messages_json=to_json_value(result.all_messages()),
                    )
                )
                session.commit()

        event_stream = adapter.build_event_stream()
        async for chunk in adapter.run_stream(
            model=model_ref,
            instructions=system_prompt,
            on_complete=on_complete,
        ):
            await publish_chunk(redis_url, stream_key, event_stream.encode_event(chunk))

        await _set_run_status(run_id, ChatRunStatus.COMPLETED)
    except Exception as exc:
        logger.exception('Taskiq worker failed to execute run %s', run_id)
        await _set_run_status(run_id, ChatRunStatus.FAILED, str(exc))
        await publish_chunk(
            redis_url,
            stream_key,
            f'data: {ErrorChunk(error_text=str(exc)).encode(5)}\\n\\n',
        )
        await publish_chunk(
            redis_url,
            stream_key,
            f'data: {DoneChunk().encode(5)}\\n\\n',
        )
    finally:
        await publish_terminal(redis_url, stream_key)
