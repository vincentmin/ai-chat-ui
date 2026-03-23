from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import (
    ModelMessage,
)
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, ErrorChunk
from redis import asyncio as redis

from ..active_run import (
    ACTIVE_RUN_HEARTBEAT_SECONDS,
    ActiveRunLease,
    get_active_run_lease,
    new_active_run_lease,
    refresh_active_run,
    release_active_run,
    try_acquire_active_run,
)
from ..agent_deps import AgentDeps
from ..db import ChatRunStatus, to_json_value
from ..db.message_codec import messages_from_json
from ..db.runtime import DatabaseRuntime
from ..db.service import (
    create_chat_run,
    get_latest_snapshot,
    save_run_snapshot,
    update_run_status,
    update_run_task_id,
)
from ..history_processor import mailbox_messages_to_model_requests
from ..mailbox import drain_mailbox, mailbox_is_empty
from ..settings import get_settings
from ..streaming.redis_stream import (
    chat_run_stream_key,
    publish_chunk,
    publish_terminal,
)
from ..team_tools import TEAM_TOOLSET, build_team_instructions
from .agent_registry import get_agent, get_team_agents, resolve_model_ref
from .broker import broker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_worker_db_runtime: DatabaseRuntime | None = None


def _build_run_instructions(
    agent_key: str,
    team_agents: list[str],
    system_prompt: str | None,
) -> str | tuple[str, ...] | None:
    instructions = [build_team_instructions(agent_key, team_agents), system_prompt]
    resolved = tuple(instruction for instruction in instructions if instruction)
    if not resolved:
        return None
    if len(resolved) == 1:
        return resolved[0]
    return resolved


def _load_snapshot_messages(
    db_runtime: DatabaseRuntime,
    conversation_id: str,
    agent_key: str,
) -> list[ModelMessage]:
    with db_runtime.session() as session:
        snapshot = get_latest_snapshot(session, conversation_id, agent_key)

    return messages_from_json(snapshot.model_messages_json) if snapshot else []


def _build_request_message_history(
    persisted_messages: list[ModelMessage],
    request_messages: list[ModelMessage],
    deferred_tool_results: DeferredToolResults | None,
) -> list[ModelMessage]:
    """Build canonical history for a direct approval-resume request."""
    if deferred_tool_results is not None:
        return list(persisted_messages)

    return [*persisted_messages, *request_messages[-1:]]


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


async def _save_snapshot(
    conversation_id: str,
    agent_key: str,
    result: AgentRunResult[Any],
) -> None:
    db_runtime = _get_worker_db_runtime()
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id=conversation_id,
            run_id=result.run_id,
            agent_key=agent_key,
            model_messages_json=to_json_value(result.all_messages()),
        )


async def _heartbeat_active_run(
    control_client: redis.Redis,
    lease: ActiveRunLease,
) -> None:
    current = lease
    while True:
        await asyncio.sleep(ACTIVE_RUN_HEARTBEAT_SECONDS)
        refreshed = await refresh_active_run(
            control_client,
            current,
            status='running',
        )
        if refreshed is None:
            logger.warning(
                'Lost active-run lease for %s/%s (%s)',
                current.agent_key,
                current.conversation_id,
                current.run_id,
            )
            return
        current = refreshed


async def _prepare_active_run(
    control_client: redis.Redis,
    run_id: str,
    conversation_id: str,
    agent_key: str,
) -> ActiveRunLease | None:
    lease = await get_active_run_lease(control_client, agent_key, conversation_id)
    if lease is None or lease.run_id != run_id:
        logger.info(
            'Skipping run %s for %s/%s because its lease is missing or owned elsewhere',
            run_id,
            agent_key,
            conversation_id,
        )
        return None

    refreshed = await refresh_active_run(control_client, lease, status='running')
    if refreshed is None:
        logger.info(
            'Skipping run %s for %s/%s because its lease could not be refreshed',
            run_id,
            agent_key,
            conversation_id,
        )
        return None
    return refreshed


