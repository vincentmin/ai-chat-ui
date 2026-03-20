from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import (
    BuiltinToolCallPart,
    ModelMessage,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage
from pydantic_ai.ui.vercel_ai.response_types import DoneChunk, ErrorChunk
from redis import asyncio as redis

from ..agent_deps import AgentDeps
from ..db import ChatRunStatus, to_json_value
from ..db.message_codec import messages_from_json
from ..db.runtime import DatabaseRuntime
from ..db.service import (
    create_chat_run,
    get_active_run,
    get_latest_snapshot,
    save_run_snapshot,
    update_run_status,
)
from ..history_processor import (
    create_mailbox_history_processor,
    mailbox_messages_to_model_requests,
)
from ..mailbox import drain_mailbox, mailbox_is_empty
from ..settings import get_settings
from ..streaming.redis_stream import (
    chat_run_stream_key,
    publish_chunk,
    publish_terminal,
)
from ..team_tools import tell
from .agent_registry import (
    get_agent,
    get_team_agents,
    get_team_instructions,
    resolve_model_ref,
)
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
    request_body: str | None,
    selected_model: str | None,
    system_prompt: str | None,
) -> None:
    db_runtime = _get_worker_db_runtime()
    settings = get_settings()
    redis_url = settings.redis_url
    stream_key = chat_run_stream_key(
        agent_key=agent_key,
        conversation_id=conversation_id,
        run_id=run_id,
    )

    redis_client = redis.from_url(redis_url, decode_responses=True)
    try:
        await _update_run_status(run_id, ChatRunStatus.RUNNING)

        # Build per-run history processor and create a fresh agent with it baked in.
        history_processor = create_mailbox_history_processor(
            redis_client,
            agent_key,
            conversation_id,
        )
        agent = get_agent(agent_key, history_processors=[history_processor])
        team_agents = get_team_agents()

        deps = AgentDeps(
            conversation_id=conversation_id,
            agent_key=agent_key,
            team_agents=team_agents,
            redis_client=redis_client,
        )

        if request_body is not None:
            # User-initiated run — parse Vercel AI SDK request body.
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
            adapter.__dict__['deferred_tool_results'] = deferred_tool_results
            message_history: list[ModelMessage] | None = None

            # For team agents, the frontend may be stale (missing messages
            # from wake-up runs the user hasn't polled yet).  Use the backend
            # snapshot as canonical history so the agent sees all prior turns.
            if team_agents and deferred_tool_results is None:
                with db_runtime.session() as session:
                    snapshot = get_latest_snapshot(session, conversation_id, agent_key)
                if snapshot:
                    persisted = messages_from_json(snapshot.model_messages_json)
                    adapter_msgs = adapter.messages
                    if len(persisted) > len(adapter_msgs):
                        # Snapshot has more messages than the adapter
                        # (wake-up runs). Use the snapshot as base and keep
                        # only the final user turn from the adapter.
                        adapter.__dict__['messages'] = adapter_msgs[-1:]
                        message_history = persisted
        else:
            # Mailbox-initiated (wake-up) run — load persisted history
            # and drain the mailbox to seed the conversation.
            adapter = VercelAIAdapter[Any, Any](
                agent=agent,
                run_input=SubmitMessage(id=conversation_id, messages=[]),
                accept='text/event-stream',
                sdk_version=6,
            )
            deferred_tool_results = None

            with db_runtime.session() as session:
                snapshot = get_latest_snapshot(session, conversation_id, agent_key)

            persisted_history = (
                messages_from_json(snapshot.model_messages_json) if snapshot else []
            )
            mailbox_msgs = await drain_mailbox(redis_client, agent_key, conversation_id)
            injected = mailbox_messages_to_model_requests(mailbox_msgs)
            message_history = [*persisted_history, *injected]

        model_ref = resolve_model_ref(agent_key, selected_model)
        tell_toolset = FunctionToolset([tell])
        team_instructions = get_team_instructions(agent_key)
        run_instructions: list[str] = [team_instructions]
        if system_prompt:
            run_instructions.append(system_prompt)

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
            instructions=run_instructions,
            toolsets=[tell_toolset],
            on_complete=on_complete,
            deps=deps,
            message_history=message_history,
        ):
            await publish_chunk(
                redis_client, stream_key, event_stream.encode_event(chunk)
            )

        await _update_run_status(run_id, ChatRunStatus.COMPLETED)

        # Post-run mailbox check: if new messages arrived during the final
        # model invocation, kick off a follow-up run for ourselves.
        # Use non-destructive peek so that the wake-up run can drain them.
        if not await mailbox_is_empty(redis_client, agent_key, conversation_id):
            await _enqueue_self_wakeup(agent_key, conversation_id)
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


async def _enqueue_self_wakeup(agent_key: str, conversation_id: str) -> None:
    """Enqueue a mailbox-initiated run for the given agent."""
    db_runtime = _get_worker_db_runtime()
    run_id = str(uuid4())
    with db_runtime.session() as session:
        create_chat_run(session, run_id, conversation_id, agent_key)

    await run_agent_task.kiq(
        run_id=run_id,
        conversation_id=conversation_id,
        agent_key=agent_key,
        request_body=None,
        selected_model=None,
        system_prompt=None,
    )


async def enqueue_wakeup_run(agent_key: str, conversation_id: str) -> None:
    """Wake up an idle agent if it has no active run.

    Called from the ``tell`` tool. If the agent already has an active run
    the mailbox will be drained by its history_processor; no wake-up needed.
    """
    db_runtime = _get_worker_db_runtime()
    with db_runtime.session() as session:
        active = get_active_run(session, conversation_id, agent_key)
    if active is not None:
        return
    await _enqueue_self_wakeup(agent_key, conversation_id)
