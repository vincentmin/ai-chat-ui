from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from redis import asyncio as redis

STREAM_FIELD_KIND = 'kind'
STREAM_FIELD_EVENT = 'event'
STREAM_KIND_CHUNK = 'chunk'
STREAM_KIND_TERMINAL = 'terminal'


def chat_run_stream_key(*, agent_key: str, conversation_id: str, run_id: str) -> str:
    return f'chat:stream:{agent_key}:{conversation_id}:{run_id}'


async def publish_chunk(redis_url: str, stream_key: str, encoded_chunk: str) -> None:
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await client.xadd(
            stream_key,
            {
                STREAM_FIELD_KIND: STREAM_KIND_CHUNK,
                STREAM_FIELD_EVENT: encoded_chunk,
            },
        )
    finally:
        await client.aclose()


async def publish_terminal(redis_url: str, stream_key: str) -> None:
    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await client.xadd(
            stream_key,
            {
                STREAM_FIELD_KIND: STREAM_KIND_TERMINAL,
                STREAM_FIELD_EVENT: '',
            },
        )
    finally:
        await client.aclose()


async def iter_stream_events(
    redis_url: str,
    stream_key: str,
    *,
    start_id: str = '0-0',
    block_ms: int = 15_000,
) -> AsyncIterator[tuple[str, str]]:
    """Yield stream events as (kind, payload) from Redis Streams."""
    client = redis.from_url(redis_url, decode_responses=True)
    current_id = start_id

    try:
        while True:
            entries = await client.xread(
                {stream_key: current_id},
                block=block_ms,
                count=100,
            )
            if not entries:
                await asyncio.sleep(0.05)
                continue

            for _stream_name, messages in entries:
                for message_id, fields in messages:
                    current_id = message_id
                    kind = fields.get(STREAM_FIELD_KIND, STREAM_KIND_CHUNK)
                    payload = fields.get(STREAM_FIELD_EVENT, '')
                    yield kind, payload
    finally:
        await client.aclose()
