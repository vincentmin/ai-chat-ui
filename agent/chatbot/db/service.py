from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from .json_types import JsonValue
from .models import AgentRunSnapshot, ChatRun, ChatRunStatus

logger = logging.getLogger(__name__)


def supersede_stale_runs(
    session: Session, conversation_id: str, agent_key: str
) -> None:
    """Mark any queued/running ChatRuns for this conversation as failed (superseded)."""
    active_statuses = {ChatRunStatus.QUEUED.value, ChatRunStatus.RUNNING.value}
    stale_runs = session.exec(
        select(ChatRun).where(
            ChatRun.conversation_id == conversation_id,
            ChatRun.agent_key == agent_key,
        )
    ).all()
    for stale in stale_runs:
        if stale.status in active_statuses:
            stale.status = ChatRunStatus.FAILED.value
            stale.error = 'superseded by new message'
            stale.updated_at = datetime.now(UTC)
            session.add(stale)
    session.commit()


def create_chat_run(
    session: Session, run_id: str, conversation_id: str, agent_key: str
) -> None:
    """Insert a new ChatRun record with QUEUED status."""
    session.add(
        ChatRun(
            run_id=run_id,
            conversation_id=conversation_id,
            agent_key=agent_key,
            status=ChatRunStatus.QUEUED.value,
        )
    )
    session.commit()


def update_run_task_id(session: Session, run_id: str, task_id: str) -> None:
    """Patch the task_id on an existing ChatRun."""
    run = session.exec(select(ChatRun).where(ChatRun.run_id == run_id)).one_or_none()
    if run is not None:
        run.task_id = task_id
        session.add(run)
        session.commit()


def get_latest_snapshot(
    session: Session, conversation_id: str, agent_key: str
) -> AgentRunSnapshot | None:
    """Return the most recent AgentRunSnapshot for a conversation, or None."""
    snapshots = session.exec(
        select(AgentRunSnapshot).where(
            AgentRunSnapshot.conversation_id == conversation_id,
            AgentRunSnapshot.agent_key == agent_key,
        )
    ).all()
    return max(snapshots, key=lambda s: s.created_at, default=None)


def get_latest_snapshot_per_conversation(
    session: Session, agent_key: str
) -> dict[str, AgentRunSnapshot]:
    """Return the most recent snapshot per conversation_id for a given agent_key."""
    snapshots = session.exec(
        select(AgentRunSnapshot).where(AgentRunSnapshot.agent_key == agent_key)
    ).all()
    latest: dict[str, AgentRunSnapshot] = {}
    for snapshot in snapshots:
        current = latest.get(snapshot.conversation_id)
        if current is None or snapshot.created_at > current.created_at:
            latest[snapshot.conversation_id] = snapshot
    return latest


def get_active_run(
    session: Session, conversation_id: str, agent_key: str
) -> ChatRun | None:
    """Return the most recent QUEUED or RUNNING ChatRun for a conversation, or None."""
    active_statuses = {ChatRunStatus.QUEUED.value, ChatRunStatus.RUNNING.value}
    runs = session.exec(
        select(ChatRun).where(
            ChatRun.conversation_id == conversation_id,
            ChatRun.agent_key == agent_key,
        )
    ).all()
    active = [r for r in runs if r.status in active_statuses]
    return max(active, key=lambda r: r.created_at) if active else None


def delete_chat_records(session: Session, conversation_id: str, agent_key: str) -> None:
    """Delete all AgentRunSnapshot records for a conversation."""
    snapshots = session.exec(
        select(AgentRunSnapshot).where(
            AgentRunSnapshot.conversation_id == conversation_id,
            AgentRunSnapshot.agent_key == agent_key,
        )
    ).all()
    for snapshot in snapshots:
        session.delete(snapshot)
    session.commit()


def save_run_snapshot(
    session: Session,
    conversation_id: str,
    run_id: str | None,
    agent_key: str,
    model_messages_json: JsonValue,
) -> None:
    """Insert an AgentRunSnapshot for a completed run."""
    session.add(
        AgentRunSnapshot(
            conversation_id=conversation_id,
            run_id=run_id,
            agent_key=agent_key,
            model_messages_json=model_messages_json,
        )
    )
    session.commit()


def update_run_status(
    session: Session,
    run_id: str,
    status: ChatRunStatus,
    error: str | None = None,
) -> None:
    """Update the status (and optionally error) of a ChatRun."""
    run = session.exec(select(ChatRun).where(ChatRun.run_id == run_id)).one_or_none()
    if run is None:
        return
    run.status = status.value
    run.error = error
    run.updated_at = datetime.now(UTC)
    session.add(run)
    session.commit()
