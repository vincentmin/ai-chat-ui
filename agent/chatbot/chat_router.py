from __future__ import annotations as _annotations

import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.alias_generators import to_camel
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    UserPromptPart,
)
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from sqlmodel import select

from .db import AgentRunSnapshot, to_json_value
from .db.json_types import JsonValue
from .db.runtime import DatabaseRuntime

logger = logging.getLogger(__name__)

ModelsParam = Mapping[str, Model | KnownModelName | str]


class ModelInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str


class ConfigureFrontend(BaseModel, alias_generator=to_camel, populate_by_name=True):
    models: list[ModelInfo]
    can_override_system_prompt: bool
    default_system_prompt: str | None


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


def _messages_from_json(messages_json: JsonValue) -> list[ModelMessage]:
    if not isinstance(messages_json, list):
        return []

    try:
        return ModelMessagesTypeAdapter.validate_python(messages_json)
    except Exception:
        logger.exception('Failed to deserialize model messages')
        return []


def _latest_model_messages(
    db_runtime: DatabaseRuntime,
    conversation_id: str,
) -> list[ModelMessage]:
    latest_snapshot = _latest_snapshot(db_runtime, conversation_id)

    if latest_snapshot is None:
        return []

    return _messages_from_json(latest_snapshot.model_messages_json)


def _latest_snapshot(
    db_runtime: DatabaseRuntime,
    conversation_id: str,
) -> AgentRunSnapshot | None:
    with db_runtime.session() as session:
        statement = select(AgentRunSnapshot).where(
            AgentRunSnapshot.conversation_id == conversation_id
        )
        snapshots = session.exec(statement).all()

    return max(
        snapshots,
        key=lambda snapshot: snapshot.created_at,
        default=None,
    )


def _metadata_parts_by_tool_call_id(
    model_messages_json: JsonValue,
) -> dict[str, list[dict[str, JsonValue]]]:
    if not isinstance(model_messages_json, list):
        return {}

    metadata_parts_by_call_id: dict[str, list[dict[str, JsonValue]]] = {}

    for message in model_messages_json:
        if not isinstance(message, dict):
            continue

        parts = message.get('parts')
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue

            if part.get('part_kind') != 'tool-return':
                continue

            tool_call_id = part.get('tool_call_id')
            if not isinstance(tool_call_id, str):
                continue

            metadata = part.get('metadata')
            if not isinstance(metadata, list):
                continue

            ui_parts = metadata_parts_by_call_id.setdefault(tool_call_id, [])

            for item in metadata:
                if not isinstance(item, dict):
                    continue

                chunk_type = item.get('type')
                if chunk_type == 'source-url':
                    source_id = item.get('source_id')
                    url = item.get('url')
                    title = item.get('title')
                    if not isinstance(source_id, str) or not isinstance(url, str):
                        continue

                    source_part: dict[str, JsonValue] = {
                        'type': 'source-url',
                        'sourceId': source_id,
                        'url': url,
                    }
                    if isinstance(title, str):
                        source_part['title'] = title

                    provider_metadata = item.get('provider_metadata')
                    if provider_metadata is not None:
                        source_part['providerMetadata'] = deepcopy(provider_metadata)

                    ui_parts.append(source_part)
                    continue

                if isinstance(chunk_type, str) and chunk_type.startswith('data-'):
                    data_part: dict[str, JsonValue] = {'type': chunk_type}

                    chunk_id = item.get('id')
                    if isinstance(chunk_id, str):
                        data_part['id'] = chunk_id

                    if 'data' in item:
                        data_part['data'] = deepcopy(item['data'])

                    ui_parts.append(data_part)

    return metadata_parts_by_call_id


def _inject_tool_metadata_parts(
    ui_messages: JsonValue,
    model_messages_json: JsonValue,
) -> JsonValue:
    if not isinstance(ui_messages, list):
        return ui_messages

    metadata_parts_by_call_id = _metadata_parts_by_tool_call_id(model_messages_json)
    if not metadata_parts_by_call_id:
        return ui_messages

    for message in ui_messages:
        if not isinstance(message, dict):
            continue

        parts = message.get('parts')
        if not isinstance(parts, list):
            continue

        merged_parts: list[JsonValue] = []
        for part in parts:
            merged_parts.append(part)

            if not isinstance(part, dict):
                continue

            tool_call_id = part.get('toolCallId')
            if not isinstance(tool_call_id, str):
                continue

            metadata_parts = metadata_parts_by_call_id.pop(tool_call_id, None)
            if metadata_parts:
                merged_parts.extend(deepcopy(metadata_parts))

        message['parts'] = merged_parts

    return ui_messages


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


