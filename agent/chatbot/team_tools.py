from __future__ import annotations

import logging

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from .agent_deps import AgentDeps
from .mailbox import push_to_mailbox

logger = logging.getLogger(__name__)

_AGENT_DESCRIPTIONS: dict[str, str] = {
    'sql': 'An expert SQL assistant using the Chinook sample database.',
    'arxiv': 'An expert research assistant with access to Arxiv papers.',
}


async def tell(ctx: RunContext[AgentDeps], agent: str, message: str) -> str:
    """Send a message to another agent in the team.

    The message is delivered to the target agent's mailbox. If the target
    agent is idle, a new run is started for it automatically.

    This tool returns immediately — it does NOT wait for the other agent
    to respond.
    """
    deps = ctx.deps
    if agent == deps.agent_key:
        raise ModelRetry('You cannot send a message to yourself.')
    if agent not in deps.team_agents:
        others = [a for a in deps.team_agents if a != deps.agent_key]
        raise ModelRetry(
            f'Unknown agent "{agent}". Available agents: {", ".join(others)}'
        )

    await push_to_mailbox(
        deps.redis_client,
        agent_key=agent,
        conversation_id=deps.conversation_id,
        sender=deps.agent_key,
        content=message,
    )

    # Wake up the target agent if it has no active run.
    # Import here to avoid circular dependency with run_agent_task.
    from .tasks.run_agent_task import enqueue_wakeup_run

    await enqueue_wakeup_run(
        agent_key=agent,
        conversation_id=deps.conversation_id,
    )

    return f'Message sent to {agent}.'


TEAM_TOOLSET = FunctionToolset[AgentDeps]([tell])


def build_team_instructions(agent_key: str, team_agents: list[str]) -> str | None:
    """Return runtime instructions for inter-agent collaboration."""
    teammates = [agent for agent in team_agents if agent != agent_key]
    if not teammates:
        return None

    teammate_lines = '\n'.join(
        f'- {agent}: {_AGENT_DESCRIPTIONS.get(agent, agent)}' for agent in teammates
    )

    return (
        '## Team collaboration\n'
        'You are part of a team of agents. Your teammates are:\n'
        f'{teammate_lines}\n\n'
        'Messages from other agents appear as user messages prefixed with '
        '"[Message from <agent>]: ". When another agent asks you to do '
        'something or requests a reply, you MUST use the `tell` tool to '
        'send your response back; simply writing text in your reply does '
        'not deliver it to the other agent.\n\n'
        'The `tell` tool is asynchronous: it delivers your message and '
        'returns immediately. You do not need to wait for a reply. '
        'If the other agent responds later, you will be automatically '
        'woken up with their reply as a new "[Message from ...]" message. '
        'After calling `tell`, finish your current turn normally. '
        'The end user can see all agent messages, so keep coordination readable.'
    )