async def _run_agent_cycle(
    *,
    run_id: str,
    conversation_id: str,
    agent_key: str,
    adapter: VercelAIAdapter[Any, Any],
    message_history: list[ModelMessage],
    selected_model: str | None,
    system_prompt: str | None,
    runtime_client: redis.Redis,
    stream_key: str,
) -> None:
    team_agents = get_team_agents()
    deps = AgentDeps(
        conversation_id=conversation_id,
        agent_key=agent_key,
        team_agents=team_agents,
        redis_client=runtime_client,
    )
    run_instructions = _build_run_instructions(
        agent_key,
        team_agents,
        system_prompt,
    )
    run_toolsets = [TEAM_TOOLSET] if len(team_agents) > 1 else None
    model_ref = resolve_model_ref(agent_key, selected_model)
    event_stream = adapter.build_event_stream()

    async def on_complete(result: AgentRunResult[Any]) -> None:
        await _save_snapshot(conversation_id, agent_key, result)

    async for chunk in adapter.run_stream(
        output_type=[str, DeferredToolRequests],
        deferred_tool_results=adapter.deferred_tool_results,
        model=model_ref,
        instructions=run_instructions,
        on_complete=on_complete,
        deps=deps,
        message_history=message_history,
        toolsets=run_toolsets,
    ):
        await publish_chunk(
            runtime_client,
            stream_key,
            event_stream.encode_event(chunk),
        )


async def _execute_with_lease(
    *,
    run_id: str,
    conversation_id: str,
    agent_key: str,
    execute: Callable[[redis.Redis, str], Awaitable[None]],
) -> None:
    settings = get_settings()
    redis_url = settings.redis_url
    stream_key = chat_run_stream_key(
        agent_key=agent_key,
        conversation_id=conversation_id,
        run_id=run_id,
    )

    control_client = redis.from_url(redis_url, decode_responses=True)
    runtime_client = redis.from_url(redis_url, decode_responses=True)
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        lease = await _prepare_active_run(
            control_client,
            run_id,
            conversation_id,
            agent_key,
        )
        if lease is None:
            await _update_run_status(
                run_id,
                ChatRunStatus.FAILED,
                'active run lease unavailable',
            )
            return

        heartbeat_task = asyncio.create_task(
            _heartbeat_active_run(control_client, lease)
        )
        await _update_run_status(run_id, ChatRunStatus.RUNNING)
        await execute(runtime_client, stream_key)
        await _update_run_status(run_id, ChatRunStatus.COMPLETED)
    except Exception as exc:
        logger.exception('Taskiq worker failed to execute run %s', run_id)
        await _update_run_status(run_id, ChatRunStatus.FAILED, str(exc))
        await publish_chunk(
            runtime_client,
            stream_key,
            f'data: {ErrorChunk(error_text=str(exc)).encode(5)}\\n\\n',
        )
        await publish_chunk(
            runtime_client,
            stream_key,
            f'data: {DoneChunk().encode(5)}\n\n',
        )
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        await release_active_run(control_client, agent_key, conversation_id, run_id)
        await publish_terminal(runtime_client, stream_key)
        await runtime_client.aclose()
        await control_client.aclose()


async def _enqueue_task_run(
    *,
    agent_key: str,
    conversation_id: str,
    task_enqueue: Callable[..., Awaitable[Any]],
    selected_model: str | None,
    system_prompt: str | None,
    request_body: str | None = None,
) -> str | None:
    settings = get_settings()
    control_client = redis.from_url(settings.redis_url, decode_responses=True)
    db_runtime = _get_worker_db_runtime()
    run_id = str(uuid4())
    lease = new_active_run_lease(run_id, agent_key, conversation_id)

    try:
        acquired = await try_acquire_active_run(control_client, lease)
        if not acquired:
            return None

        with db_runtime.session() as session:
            create_chat_run(session, run_id, conversation_id, agent_key)

        enqueue_kwargs: dict[str, Any] = {
            'run_id': run_id,
            'conversation_id': conversation_id,
            'agent_key': agent_key,
        }
        if request_body is not None:
            enqueue_kwargs['request_body'] = request_body
            enqueue_kwargs['selected_model'] = selected_model
            enqueue_kwargs['system_prompt'] = system_prompt
        else:
            enqueue_kwargs['selected_model'] = selected_model
            enqueue_kwargs['system_prompt'] = system_prompt

        task = await task_enqueue(**enqueue_kwargs)
        with db_runtime.session() as session:
            update_run_task_id(session, run_id, task.task_id)
        return run_id
    except Exception as exc:
        logger.exception(
            'Failed to enqueue run %s for %s/%s',
            run_id,
            agent_key,
            conversation_id,
        )
        await release_active_run(control_client, agent_key, conversation_id, run_id)
        await _update_run_status(run_id, ChatRunStatus.FAILED, str(exc))
        raise
    finally:
        await control_client.aclose()


