from __future__ import annotations as _annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic.alias_generators import to_camel
from pydantic_ai import Agent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

AgentDepsT = TypeVar('AgentDepsT')
OutputDataT = TypeVar('OutputDataT')


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    agent: Agent[AgentDepsT, OutputDataT]


class AgentInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str


class ConfigureFrontend(BaseModel, alias_generator=to_camel, populate_by_name=True):
    agents: list[AgentInfo]


class ChatRequestExtra(
    BaseModel, extra='ignore', alias_generator=to_camel, populate_by_name=True
):
    agent_id: str | None = None


def validate_request_options(
    extra_data: ChatRequestExtra, agent_ids: set[str]
) -> str | None:
    if extra_data.agent_id and extra_data.agent_id not in agent_ids:
        return f'Agent "{extra_data.agent_id}" is not in the allowed agents list'
    return None


def create_chat_router(
    *,
    agents: dict[str, Agent[AgentDepsT, OutputDataT]],
) -> APIRouter:
    if not agents:
        raise ValueError('At least one agent must be configured')

    agent_infos = [
        AgentInfo(id=agent_id, name=to_camel(agent_id)) for agent_id in agents
    ]
    agent_ids = set(agents.keys())
    default_agent_id = next(iter(agents))
    router = APIRouter()

    @router.options('/chat')
    async def options_chat() -> Response:
        return Response()

    @router.get('/configure')
    async def configure_frontend() -> JSONResponse:
        config = ConfigureFrontend(agents=agent_infos)
        return JSONResponse(config.model_dump(by_alias=True))

    @router.get('/health')
    async def health() -> JSONResponse:
        return JSONResponse({'ok': True})

    @router.post('/chat')
    async def post_chat(request: Request) -> Response:
        default_agent = agents[default_agent_id]
        adapter = await VercelAIAdapter[AgentDepsT, OutputDataT].from_request(
            request, agent=default_agent
        )
        extra_data = ChatRequestExtra.model_validate(
            adapter.run_input.__pydantic_extra__
        )

        if error := validate_request_options(extra_data, agent_ids):
            return JSONResponse({'error': error}, status_code=400)

        selected_agent_id = extra_data.agent_id or default_agent_id
        selected_agent = agents[selected_agent_id]

        return await VercelAIAdapter[AgentDepsT, OutputDataT].dispatch_request(
            request,
            agent=selected_agent,
        )

    return router
