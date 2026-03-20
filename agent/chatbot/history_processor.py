from __future__ import annotations

from pydantic_ai.messages import ModelMessage, ModelRequest, UserPromptPart
from redis import asyncio as redis

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


def create_mailbox_history_processor(
    redis_client: redis.Redis,
    agent_key: str,
    conversation_id: str,
):
    """Return a history_processor that drains the mailbox before each model invocation.

    Pydantic AI calls ``history_processor`` before every model invocation in
    the react loop, giving us a hook to inject inter-agent messages.
    """

    async def process_history(messages: list[ModelMessage]) -> list[ModelMessage]:
        mailbox = await drain_mailbox(redis_client, agent_key, conversation_id)
        if not mailbox:
            return messages
        injected = mailbox_messages_to_model_requests(mailbox)
        return [*messages, *injected]

    return process_history
