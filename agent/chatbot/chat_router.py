from __future__ import annotations as _annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import UIMessage
from redis import asyncio as redis

from .active_run import get_active_run_lease
from .chat_schemas import (
    ChatMessagesResponse,
    ChatRequestExtra,
    ConfigureFrontend,
    ConversationsResponse,
    ConversationSummary,
    DeleteChatResponse,
    HealthResponse,
    ModelInfo,
    RunStatusResponse,
)
from .db.message_codec import messages_from_json
from .db.runtime import DatabaseRuntime
from .db.service import (
    delete_chat_records,
    get_latest_snapshot,
    get_latest_snapshot_per_conversation,
)
from .lifespan import get_db_runtime
from .mailbox import push_to_mailbox
from .settings import AppSettings, get_settings
from .streaming.redis_stream import chat_run_stream_key, iter_stream_events
from .tasks.run_agent_task import ensure_agent_mailbox_run, ensure_agent_request_run

logger = logging.getLogger(__name__)

ModelsParam = Mapping[str, Model | KnownModelName | str]
_CHAT_STREAM_HEADERS = {'x-vercel-ai-ui-message-stream': 'v1'}


def _require_redis_url(settings: AppSettings) -> str:
    redis_url = settings.redis_url
    if not isinstance(redis_url, str) or not redis_url:
        raise HTTPException(status_code=503, detail='Redis runtime unavailable')
    return redis_url


def _extract_last_user_text(messages: Sequence[UIMessage]) -> str | None:
    """Extract the text content of the last user message, if any."""
    for msg in reversed(messages):
        if msg.role != 'user':
            continue
        texts: list[str] = []
        for part in msg.parts:
            text = getattr(part, 'text', None)
            if isinstance(text, str):
                texts.append(text)
        if texts:
            return '\n'.join(texts)
    return None


def _validate_chat_request(
    *,
    raw_body: bytes,
    model_ids: set[str],
    can_override_system_prompt: bool,
) -> ChatRequestExtra:
    run_input = VercelAIAdapter[Any, Any].build_run_input(raw_body)
    extra_data = ChatRequestExtra.model_validate(run_input.__pydantic_extra__)

    if extra_data.model and extra_data.model not in model_ids:
        raise HTTPException(
            status_code=400,
            detail=f'Model "{extra_data.model}" is not in the allowed models list',
        )

    if extra_data.system_prompt and not can_override_system_prompt:
        raise HTTPException(
            status_code=400,
            detail='System prompt override is not available for this agent',
        )

    return extra_data


def _streaming_response(
    redis_url: str,
    stream_key: str,
    *,
    start_id: str = '0-0',
) -> StreamingResponse:
    return StreamingResponse(
        _relay_stream(redis_url, stream_key, start_id=start_id),
        media_type='text/event-stream',
        headers=_CHAT_STREAM_HEADERS,
    )


def _build_conversation_summaries(
    latest_by_conversation: Mapping[str, Any],
) -> list[ConversationSummary]:
    summaries: list[ConversationSummary] = []
    for conversation_id, snapshot in latest_by_conversation.items():
        messages = messages_from_json(snapshot.model_messages_json)
        first_message = _first_user_message_text(messages)
        summaries.append(
            ConversationSummary(
                id=conversation_id,
                first_message=first_message,
                timestamp=int(snapshot.created_at.timestamp() * 1000),
            )
        )

    return sorted(
        summaries,
        key=lambda summary: summary.timestamp,
        reverse=True,
    )


def _first_user_message_text(model_messages: list[ModelMessage]) -> str | None:
    for message in model_messages:
        if not isinstance(message, ModelRequest):
            continue

        for part in message.parts:
            if not isinstance(part, UserPromptPart):
                continue

            if isinstance(part.content, str) and part.content.strip():
                return part.content

            if isinstance(part.content, list):
                text_parts = [item for item in part.content if isinstance(item, str)]
                joined = '\n'.join(text_parts).strip()
                if joined:
                    return joined

    return None


def _string_instructions_or_none(agent: Agent[Any, Any]) -> list[str] | None:
    instructions = getattr(agent, '_instructions', None)
    if not isinstance(instructions, list):
        return None
    if any(not isinstance(value, str) for value in instructions):
        return None
    return instructions


def _build_model_options(
    agent: Agent[Any, Any],
    models: ModelsParam,
) -> tuple[dict[str, Model | str], list[ModelInfo]]:
    model_id_to_ref: dict[str, Model | str] = {}
    model_infos: list[ModelInfo] = []

    seen_model_keys: set[tuple[str, str]] = set()

    def add_model(label: str | None, model_ref: Model | str | KnownModelName) -> None:
        model = infer_model(model_ref)
        model_key = (model.system, model.model_name)
        model_id = f'{model.system}:{model.model_name}'

        if model_key in seen_model_keys:
            return
        seen_model_keys.add(model_key)

        model_id_to_ref[model_id] = model_ref
        model_infos.append(ModelInfo(id=model_id, name=label or model.label))

    if agent.model is not None:
        add_model(None, agent.model)

    for label, model_ref in models.items():
        add_model(label, model_ref)

    return model_id_to_ref, model_infos


_TOOL_STATE_NORMALIZATION = {
    'approval-requested': 'input-available',
    'approval-responded': 'input-available',
    'output-denied': 'input-available',
}


async def _relay_stream(
    redis_url: str,
    stream_key: str,
    *,
    start_id: str = '0-0',
) -> AsyncIterator[str]:
    async for kind, payload in iter_stream_events(
        redis_url, stream_key, start_id=start_id
    ):
        if kind == 'chunk' and payload:
            yield payload
        if kind == 'terminal':
            break


