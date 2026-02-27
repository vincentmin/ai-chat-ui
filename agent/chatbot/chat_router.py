from __future__ import annotations as _annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic.alias_generators import to_camel
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import UIMessage

from .db.message_codec import messages_from_json
from .db.runtime import DatabaseRuntime
from .db.service import (
    create_chat_run,
    delete_chat_records,
    get_latest_snapshot,
    get_latest_snapshot_per_conversation,
    supersede_stale_runs,
    update_run_task_id,
)
from .lifespan import get_db_runtime
from .settings import AppSettings, get_settings
from .streaming.redis_stream import chat_run_stream_key, iter_stream_events
from .tasks.run_agent_task import run_agent_task

logger = logging.getLogger(__name__)

ModelsParam = Mapping[str, Model | KnownModelName | str]


class ModelInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str


class ConfigureFrontend(BaseModel, alias_generator=to_camel, populate_by_name=True):
    models: list[ModelInfo]
    can_override_system_prompt: bool
    default_system_prompt: str | None


class HealthResponse(BaseModel, alias_generator=to_camel, populate_by_name=True):
    ok: bool


class ChatRequestExtra(
    BaseModel,
    extra='ignore',
    alias_generator=to_camel,
    populate_by_name=True,
):
    model: str | None = None
    system_prompt: str | None = None
    agent_key: str | None = None


class CreateConversationResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    id: str


class ConversationSummary(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    id: str
    first_message: str | None = None
    timestamp: int


class ConversationsResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    conversations: list[ConversationSummary]


class DeleteChatResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    ok: bool


class ChatMessagesResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    messages: list[UIMessage]


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


async def _relay_stream(redis_url: str, stream_key: str) -> AsyncIterator[str]:
    async for kind, payload in iter_stream_events(
        redis_url, stream_key, start_id='0-0'
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

    @router.options('/chat')
    async def options_chat() -> Response:
        return Response()

    @router.options('/chat/{conversation_id}')
    async def options_chat_with_id() -> Response:
        return Response()

    @router.post('/chat')
    async def create_conversation() -> CreateConversationResponse:
        payload = CreateConversationResponse(id=str(uuid4()))
        return payload

    @router.get('/configure')
    async def configure_frontend() -> ConfigureFrontend:
        config = ConfigureFrontend(
            models=model_infos,
            can_override_system_prompt=can_override_system_prompt,
            default_system_prompt=default_system_prompt,
        )
        return config

    @router.get('/health')
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(ok=True)

    @router.post('/chat/{conversation_id}')
    async def post_chat(
        request: Request,
        conversation_id: str,
        settings: AppSettings = Depends(get_settings),
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> StreamingResponse:
        raw_body = await request.body()
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

        redis_url = settings.redis_url
        if not isinstance(redis_url, str) or not redis_url:
            raise HTTPException(status_code=503, detail='Redis runtime unavailable')

        # POST always means a new user message — supersede any stale active runs
        # so they don't block the new enqueue.
        with db_runtime.session() as session:
            supersede_stale_runs(session, conversation_id, agent_key)

        run_id = str(uuid4())
        with db_runtime.session() as session:
            create_chat_run(session, run_id, conversation_id, agent_key)

        task = await run_agent_task.kiq(
            run_id=run_id,
            conversation_id=conversation_id,
            agent_key=agent_key,
            request_body=raw_body.decode('utf-8'),
            selected_model=extra_data.model,
            system_prompt=(
                extra_data.system_prompt if can_override_system_prompt else None
            ),
        )

        with db_runtime.session() as session:
            update_run_task_id(session, run_id, task.task_id)

        stream_key = chat_run_stream_key(
            agent_key=agent_key,
            conversation_id=conversation_id,
            run_id=run_id,
        )

        return StreamingResponse(
            _relay_stream(redis_url, stream_key),
            media_type='text/event-stream',
            headers={'x-vercel-ai-ui-message-stream': 'v1'},
        )

    @router.get('/chat/{conversation_id}')
    async def get_chat(
        conversation_id: str,
        request: Request,
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
        request: Request,
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> ConversationsResponse:
        with db_runtime.session() as session:
            latest_by_conversation = get_latest_snapshot_per_conversation(
                session, agent_key
            )

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

        sorted_summaries = sorted(
            summaries,
            key=lambda summary: summary.timestamp,
            reverse=True,
        )
        return ConversationsResponse(conversations=sorted_summaries)

    @router.delete('/chat/{conversation_id}')
    async def delete_chat(
        conversation_id: str,
        request: Request,
        db_runtime: DatabaseRuntime = Depends(get_db_runtime),
    ) -> DeleteChatResponse:
        with db_runtime.session() as session:
            delete_chat_records(session, conversation_id, agent_key)

        return DeleteChatResponse(ok=True)

    return router
