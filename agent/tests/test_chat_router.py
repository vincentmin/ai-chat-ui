from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from sqlmodel import select

from chatbot.chat_router import (
    _build_model_options,
    _first_user_message_text,
    _normalize_tool_part_states,
    _string_instructions_or_none,
)
from chatbot.db import JsonValue, to_json_value
from chatbot.db.models import AgentRunSnapshot
from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import save_run_snapshot


def _serialized_messages(text: str) -> JsonValue:
    messages = [ModelRequest(parts=[UserPromptPart(content=text)])]
    return to_json_value(json.loads(ModelMessagesTypeAdapter.dump_json(messages)))


def test_first_user_message_text_returns_first_non_empty_prompt() -> None:
    messages = [
        ModelRequest(parts=[UserPromptPart(content='   ')]),
        ModelRequest(parts=[UserPromptPart(content='Hello world')]),
        ModelRequest(parts=[UserPromptPart(content='Another prompt')]),
    ]

    assert _first_user_message_text(messages) == 'Hello world'


def test_first_user_message_text_joins_string_list_content() -> None:
    message = ModelRequest(parts=[UserPromptPart(content=['line 1', 'line 2'])])

    assert _first_user_message_text([message]) == 'line 1\nline 2'


def test_string_instructions_or_none_handles_non_string_entries() -> None:
    agent = Agent(model=TestModel(), instructions='valid')
    assert _string_instructions_or_none(agent) == ['valid']

    agent._instructions = ['valid', 123]  # type: ignore[assignment]
    assert _string_instructions_or_none(agent) is None


def test_build_model_options_deduplicates_models() -> None:
    model = TestModel()
    agent = Agent(model=model, instructions='Test')

    model_id_to_ref, model_infos = _build_model_options(
        agent,
        {
            'Default': model,
            'Duplicate': model,
        },
    )

    assert len(model_infos) == 1
    assert len(model_id_to_ref) == 1


def test_configure_endpoint_returns_models_and_prompt_capability(client) -> None:
    response = client.get('/api/configure')

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get('models'), list)
    assert len(payload['models']) >= 1
    assert payload['canOverrideSystemPrompt'] is True
    assert payload['defaultSystemPrompt'] == 'Test agent'


def test_get_chat_returns_empty_messages_for_missing_snapshot(client) -> None:
    response = client.get('/api/chat/conversation-missing')

    assert response.status_code == 200
    assert response.json() == {'messages': []}


def test_get_chat_returns_messages_for_latest_snapshot(
    client,
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id='conversation-1',
            run_id='run-1',
            agent_key='sql',
            model_messages_json=_serialized_messages('Hello from snapshot'),
        )

    response = client.get('/api/chat/conversation-1')

    assert response.status_code == 200
    payload = response.json()
    assert len(payload['messages']) == 1
    assert payload['messages'][0]['role'] == 'user'
    assert payload['messages'][0]['parts'][0]['text'] == 'Hello from snapshot'


def test_list_chats_returns_timestamp_sorted_summaries(
    client,
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id='conversation-older',
            run_id='run-1',
            agent_key='sql',
            model_messages_json=_serialized_messages('older message'),
        )
        save_run_snapshot(
            session,
            conversation_id='conversation-newer',
            run_id='run-2',
            agent_key='sql',
            model_messages_json=_serialized_messages('newer message'),
        )

        snapshots = session.exec(select(AgentRunSnapshot)).all()
        by_conversation = {snapshot.conversation_id: snapshot for snapshot in snapshots}
        base = datetime.now(UTC)
        by_conversation['conversation-older'].created_at = base
        by_conversation['conversation-newer'].created_at = base + timedelta(seconds=1)
        for snapshot in by_conversation.values():
            session.add(snapshot)
        session.commit()

    response = client.get('/api/chats')

    assert response.status_code == 200
    payload = response.json()
    assert [entry['id'] for entry in payload['conversations']] == [
        'conversation-newer',
        'conversation-older',
    ]
    assert payload['conversations'][0]['firstMessage'] == 'newer message'


def test_delete_chat_endpoint_removes_conversation_snapshots(
    client,
    db_runtime: DatabaseRuntime,
) -> None:
    with db_runtime.session() as session:
        save_run_snapshot(
            session,
            conversation_id='conversation-delete',
            run_id='run-1',
            agent_key='sql',
            model_messages_json=_serialized_messages('to delete'),
        )
        save_run_snapshot(
            session,
            conversation_id='conversation-keep',
            run_id='run-2',
            agent_key='sql',
            model_messages_json=_serialized_messages('to keep'),
        )

    response = client.delete('/api/chat/conversation-delete')

    assert response.status_code == 200
    assert response.json() == {'ok': True}

    with db_runtime.session() as session:
        remaining = session.exec(select(AgentRunSnapshot)).all()

    assert len(remaining) == 1
    assert remaining[0].conversation_id == 'conversation-keep'


def test_normalize_tool_part_states_handles_approval_states() -> None:
    payload = {
        'messages': [
            {
                'id': 'assistant-1',
                'role': 'assistant',
                'parts': [
                    {
                        'type': 'tool-query',
                        'toolCallId': 'call-1',
                        'state': 'approval-responded',
                        'input': {'sql_query': 'select 1'},
                        'approval': {'id': 'approval-1', 'approved': True},
                    },
                    {
                        'type': 'dynamic-tool',
                        'toolName': 'custom',
                        'toolCallId': 'call-2',
                        'state': 'output-denied',
                        'input': {'foo': 'bar'},
                        'approval': {'id': 'approval-2', 'approved': False},
                    },
                ],
            }
        ]
    }

    normalized = _normalize_tool_part_states(json.dumps(payload).encode('utf-8'))
    normalized_payload = json.loads(normalized)
    parts = normalized_payload['messages'][0]['parts']

    assert parts[0]['state'] == 'input-available'
    assert parts[1]['state'] == 'input-available'


def test_normalize_tool_part_states_leaves_other_states_unchanged() -> None:
    payload = {
        'messages': [
            {
                'id': 'assistant-1',
                'role': 'assistant',
                'parts': [
                    {
                        'type': 'tool-query',
                        'toolCallId': 'call-1',
                        'state': 'input-available',
                        'input': {'sql_query': 'select 1'},
                    }
                ],
            }
        ]
    }

    body = json.dumps(payload).encode('utf-8')
    normalized = _normalize_tool_part_states(body)
    assert normalized == body
