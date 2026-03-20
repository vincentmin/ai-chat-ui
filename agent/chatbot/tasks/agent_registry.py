from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model, infer_model

from .. import arxiv_agent as arxiv_agent_module
from .. import sql_agent as sql_agent_module
from ..settings import get_settings

ModelsParam = Mapping[str, Model | KnownModelName | str]

# All known agent keys. Order is stable and used for team_agents lists.
AGENT_KEYS: list[str] = ['sql', 'arxiv']

_AGENT_DESCRIPTIONS: dict[str, str] = {
    'sql': 'An expert SQL assistant using the Chinook sample database.',
    'arxiv': 'An expert research assistant with access to Arxiv papers.',
}

_TEAM_COLLAB_TEMPLATE = (
    '## Team collaboration\n'
    'You are part of a team of agents. Your teammates are:\n'
    '{teammates}\n\n'
    'Messages from other agents appear as user messages prefixed with '
    '"[Message from <agent>]: ". When another agent asks you to do '
    'something or requests a reply, you MUST use the `tell` tool to '
    'send your response back — simply writing text in your reply does '
    'NOT deliver it to the other agent.\n\n'
    'The `tell` tool is asynchronous: it delivers your message and '
    'returns immediately. You do not need to wait for a reply. '
    'If the other agent responds later, you will be automatically '
    'woken up with their reply as a new "[Message from ...]" message. '
    'So after calling `tell`, finish your current turn normally — '
    'you can continue doing other work if there is any, or end with '
    'a brief status message to the user. '
    'The end user has visibility into all your messages, '
    'so you can inform them using your regular messages.'
)


def get_team_instructions(agent_key: str) -> str:
    """Build the team-collaboration instruction block for the given agent."""
    teammates = '\n'.join(
        f'- {key}: {desc}'
        for key, desc in _AGENT_DESCRIPTIONS.items()
        if key != agent_key
    )
    return _TEAM_COLLAB_TEMPLATE.format(teammates=teammates)


def get_agent(
    agent_key: str,
    history_processors: Sequence[Any] | None = None,
) -> Agent[Any, Any]:
    """Create a fresh agent with optional per-run history processors."""
    if agent_key == 'sql':
        return sql_agent_module.make_agent(history_processors=history_processors)
    if agent_key == 'arxiv':
        return arxiv_agent_module.make_agent(history_processors=history_processors)
    raise ValueError(f'Unsupported agent key: {agent_key}')


def get_team_agents() -> list[str]:
    """Return the list of all agent keys in the team."""
    return list(AGENT_KEYS)


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
    # Use the module-level singleton agents for model lookup — they share the same
    # model configuration as factory-created agents but avoid unnecessary allocation.
    if agent_key == 'sql':
        lookup_agent = sql_agent_module.agent
    elif agent_key == 'arxiv':
        lookup_agent = arxiv_agent_module.agent
    else:
        raise ValueError(f'Unsupported agent key: {agent_key}')
    model_lookup = build_model_lookup(lookup_agent, settings.available_models())
    return model_lookup.get(model_id)
