from __future__ import annotations

from collections.abc import Iterator

import pytest
from docker.errors import DockerException
from redis import asyncio as redis
from testcontainers.redis import RedisContainer

from chatbot.streaming.redis_stream import (
    STREAM_KIND_CHUNK,
    STREAM_KIND_TERMINAL,
    chat_run_stream_key,
    iter_stream_events,
    publish_chunk,
    publish_terminal,
)


@pytest.fixture
def redis_url() -> Iterator[str]:
    try:
        with RedisContainer('redis:6.2-alpine') as container:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(6379)
            yield f'redis://{host}:{port}'
    except DockerException as exc:
        pytest.skip(f'Docker is unavailable for Redis integration tests: {exc}')


def test_chat_run_stream_key_builds_expected_pattern() -> None:
    key = chat_run_stream_key(
        agent_key='sql',
        conversation_id='conversation-1',
        run_id='run-1',
    )

    assert key == 'chat:stream:sql:conversation-1:run-1'


@pytest.mark.anyio
async def test_publish_and_iter_stream_events_round_trip(redis_url: str) -> None:
    stream_key = chat_run_stream_key(
        agent_key='sql',
        conversation_id='conversation-1',
        run_id='run-1',
    )

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await publish_chunk(client, stream_key, 'data: {"delta":"hello"}\n\n')
        await publish_terminal(client, stream_key)
    finally:
        await client.aclose()

    observed: list[tuple[str, str]] = []
    async for kind, payload in iter_stream_events(
        redis_url,
        stream_key,
        start_id='0-0',
        block_ms=200,
    ):
        observed.append((kind, payload))
        if kind == STREAM_KIND_TERMINAL:
            break

    assert observed == [
        (STREAM_KIND_CHUNK, 'data: {"delta":"hello"}\n\n'),
        (STREAM_KIND_TERMINAL, ''),
    ]


@pytest.mark.anyio
async def test_iter_stream_events_resumes_after_start_id(redis_url: str) -> None:
    stream_key = chat_run_stream_key(
        agent_key='sql',
        conversation_id='conversation-2',
        run_id='run-2',
    )

    client = redis.from_url(redis_url, decode_responses=True)
    try:
        await publish_chunk(client, stream_key, 'data: {"delta":"first"}\n\n')
        first_entry_id = (await client.xrange(stream_key))[0][0]
        await publish_chunk(client, stream_key, 'data: {"delta":"second"}\n\n')
        await publish_terminal(client, stream_key)
    finally:
        await client.aclose()

    observed: list[tuple[str, str]] = []
    async for kind, payload in iter_stream_events(
        redis_url,
        stream_key,
        start_id=first_entry_id,
        block_ms=200,
    ):
        observed.append((kind, payload))
        if kind == STREAM_KIND_TERMINAL:
            break

    assert observed == [
        (STREAM_KIND_CHUNK, 'data: {"delta":"second"}\n\n'),
        (STREAM_KIND_TERMINAL, ''),
    ]
