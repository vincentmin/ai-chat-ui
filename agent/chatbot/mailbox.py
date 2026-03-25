from __future__ import annotations

import json
import time
from dataclasses import dataclass

from redis import asyncio as redis


def _mailbox_key(agent_key: str, conversation_id: str) -> str:
    return f'mailbox:{agent_key}:{conversation_id}'


@dataclass
class MailboxMessage:
    sender: str
    content: str
    timestamp: float

    def to_json(self) -> str:
        return json.dumps(
            {
                'sender': self.sender,
                'content': self.content,
                'timestamp': self.timestamp,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> MailboxMessage:
        data = json.loads(raw)
        return cls(
            sender=data['sender'],
            content=data['content'],
            timestamp=data['timestamp'],
        )


async def push_to_mailbox(
    client: redis.Redis,
    agent_key: str,
    conversation_id: str,
    sender: str,
    content: str,
) -> None:
    """Append a message to the target agent's mailbox."""
    msg = MailboxMessage(sender=sender, content=content, timestamp=time.time())
    await client.rpush(_mailbox_key(agent_key, conversation_id), msg.to_json())  # type: ignore[misc]


async def drain_mailbox(
    client: redis.Redis,
    agent_key: str,
    conversation_id: str,
) -> list[MailboxMessage]:
    """Read and remove all messages from the agent's mailbox.

    Uses a pipeline (LRANGE + DEL) which is safe because drain is only called
    by the single Taskiq worker owning the current run for this
    (agent_key, conversation_id). A message arriving between LRANGE and DEL
    will be picked up by the next drain or post-run check.
    """
    key = _mailbox_key(agent_key, conversation_id)
    async with client.pipeline(transaction=False) as pipe:
        pipe.lrange(key, 0, -1)
        pipe.delete(key)
        results = await pipe.execute()

    raw_messages: list[str] = results[0] or []
    return [MailboxMessage.from_json(raw) for raw in raw_messages]


async def mailbox_is_empty(
    client: redis.Redis,
    agent_key: str,
    conversation_id: str,
) -> bool:
    """Check whether the agent's mailbox is empty without consuming messages."""
    return await client.llen(_mailbox_key(agent_key, conversation_id)) == 0  # type: ignore[misc]
