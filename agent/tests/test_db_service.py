from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from chatbot.db.models import AgentRunSnapshot, ChatRun, ChatRunStatus
from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import (
    create_chat_run,
    delete_chat_records,
    get_active_run,
    get_latest_snapshot,
    get_latest_snapshot_per_conversation,
    save_run_snapshot,
    supersede_stale_runs,
    update_run_status,
    update_run_task_id,
)


def test_create_chat_run_inserts_queued_record(db_runtime: DatabaseRuntime) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-1', 'conversation-1', 'sql')
        run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-1')).one()

    assert run.conversation_id == 'conversation-1'
    assert run.agent_key == 'sql'
    assert run.status == ChatRunStatus.QUEUED.value
    assert run.task_id is None


def test_update_run_task_id_sets_task_identifier(db_runtime: DatabaseRuntime) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-2', 'conversation-1', 'sql')
        update_run_task_id(session, 'run-2', 'task-123')
        run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-2')).one()

    assert run.task_id == 'task-123'


def test_get_active_run_prefers_latest_running_or_queued(
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-old', 'conversation-1', 'sql')
        create_chat_run(session, 'run-new', 'conversation-1', 'sql')
        create_chat_run(session, 'run-done', 'conversation-1', 'sql')

        old_run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-old')).one()
        new_run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-new')).one()
        done_run = session.exec(
            select(ChatRun).where(ChatRun.run_id == 'run-done')
        ).one()

        old_run.status = ChatRunStatus.RUNNING.value
        new_run.status = ChatRunStatus.QUEUED.value
        done_run.status = ChatRunStatus.COMPLETED.value

        base = datetime.now(UTC)
        old_run.created_at = base
        new_run.created_at = base + timedelta(seconds=1)
        done_run.created_at = base + timedelta(seconds=2)

        session.add(old_run)
        session.add(new_run)
        session.add(done_run)
        session.commit()

        active = get_active_run(session, 'conversation-1', 'sql')

    assert active is not None
    assert active.run_id == 'run-new'


def test_supersede_stale_runs_marks_active_runs_failed(
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-queued', 'conversation-1', 'sql')
        create_chat_run(session, 'run-running', 'conversation-1', 'sql')
        create_chat_run(session, 'run-completed', 'conversation-1', 'sql')

        queued = session.exec(
            select(ChatRun).where(ChatRun.run_id == 'run-queued')
        ).one()
        running = session.exec(
            select(ChatRun).where(ChatRun.run_id == 'run-running')
        ).one()
        completed = session.exec(
            select(ChatRun).where(ChatRun.run_id == 'run-completed')
        ).one()

        queued.status = ChatRunStatus.QUEUED.value
        running.status = ChatRunStatus.RUNNING.value
        completed.status = ChatRunStatus.COMPLETED.value

        session.add(queued)
        session.add(running)
        session.add(completed)
        session.commit()

        supersede_stale_runs(session, 'conversation-1', 'sql')

        refreshed = {
            run.run_id: run
            for run in session.exec(
                select(ChatRun).where(ChatRun.conversation_id == 'conversation-1')
            ).all()
        }

    assert refreshed['run-queued'].status == ChatRunStatus.FAILED.value
    assert refreshed['run-running'].status == ChatRunStatus.FAILED.value
    assert refreshed['run-completed'].status == ChatRunStatus.COMPLETED.value
    assert refreshed['run-queued'].error == 'superseded by new message'
    assert refreshed['run-running'].error == 'superseded by new message'


def test_snapshot_queries_return_latest_values(db_runtime: DatabaseRuntime) -> None:
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id='conversation-1',
            run_id='run-1',
            agent_key='sql',
            model_messages_json=[],
        )
        save_run_snapshot(
            session,
            conversation_id='conversation-1',
            run_id='run-2',
            agent_key='sql',
            model_messages_json=[{'latest': True}],
        )
        save_run_snapshot(
            session,
            conversation_id='conversation-2',
            run_id='run-3',
            agent_key='sql',
            model_messages_json=[],
        )

        snapshots = session.exec(
            select(AgentRunSnapshot).where(AgentRunSnapshot.agent_key == 'sql')
        ).all()
        for index, snapshot in enumerate(snapshots):
            snapshot.created_at = datetime.now(UTC) + timedelta(seconds=index)
            session.add(snapshot)
        session.commit()

        latest_conversation_1 = get_latest_snapshot(session, 'conversation-1', 'sql')
        latest_per_conversation = get_latest_snapshot_per_conversation(session, 'sql')

    assert latest_conversation_1 is not None
    assert latest_conversation_1.run_id == 'run-2'
    assert set(latest_per_conversation.keys()) == {'conversation-1', 'conversation-2'}
    assert latest_per_conversation['conversation-1'].run_id == 'run-2'


def test_delete_chat_records_removes_only_target_conversation(
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id='conversation-1',
            run_id='run-1',
            agent_key='sql',
            model_messages_json=[],
        )
        save_run_snapshot(
            session,
            conversation_id='conversation-2',
            run_id='run-2',
            agent_key='sql',
            model_messages_json=[],
        )

        delete_chat_records(session, 'conversation-1', 'sql')

        remaining = session.exec(select(AgentRunSnapshot)).all()

    assert len(remaining) == 1
    assert remaining[0].conversation_id == 'conversation-2'


def test_update_run_status_updates_status_and_error(
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-1', 'conversation-1', 'sql')
        before = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-1')).one()
        previous_updated_at = before.updated_at

        update_run_status(
            session,
            'run-1',
            ChatRunStatus.FAILED,
            error='boom',
        )

        after = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-1')).one()

    assert after.status == ChatRunStatus.FAILED.value
    assert after.error == 'boom'
    assert after.updated_at >= previous_updated_at