async def ensure_agent_mailbox_run(
    agent_key: str,
    conversation_id: str,
    *,
    selected_model: str | None = None,
    system_prompt: str | None = None,
) -> str | None:
    return await _enqueue_task_run(
        agent_key=agent_key,
        conversation_id=conversation_id,
        task_enqueue=run_agent_mailbox_task.kiq,
        selected_model=selected_model,
        system_prompt=system_prompt,
    )


async def ensure_agent_request_run(
    agent_key: str,
    conversation_id: str,
    *,
    request_body: str,
    selected_model: str | None,
    system_prompt: str | None,
) -> str | None:
    return await _enqueue_task_run(
        agent_key=agent_key,
        conversation_id=conversation_id,
        task_enqueue=run_agent_request_task.kiq,
        selected_model=selected_model,
        system_prompt=system_prompt,
        request_body=request_body,
    )


@broker.task(task_name='chatbot.tasks.run_agent_request')
async def run_agent_request_task(
    run_id: str,
    conversation_id: str,
    agent_key: str,
    request_body: str,
    selected_model: str | None,
    system_prompt: str | None,
) -> None:
    async def execute(runtime_client: redis.Redis, stream_key: str) -> None:
        db_runtime = _get_worker_db_runtime()
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

        persisted_messages = _load_snapshot_messages(
            db_runtime,
            conversation_id,
            agent_key,
        )
        message_history = _build_request_message_history(
            persisted_messages,
            adapter.messages,
            adapter.deferred_tool_results,
        )
        adapter.__dict__['messages'] = []

        await _run_agent_cycle(
            run_id=run_id,
            conversation_id=conversation_id,
            agent_key=agent_key,
            adapter=adapter,
            message_history=message_history,
            selected_model=selected_model,
            system_prompt=system_prompt,
            runtime_client=runtime_client,
            stream_key=stream_key,
        )

    await _execute_with_lease(
        run_id=run_id,
        conversation_id=conversation_id,
        agent_key=agent_key,
        execute=execute,
    )


@broker.task(task_name='chatbot.tasks.run_agent_mailbox')
async def run_agent_mailbox_task(
    run_id: str,
    conversation_id: str,
    agent_key: str,
    selected_model: str | None,
    system_prompt: str | None,
) -> None:
    async def execute(runtime_client: redis.Redis, stream_key: str) -> None:
        db_runtime = _get_worker_db_runtime()
        agent = get_agent(agent_key)

        while True:
            persisted_history = _load_snapshot_messages(
                db_runtime,
                conversation_id,
                agent_key,
            )
            mailbox_msgs = await drain_mailbox(
                runtime_client,
                agent_key,
                conversation_id,
            )
            if not mailbox_msgs:
                return

            adapter = VercelAIAdapter[Any, Any](
                agent=agent,
                run_input=SubmitMessage(id=conversation_id, messages=[]),
                accept='text/event-stream',
                sdk_version=6,
            )
            adapter.__dict__['messages'] = []

            await _run_agent_cycle(
                run_id=run_id,
                conversation_id=conversation_id,
                agent_key=agent_key,
                adapter=adapter,
                message_history=[
                    *persisted_history,
                    *mailbox_messages_to_model_requests(mailbox_msgs),
                ],
                selected_model=selected_model,
                system_prompt=system_prompt,
                runtime_client=runtime_client,
                stream_key=stream_key,
            )

            if await mailbox_is_empty(runtime_client, agent_key, conversation_id):
                return

    await _execute_with_lease(
        run_id=run_id,
        conversation_id=conversation_id,
        agent_key=agent_key,
        execute=execute,
    )