def create_chat_router(
    *,
    agent: Agent[Any, Any],
    models: ModelsParam,
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
    async def create_conversation() -> JSONResponse:
        payload = CreateConversationResponse(id=str(uuid4()))
        return JSONResponse(payload.model_dump(by_alias=True))

    @router.get('/configure')
    async def configure_frontend() -> JSONResponse:
        config = ConfigureFrontend(
            models=model_infos,
            can_override_system_prompt=can_override_system_prompt,
            default_system_prompt=default_system_prompt,
        )
        return JSONResponse(config.model_dump(by_alias=True))

    @router.get('/health')
    async def health(request: Request) -> JSONResponse:
        settings = getattr(request.app.state, 'settings', None)
        redis_runtime = getattr(request.app.state, 'redis_runtime', None)
        return JSONResponse(
            {
                'ok': True,
                'profile': str(getattr(settings, 'profile', 'unknown')),
                'redisBackend': (
                    'redislite'
                    if getattr(redis_runtime, 'redislite_client', None)
                    else 'redis'
                ),
                'redisUrl': getattr(redis_runtime, 'redis_url', None),
            }
        )

    @router.post('/chat/{conversation_id}')
    async def post_chat(request: Request, conversation_id: str) -> Response:
        adapter = await VercelAIAdapter[Any, Any].from_request(
            request,
            agent=agent,
        )
        extra_data = ChatRequestExtra.model_validate(
            adapter.run_input.__pydantic_extra__
        )

        if extra_data.model and extra_data.model not in model_ids:
            return JSONResponse(
                {
                    'error': (
                        f'Model "{extra_data.model}" is not in the allowed models list'
                    )
                },
                status_code=400,
            )

        if extra_data.system_prompt and not can_override_system_prompt:
            return JSONResponse(
                {'error': 'System prompt override is not available for this agent'},
                status_code=400,
            )

        model_ref = model_id_to_ref.get(extra_data.model) if extra_data.model else None
        instructions = extra_data.system_prompt if can_override_system_prompt else None

        db_runtime = getattr(request.app.state, 'db_runtime', None)

        async def on_complete(result: AgentRunResult[Any]) -> None:
            if not isinstance(db_runtime, DatabaseRuntime):
                logger.warning(
                    'db_runtime is not available; skipping AgentRunResult persistence'
                )
                return

            agent_key = (
                extra_data.agent_key or getattr(agent, 'name', None) or 'default'
            )

            try:
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
            except Exception:
                logger.exception('Failed to persist AgentRunResult snapshot')

        return adapter.streaming_response(
            adapter.run_stream(
                model=model_ref,
                instructions=instructions,
                on_complete=on_complete,
            )
        )

    @router.get('/chat/{conversation_id}')
    async def get_chat(conversation_id: str, request: Request) -> JSONResponse:
        db_runtime = getattr(request.app.state, 'db_runtime', None)
        if not isinstance(db_runtime, DatabaseRuntime):
            return JSONResponse({'messages': []})

        latest_snapshot = _latest_snapshot(db_runtime, conversation_id)
        if latest_snapshot is None:
            return JSONResponse({'messages': []})

        model_messages = _messages_from_json(latest_snapshot.model_messages_json)
        ui_messages = VercelAIAdapter[Any, Any].dump_messages(model_messages)
        encoded_messages = jsonable_encoder(ui_messages)
        patched_messages = _inject_tool_metadata_parts(
            encoded_messages,
            latest_snapshot.model_messages_json,
        )
        return JSONResponse({'messages': patched_messages})

    @router.get('/chats')
    async def list_chats(request: Request) -> JSONResponse:
        db_runtime = getattr(request.app.state, 'db_runtime', None)
        if not isinstance(db_runtime, DatabaseRuntime):
            payload = ConversationsResponse(conversations=[])
            return JSONResponse(payload.model_dump(by_alias=True))

        with db_runtime.session() as session:
            snapshots = session.exec(select(AgentRunSnapshot)).all()

        latest_by_conversation: dict[str, AgentRunSnapshot] = {}
        for snapshot in snapshots:
            current = latest_by_conversation.get(snapshot.conversation_id)
            if current is None or snapshot.created_at > current.created_at:
                latest_by_conversation[snapshot.conversation_id] = snapshot

        summaries: list[ConversationSummary] = []
        for conversation_id, snapshot in latest_by_conversation.items():
            messages = _messages_from_json(snapshot.model_messages_json)
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
        payload = ConversationsResponse(conversations=sorted_summaries)
        return JSONResponse(payload.model_dump(by_alias=True))

    @router.delete('/chat/{conversation_id}')
    async def delete_chat(conversation_id: str, request: Request) -> JSONResponse:
        db_runtime = getattr(request.app.state, 'db_runtime', None)
        if not isinstance(db_runtime, DatabaseRuntime):
            return JSONResponse(
                {'ok': False, 'error': 'Database runtime unavailable'},
                status_code=503,
            )

        with db_runtime.session() as session:
            snapshots = session.exec(
                select(AgentRunSnapshot).where(
                    AgentRunSnapshot.conversation_id == conversation_id
                )
            ).all()
            for snapshot in snapshots:
                session.delete(snapshot)
            session.commit()

        return JSONResponse({'ok': True})

    return router
