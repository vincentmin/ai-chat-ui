from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from chatbot.active_run import new_active_run_lease
from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import create_chat_run, save_run_snapshot


async def _get_active_run_lease(*_args: object, **_kwargs: object):
    return None


def test_run_status_returns_inactive_when_no_active_run(client: TestClient) -> None:
    with patch('chatbot.chat_router.get_active_run_lease', _get_active_run_lease):
        response = client.get('/api/chat/conversation-no-run/run')
    assert response.status_code == 200
    payload = response.json()
    assert payload['active'] is False
    assert payload.get('runId') is None
    assert payload.get('status') is None


def test_run_status_returns_inactive_when_snapshot_matches_active_run(
    client: TestClient, db_runtime: DatabaseRuntime
) -> None:
    conversation_id = 'conversation-run-done'
    run_id = 'run-done'

    with db_runtime.session() as session:
        create_chat_run(session, run_id, conversation_id, 'sql')
        save_run_snapshot(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_key='sql',
            model_messages_json=[],
        )

    async def fake_get_active_run_lease(*_args: object, **_kwargs: object):
        return new_active_run_lease(run_id, 'sql', conversation_id, status='running')

    with patch('chatbot.chat_router.get_active_run_lease', fake_get_active_run_lease):
        response = client.get(f'/api/chat/{conversation_id}/run')

    assert response.status_code == 200
    payload = response.json()
    assert payload['active'] is True
    assert payload['runId'] == run_id
    assert payload['status'] == 'running'


def test_run_status_returns_active_when_run_has_no_snapshot(
    client: TestClient, db_runtime: DatabaseRuntime
) -> None:
    conversation_id = 'conversation-run-active'
    run_id = 'run-active'

    with db_runtime.session() as session:
        create_chat_run(session, run_id, conversation_id, 'sql')

    async def fake_get_active_run_lease(*_args: object, **_kwargs: object):
        return new_active_run_lease(run_id, 'sql', conversation_id, status='starting')

    with patch('chatbot.chat_router.get_active_run_lease', fake_get_active_run_lease):
        response = client.get(f'/api/chat/{conversation_id}/run')

    assert response.status_code == 200
    payload = response.json()
    assert payload['active'] is True
    assert payload['runId'] == run_id
    assert payload['status'] == 'starting'
