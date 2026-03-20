from __future__ import annotations

import logging

from pydantic_ai import ModelRetry, RunContext

from .agent_deps import AgentDeps
from .mailbox import push_to_mailbox

logger = logging.getLogger(__name__)


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
