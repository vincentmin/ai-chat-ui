from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from .json_types import JSON_SQL_TYPE, JsonValue


def utc_now() -> datetime:
    return datetime.now(UTC)


class ChatRunStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'


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
    # Stores run model messages from AgentRunResult.all_messages().
    model_messages_json: JsonValue = Field(
        sa_column=Column(JSON_SQL_TYPE, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)


class ChatRun(SQLModel, table=True):
    __tablename__ = 'chat_task_runs'

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        max_length=64,
    )
    run_id: str = Field(
        sa_column=Column(String(128), nullable=False, unique=True, index=True)
    )
    task_id: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True, index=True),
    )
    conversation_id: str = Field(
        sa_column=Column(String(128), nullable=False, index=True)
    )
    agent_key: str = Field(
        default='default',
        sa_column=Column(String(200), nullable=False, index=True),
    )
    status: str = Field(
        default=ChatRunStatus.QUEUED.value,
        sa_column=Column(String(32), nullable=False, index=True),
    )
    error: str | None = Field(
        default=None,
        sa_column=Column(String(1000), nullable=True),
    )
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
