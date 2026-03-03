from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import (
    BuiltinToolCallPart,
    ModelMessage,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_worker_db_runtime: DatabaseRuntime | None = None


def _get_worker_db_runtime() -> DatabaseRuntime:
    global _worker_db_runtime
    if _worker_db_runtime is None:
        _worker_db_runtime = DatabaseRuntime(get_settings().resolved_database_url)
        _worker_db_runtime.startup()
    return _worker_db_runtime


def _filter_deferred_tool_results(
    messages: list[ModelMessage],
    deferred_tool_results: DeferredToolResults | None,
) -> DeferredToolResults | None:
    """Keep deferred tool results only for dangling tool"""
    if deferred_tool_results is None or not messages:
        return None

    # find any tool calls without corresponding tool message
    tool_call_ids: set[str] = {
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart | BuiltinToolCallPart)
    }
    tool_message_ids: set[str] = {
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart | RetryPromptPart | BuiltinToolCallPart)
    }
    dangling_tool_call_ids: set[str] = tool_call_ids - tool_message_ids

    if not dangling_tool_call_ids:
        return None

    filtered = DeferredToolResults(
        approvals={
            tool_call_id: value
            for tool_call_id, value in deferred_tool_results.approvals.items()
            if tool_call_id in dangling_tool_call_ids
        },
        calls={
            tool_call_id: value
            for tool_call_id, value in deferred_tool_results.calls.items()
            if tool_call_id in dangling_tool_call_ids
        },
        metadata={
            tool_call_id: value
            for tool_call_id, value in deferred_tool_results.metadata.items()
            if tool_call_id in dangling_tool_call_ids
        },
    )

    if not filtered.approvals and not filtered.calls:
        return None

    return filtered


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
            sdk_version=6,
        )
        deferred_tool_results = _filter_deferred_tool_results(
            adapter.messages,
            adapter.deferred_tool_results,
        )
        # `UIAdapter.run_stream_native` falls back to `self.deferred_tool_results`
        # whenever the explicit argument is `None`. Override the cached property
        # value so stale approvals from the request payload are not reintroduced.
        adapter.__dict__['deferred_tool_results'] = deferred_tool_results
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
            output_type=[str, DeferredToolRequests],
            deferred_tool_results=deferred_tool_results,
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
