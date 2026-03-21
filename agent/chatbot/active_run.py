from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Literal

from redis import asyncio as redis
from redis.exceptions import WatchError

ACTIVE_RUN_TTL_SECONDS = 90
ACTIVE_RUN_HEARTBEAT_SECONDS = 30


@dataclass
class ActiveRunLease:
    run_id: str
    agent_key: str
    conversation_id: str
    status: Literal['starting', 'running']
    acquired_at: float
    heartbeat_at: float

    def to_json(self) -> str:
        return json.dumps(
            {
                'run_id': self.run_id,
                'agent_key': self.agent_key,
                'conversation_id': self.conversation_id,
                'status': self.status,
                'acquired_at': self.acquired_at,
                'heartbeat_at': self.heartbeat_at,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> ActiveRunLease:
        data = json.loads(raw)
        return cls(
            run_id=data['run_id'],
            agent_key=data['agent_key'],
            conversation_id=data['conversation_id'],
            status=data['status'],
            acquired_at=data['acquired_at'],
            heartbeat_at=data['heartbeat_at'],
        )


def active_run_key(agent_key: str, conversation_id: str) -> str:
    return f'active-run:{agent_key}:{conversation_id}'


def new_active_run_lease(
    run_id: str,
    agent_key: str,
    conversation_id: str,
    *,
    status: Literal['starting', 'running'] = 'starting',
) -> ActiveRunLease:
    now = time.time()
    return ActiveRunLease(
        run_id=run_id,
        agent_key=agent_key,
        conversation_id=conversation_id,
        status=status,
        acquired_at=now,
        heartbeat_at=now,
    )


async def try_acquire_active_run(
    client: redis.Redis,
    lease: ActiveRunLease,
    *,
    ttl_seconds: int = ACTIVE_RUN_TTL_SECONDS,
) -> bool:
    return bool(
        await client.set(
            active_run_key(lease.agent_key, lease.conversation_id),
            lease.to_json(),
            ex=ttl_seconds,
            nx=True,
        )
    )


async def get_active_run_lease(
    client: redis.Redis,
    agent_key: str,
    conversation_id: str,
) -> ActiveRunLease | None:
    raw = await client.get(active_run_key(agent_key, conversation_id))
    if not raw:
        return None
    return ActiveRunLease.from_json(raw)


async def refresh_active_run(
    client: redis.Redis,
    lease: ActiveRunLease,
    *,
    status: Literal['starting', 'running'] | None = None,
    ttl_seconds: int = ACTIVE_RUN_TTL_SECONDS,
) -> ActiveRunLease | None:
    key = active_run_key(lease.agent_key, lease.conversation_id)

    while True:
        try:
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if not raw:
                    return None

                current = ActiveRunLease.from_json(raw)
                if current.run_id != lease.run_id:
                    return None

                updated = ActiveRunLease(
                    run_id=current.run_id,
                    agent_key=current.agent_key,
                    conversation_id=current.conversation_id,
                    status=status or current.status,
                    acquired_at=current.acquired_at,
                    heartbeat_at=time.time(),
                )
                pipe.multi()
                pipe.set(key, updated.to_json(), ex=ttl_seconds)
                await pipe.execute()
                return updated
        except WatchError:
            continue


async def release_active_run(
    client: redis.Redis,
    agent_key: str,
    conversation_id: str,
    run_id: str,
) -> bool:
    key = active_run_key(agent_key, conversation_id)

    while True:
        try:
            async with client.pipeline(transaction=True) as pipe:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if not raw:
                    return False

                current = ActiveRunLease.from_json(raw)
                if current.run_id != run_id:
                    return False

                pipe.multi()
                pipe.delete(key)
                await pipe.execute()
                return True
        except WatchError:
            continue
