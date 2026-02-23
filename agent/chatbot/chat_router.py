from __future__ import annotations as _annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.alias_generators import to_camel
from pydantic_ai import Agent
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from .db import AgentRunSnapshot, to_json_snapshot
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
    conversation_id: str | None = None
    agent_key: str | None = None


def _conversation_id_from_result(
    result: AgentRunResult[Any],
    requested_conversation_id: str | None,
) -> str:
    if requested_conversation_id:
        return requested_conversation_id

    metadata = result.metadata
    if isinstance(metadata, dict):
        maybe_conversation_id = metadata.get('conversation_id')
        if isinstance(maybe_conversation_id, str) and maybe_conversation_id:
            return maybe_conversation_id

    if result.run_id:
        return result.run_id

    return str(uuid4())


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

    @router.post('/chat')
    async def post_chat(request: Request) -> Response:
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

            conversation_id = _conversation_id_from_result(
                result,
                extra_data.conversation_id,
            )
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
                            agent_run_result_json=to_json_snapshot(result),
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

    return router
