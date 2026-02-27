from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

from fastapi.testclient import TestClient

from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import create_chat_run, save_run_snapshot


def test_stream_returns_204_when_no_active_run(client: TestClient) -> None:
    response = client.get('/api/chat/conversation-1/stream')
    assert response.status_code == 204


def test_stream_returns_204_when_latest_snapshot_matches_active_run(
    client: TestClient, db_runtime: DatabaseRuntime
) -> None:
    conversation_id = 'conversation-2'
    run_id = 'run-2'

    with db_runtime.session() as session:
        create_chat_run(session, run_id, conversation_id, 'sql')
        save_run_snapshot(
            session,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_key='sql',
            model_messages_json=[],
        )

    with patch('chatbot.chat_router.iter_stream_events') as iter_mock:
        response = client.get(f'/api/chat/{conversation_id}/stream')

    assert response.status_code == 204
    iter_mock.assert_not_called()


def test_stream_relays_chunks_for_active_run_without_snapshot(
    client: TestClient, db_runtime: DatabaseRuntime
) -> None:
    conversation_id = 'conversation-3'
    run_id = 'run-3'

    with db_runtime.session() as session:
        create_chat_run(session, run_id, conversation_id, 'sql')

    async def fake_iter_stream_events(
        redis_url: str,
        stream_key: str,
        *,
        start_id: str = '0-0',
        block_ms: int = 15_000,
    ) -> AsyncIterator[tuple[str, str]]:
        del redis_url
        del stream_key
        del start_id
        del block_ms
        yield 'chunk', 'data: {"type":"text-delta","delta":"Hello"}\n\n'
        yield 'terminal', ''

    with (
        patch('chatbot.chat_router.iter_stream_events', fake_iter_stream_events),
        client.stream('GET', f'/api/chat/{conversation_id}/stream') as response,
    ):
        body = ''.join(response.iter_text())

    assert response.status_code == 200
    assert response.headers.get('x-vercel-ai-ui-message-stream') == 'v1'
    assert 'text-delta' in body
    assert 'Hello' in body
