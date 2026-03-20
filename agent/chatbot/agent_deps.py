from __future__ import annotations

from dataclasses import dataclass

from redis import asyncio as redis


@dataclass
class AgentDeps:
    """Dependencies injected into agent tools via RunContext.

    Provides conversation context and inter-agent communication handles
    needed by the ``tell`` tool and other team-aware tools.
    """

    conversation_id: str
    agent_key: str
    team_agents: list[str]
    redis_client: redis.Redis
