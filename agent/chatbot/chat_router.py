from __future__ import annotations as _annotations

from collections.abc import Mapping, Sequence
from typing import TypeVar

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel
from pydantic_ai import Agent
from pydantic_ai.builtin_tools import AbstractBuiltinTool
from pydantic_ai.models import KnownModelName, Model, infer_model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

AgentDepsT = TypeVar('AgentDepsT')
OutputDataT = TypeVar('OutputDataT')

ModelsParam = (
    Sequence[Model | KnownModelName | str]
    | Mapping[str, Model | KnownModelName | str]
    | None
)


class ModelInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str
    builtin_tools: list[str]


class BuiltinToolInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str


class ConfigureFrontend(BaseModel, alias_generator=to_camel, populate_by_name=True):
    models: list[ModelInfo]
    builtin_tools: list[BuiltinToolInfo]


class ChatRequestExtra(
    BaseModel, extra='ignore', alias_generator=to_camel, populate_by_name=True
):
    model: str | None = None
    builtin_tools: list[str] = Field(default_factory=list)


def validate_request_options(
    extra_data: ChatRequestExtra,
    model_ids: set[str],
    builtin_tool_ids: set[str],
) -> str | None:
    if extra_data.model and extra_data.model not in model_ids:
        return f'Model "{extra_data.model}" is not in the allowed models list'

    invalid_tools = [t for t in extra_data.builtin_tools if t not in builtin_tool_ids]
    if invalid_tools:
        return f'Builtin tool(s) {invalid_tools} not in the allowed tools list'

    return None


def create_chat_router(
    *,
    agent: Agent[AgentDepsT, OutputDataT],
    models: ModelsParam = None,
    builtin_tools: Sequence[AbstractBuiltinTool] | None = None,
    deps: AgentDepsT | None = None,
    model_settings: ModelSettings | None = None,
    instructions: str | None = None,
) -> APIRouter:
    model_id_to_ref: dict[str, Model | str] = {}
    model_infos: list[ModelInfo] = []

    # Builtin tools already on the agent are always available and should not appear as UI options.
    agent_tool_ids = {
        t.unique_id for t in agent._builtin_tools if isinstance(t, AbstractBuiltinTool)
    }  # pyright: ignore[reportPrivateUsage]
    ui_builtin_tools = [
        t for t in (builtin_tools or []) if t.unique_id not in agent_tool_ids
    ]

    all_models: list[tuple[str | None, Model | str]] = []
    if agent.model is not None:
        all_models.append((None, agent.model))
    items = (
        list(models.items())
        if isinstance(models, Mapping)
        else [(None, m) for m in (models or [])]
    )
    all_models.extend(items)

    seen_model_ids: set[str] = set()
    for label, model_ref in all_models:
        model = infer_model(model_ref)
        model_id = (
            model_ref
            if isinstance(model_ref, str)
            else f'{model.system}:{model.model_name}'
        )
        if model_id in seen_model_ids:
            continue
        seen_model_ids.add(model_id)

        display_name = label or model.label
        model_supported_tools = model.profile.supported_builtin_tools
        supported_tool_ids = [
            t.unique_id for t in ui_builtin_tools if type(t) in model_supported_tools
        ]

        model_id_to_ref[model_id] = model_ref
        model_infos.append(
            ModelInfo(id=model_id, name=display_name, builtin_tools=supported_tool_ids)
        )

    model_ids = set(model_id_to_ref.keys())
    allowed_tool_ids = {tool.unique_id for tool in ui_builtin_tools}
    router = APIRouter()

    @router.options('/chat')
    async def options_chat() -> Response:
        return Response()

    @router.get('/configure')
    async def configure_frontend() -> JSONResponse:
        config = ConfigureFrontend(
            models=model_infos,
            builtin_tools=[
                BuiltinToolInfo(id=tool.unique_id, name=tool.label)
                for tool in ui_builtin_tools
            ],
        )
        return JSONResponse(config.model_dump(by_alias=True))

    @router.get('/health')
    async def health() -> JSONResponse:
        return JSONResponse({'ok': True})

    @router.post('/chat')
    async def post_chat(request: Request) -> Response:
        adapter = await VercelAIAdapter[AgentDepsT, OutputDataT].from_request(
            request, agent=agent
        )
        extra_data = ChatRequestExtra.model_validate(
            adapter.run_input.__pydantic_extra__
        )

        if error := validate_request_options(extra_data, model_ids, allowed_tool_ids):
            return JSONResponse({'error': error}, status_code=400)

        model_ref = model_id_to_ref.get(extra_data.model) if extra_data.model else None
        request_builtin_tools = [
            tool
            for tool in ui_builtin_tools
            if tool.unique_id in extra_data.builtin_tools
        ]
        return await VercelAIAdapter[AgentDepsT, OutputDataT].dispatch_request(
            request,
            agent=agent,
            model=model_ref,
            builtin_tools=request_builtin_tools,
            deps=deps,
            model_settings=model_settings,
            instructions=instructions,
        )

    return router
