from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model, infer_model

from .. import arxiv_agent as arxiv_agent_module
from ..settings import get_settings
from ..sql_agent import agent as sql_agent

ModelsParam = Mapping[str, Model | KnownModelName | str]


def get_agent(agent_key: str) -> Agent[Any, Any]:
    if agent_key == 'sql':
        return sql_agent
    if agent_key == 'arxiv':
        return arxiv_agent_module.agent
    raise ValueError(f'Unsupported agent key: {agent_key}')


def build_model_lookup(
    agent: Agent[Any, Any],
    models: ModelsParam,
) -> dict[str, Model | str]:
    model_id_to_ref: dict[str, Model | str] = {}
    seen_model_keys: set[tuple[str, str]] = set()

    def add_model(model_ref: Model | str | KnownModelName) -> None:
        model = infer_model(model_ref)
        model_key = (model.system, model.model_name)
        model_id = f'{model.system}:{model.model_name}'

        if model_key in seen_model_keys:
            return

        seen_model_keys.add(model_key)
        model_id_to_ref[model_id] = model_ref

    if agent.model is not None:
        add_model(agent.model)

    for model_ref in models.values():
        add_model(model_ref)

    return model_id_to_ref


def resolve_model_ref(agent_key: str, model_id: str | None) -> Model | str | None:
    if not model_id:
        return None

    settings = get_settings()
    agent = get_agent(agent_key)
    model_lookup = build_model_lookup(agent, settings.available_models())
    return model_lookup.get(model_id)