def create_chat_router(
    *,
    agent: Agent[Any, Any],
    models: ModelsParam,
    agent_key: str,
) -> APIRouter:
    model_id_to_ref, model_infos = _build_model_options(agent, models)
    model_ids = set(model_id_to_ref.keys())

    string_instructions = _string_instructions_or_none(agent)
    can_override_system_prompt = string_instructions is not None
    default_system_prompt = (
        '\n\n'.join(string_instructions) if string_instructions else None
    )

    router = APIRouter()

    @router.options('/chat/{conversation_id}')
    async def options_chat_with_id() -> Response:
        return Response()

    @router.get('/configure')
    async def configure_frontend() -> ConfigureFrontend:
        config = ConfigureFrontend(
            models=model_infos,
            can_override_system_prompt=can_override_system_prompt,
            default_system_prompt=default_system_prompt,
        )
        return config

    @router.get('/health')
    async def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @router.post('/chat/{conversation_id}')
    async def post_chat(
        request: Request,
        conversation_id: str,
        settings: AppSettings = Depends(get_settings),
    ) -> Response:
        raw_body = await request.body()
        extra_data = _validate_chat_request(
            raw_body=raw_body,
            model_ids=model_ids,
            can_override_system_prompt=can_override_system_prompt,
        )
        redis_url = _require_redis_url(settings)

        run_input = VercelAIAdapter[Any, Any].build_run_input(raw_body)
        request_adapter = VercelAIAdapter[Any, Any](
            agent=agent,
            run_input=run_input,
            accept='text/event-stream',
            sdk_version=6,
        )
        user_text = _extract_last_user_text(run_input.messages)

        if request_adapter.deferred_tool_results is not None:
            run_id = await ensure_agent_request_run(
                agent_key,
                conversation_id,
                request_body=raw_body.decode('utf-8'),
                selected_model=extra_data.model,
                system_prompt=(
                    extra_data.system_prompt if can_override_system_prompt else None
                ),
            )
            if run_id is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        'Cannot resume deferred tool request while an '
                        'agent run is already active'
                    ),
                )

            stream_key = chat_run_stream_key(
                agent_key=agent_key,
                conversation_id=conversation_id,
                run_id=run_id,
            )
            return _streaming_response(redis_url, stream_key)

        if not user_text:
            raise HTTPException(status_code=400, detail='No user message content found')

        redis_client = redis.from_url(redis_url, decode_responses=True)
        try:
            await push_to_mailbox(
                redis_client,
                agent_key=agent_key,
                conversation_id=conversation_id,
                sender='user',
                content=user_text,
            )
            run_id = await ensure_agent_mailbox_run(
                agent_key,
                conversation_id,
                selected_model=extra_data.model,
                system_prompt=(
                    extra_data.system_prompt if can_override_system_prompt else None
                ),
            )
        finally:
            await redis_client.aclose()

        if run_id is None:
            return Response(status_code=202)

        stream_key = chat_run_stream_key(
            agent_key=agent_key,
            conversation_id=conversation_id,
            run_id=run_id,
        )

        return _streaming_response(redis_url, stream_key)

    @router.get('/chat/{conversation_id}/stream')
    async def stream_chat(
        conversation_id: str,
        settings: AppSettings = Depends(get_settings),
    ) -> Response:
        redis_url = _require_redis_url(settings)

        redis_client = redis.from_url(redis_url, decode_responses=True)
        try:
            active_lease = await get_active_run_lease(
                redis_client,
                agent_key,
                conversation_id,
            )
        finally:
            await redis_client.aclose()

        if active_lease is None:
            return Response(status_code=204)

        stream_key = chat_run_stream_key(
            agent_key=agent_key,
            conversation_id=conversation_id,
            run_id=active_lease.run_id,
        )
        return _streaming_response(redis_url, stream_key, start_id='0-0')

    @router.get('/chat/{conversation_id}/run')
    async def get_run_status(
        conversation_id: str,
        settings: AppSettings = Depends(get_settings),
    ) -> RunStatusResponse:
        redis_url = _require_redis_url(settings)
        redis_client = redis.from_url(redis_url, decode_responses=True)
        try:
            active_lease = await get_active_run_lease(
                redis_client,
                agent_key,
                conversation_id,
            )
        finally:
            await redis_client.aclose()

        if active_lease is None:
            return RunStatusResponse(active=False)

        return RunStatusResponse(
            active=True,
            run_id=active_lease.run_id,
            status=active_lease.status,
        )

    @router.get('/chat/{conversation_id}')
    async def get_chat(
        conversation_id: str,
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> ChatMessagesResponse:
        with db_runtime.session() as session:
            latest_snapshot = get_latest_snapshot(session, conversation_id, agent_key)
        if latest_snapshot is None:
            return ChatMessagesResponse(messages=[])

        model_messages = messages_from_json(latest_snapshot.model_messages_json)
        ui_messages = VercelAIAdapter[Any, Any].dump_messages(model_messages)
        return ChatMessagesResponse.model_validate(
            {'messages': jsonable_encoder(ui_messages)}
        )

    @router.get('/chats')
    async def list_chats(
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> ConversationsResponse:
        with db_runtime.session() as session:
            latest_by_conversation = get_latest_snapshot_per_conversation(
                session, agent_key
            )

        return ConversationsResponse(
            conversations=_build_conversation_summaries(latest_by_conversation)
        )

    @router.delete('/chat/{conversation_id}')
    async def delete_chat(
        conversation_id: str,
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> DeleteChatResponse:
        with db_runtime.session() as session:
            delete_chat_records(session, conversation_id, agent_key)

        return DeleteChatResponse(ok=True)

    return router
