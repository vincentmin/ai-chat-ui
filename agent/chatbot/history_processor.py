from __future__ import annotations

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart

from .agent_deps import AgentDeps
from .mailbox import MailboxMessage, drain_mailbox


def mailbox_messages_to_model_requests(
    messages: list[MailboxMessage],
) -> list[ModelRequest]:
    """Convert mailbox messages into ModelRequest parts for injection."""
    return [
        ModelRequest(
            parts=[
                UserPromptPart(content=f'[Message from {msg.sender}]: {msg.content}')
            ]
        )
        for msg in messages
    ]


async def mailbox_history_processor(
    ctx: RunContext[AgentDeps], messages: list[ModelMessage]
) -> list[ModelMessage]:
    """Drain the agent mailbox before each model invocation.

    This uses ``RunContext`` so the processor reads the Redis client and
    conversation metadata from runtime deps instead of mutating the agent.
    """
    mailbox = await drain_mailbox(
        ctx.deps.redis_client,
        ctx.deps.agent_key,
        ctx.deps.conversation_id,
    )
    if not mailbox:
        return messages

    injected = mailbox_messages_to_model_requests(mailbox)
    return [*messages, *injected]
