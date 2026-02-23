from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from .json_types import JSON_SQL_TYPE, JsonValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRunSnapshot(SQLModel, table=True):
    __tablename__ = 'chat_runs'

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        max_length=64,
    )
    conversation_id: str = Field(
        sa_column=Column(String(128), nullable=False, index=True),
    )
    run_id: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True, index=True),
    )
    agent_key: str = Field(
        default='default',
        sa_column=Column(String(200), nullable=False, index=True),
    )
    # Stores the complete AgentRunResult payload, including `_state`.
    agent_run_result_json: JsonValue = Field(
        sa_column=Column(JSON_SQL_TYPE, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
