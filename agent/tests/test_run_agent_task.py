from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from sqlmodel import select

from chatbot.db.models import AgentRunSnapshot, ChatRun, ChatRunStatus
from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import create_chat_run

run_agent_task_module = importlib.import_module('chatbot.tasks.run_agent_task')


class _FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_filter_deferred_tool_results_matches_last_model_response_calls() -> None:
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name='query',
                    tool_call_id='call-old',
                    args={'sql_query': 'select 1'},
                ),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name='query',
                    tool_call_id='call-old',
                    content='already completed',
                ),
            ]
        ),
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name='query',
                    tool_call_id='call-latest',
                    args={'sql_query': 'select 2'},
                )
            ]
        ),
    ]
    deferred_tool_results = DeferredToolResults(
        approvals={
            'call-old': True,
            'call-latest': True,
        }
    )

    filtered = run_agent_task_module._filter_deferred_tool_results(
        messages,
        deferred_tool_results,
    )

    assert filtered is not None
    assert filtered.approvals == {'call-latest': True}


def test_filter_deferred_tool_results_returns_none_when_no_expected_calls() -> None:
    filtered = run_agent_task_module._filter_deferred_tool_results(
        messages=[],
        deferred_tool_results=DeferredToolResults(approvals={'call-old': True}),
    )

    assert filtered is None


def test_filter_deferred_tool_results_excludes_already_resolved_calls() -> None:
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name='query',
                    tool_call_id='call-old',
                    args={'sql_query': 'select 1'},
                ),
                ToolCallPart(
                    tool_name='query',
                    tool_call_id='call-new',
                    args={'sql_query': 'select 2'},
                ),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name='query',
                    tool_call_id='call-old',
                    content='already completed',
                )
            ]
        ),
    ]

    deferred_tool_results = DeferredToolResults(
        approvals={
            'call-old': True,
            'call-new': True,
        }
    )

    filtered = run_agent_task_module._filter_deferred_tool_results(
        messages,
        deferred_tool_results,
    )

    assert filtered is not None
    assert filtered.approvals == {'call-new': True}


@pytest.mark.anyio
async def test_run_agent_task_success_persists_snapshot_and_completes(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-1', 'conversation-1', 'sql')

    fake_redis_client = _FakeRedisClient()
    publish_calls: list[tuple[str, str, str]] = []
    terminal_calls: list[tuple[str, str]] = []
    captured_run_stream_args: dict[str, Any] = {}

    monkeypatch.setattr(
        run_agent_task_module,
        '_get_worker_db_runtime',
        lambda: db_runtime,
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_settings',
        lambda: SimpleNamespace(redis_url='redis://test'),
    )
    monkeypatch.setattr(
        run_agent_task_module.redis,
        'from_url',
        lambda *_args, **_kwargs: fake_redis_client,
    )
    monkeypatch.setattr(run_agent_task_module, 'get_agent', lambda _agent_key: object())
    monkeypatch.setattr(
        run_agent_task_module,
        'resolve_model_ref',
        lambda _agent_key, selected_model: f'resolved:{selected_model}',
    )

    async def fake_publish_chunk(_client, stream_key: str, encoded_chunk: str) -> None:
        publish_calls.append((_client.__class__.__name__, stream_key, encoded_chunk))

    async def fake_publish_terminal(_client, stream_key: str) -> None:
        terminal_calls.append((_client.__class__.__name__, stream_key))

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    class FakeResult:
        run_id = 'result-run-1'

        def all_messages(self):
            return [
                {
                    'kind': 'request',
                    'parts': [{'part_kind': 'user-prompt', 'content': 'hello'}],
                }
            ]

    class FakeEventStream:
        @staticmethod
        def encode_event(chunk: str) -> str:
            return f'encoded:{chunk}'

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        @staticmethod
        def build_run_input(raw_body: bytes) -> dict[str, bytes]:
            return {'raw_body': raw_body}

        def __init__(
            self,
            *,
            agent: object,
            run_input: dict[str, bytes],
            accept: str,
            sdk_version: int,
        ) -> None:
            assert accept == 'text/event-stream'
            assert run_input['raw_body'] == b'{"messages":[]}'
            assert sdk_version == 6
            self.agent = agent
            self.messages = []
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> FakeEventStream:
            return FakeEventStream()

        async def run_stream(
            self,
            *,
            output_type=None,
            deferred_tool_results=None,
            model,
            instructions,
            on_complete,
        ):
            captured_run_stream_args['model'] = model
            captured_run_stream_args['instructions'] = instructions
            captured_run_stream_args['output_type'] = output_type
            captured_run_stream_args['deferred_tool_results'] = deferred_tool_results
            await on_complete(FakeResult())
            yield 'chunk-1'
            yield 'chunk-2'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    await run_agent_task_module.run_agent_task.original_func(
        run_id='run-1',
        conversation_id='conversation-1',
        agent_key='sql',
        request_body='{"messages":[]}',
        selected_model='openai-responses:gpt-5',
        system_prompt='be concise',
    )

    with db_runtime.session() as session:
        run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-1')).one()
        snapshots = session.exec(select(AgentRunSnapshot)).all()

    assert run.status == ChatRunStatus.COMPLETED.value
    assert run.error is None
    assert len(snapshots) == 1
    assert snapshots[0].run_id == 'result-run-1'
    assert snapshots[0].conversation_id == 'conversation-1'
    assert captured_run_stream_args == {
        'model': 'resolved:openai-responses:gpt-5',
        'instructions': 'be concise',
        'output_type': [str, DeferredToolRequests],
        'deferred_tool_results': None,
    }
    assert [call[2] for call in publish_calls] == ['encoded:chunk-1', 'encoded:chunk-2']
    assert len(terminal_calls) == 1
    assert fake_redis_client.closed is True


@pytest.mark.anyio
async def test_run_agent_task_failure_marks_run_failed_and_publishes_error(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db_runtime.session() as session:
        create_chat_run(session, 'run-2', 'conversation-2', 'sql')

    fake_redis_client = _FakeRedisClient()
    publish_calls: list[str] = []
    terminal_calls: list[str] = []

    monkeypatch.setattr(
        run_agent_task_module,
        '_get_worker_db_runtime',
        lambda: db_runtime,
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_settings',
        lambda: SimpleNamespace(redis_url='redis://test'),
    )
    monkeypatch.setattr(
        run_agent_task_module.redis,
        'from_url',
        lambda *_args, **_kwargs: fake_redis_client,
    )
    monkeypatch.setattr(run_agent_task_module, 'get_agent', lambda _agent_key: object())
    monkeypatch.setattr(
        run_agent_task_module,
        'resolve_model_ref',
        lambda _agent_key, selected_model: selected_model,
    )

    async def fake_publish_chunk(_client, _stream_key: str, encoded_chunk: str) -> None:
        publish_calls.append(encoded_chunk)

    async def fake_publish_terminal(_client, stream_key: str) -> None:
        terminal_calls.append(stream_key)

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    class FakeEventStream:
        @staticmethod
        def encode_event(chunk: str) -> str:
            return f'encoded:{chunk}'

    class FailingAdapter:
        def __class_getitem__(cls, _item):
            return cls

        @staticmethod
        def build_run_input(raw_body: bytes) -> dict[str, bytes]:
            return {'raw_body': raw_body}

        def __init__(
            self,
            *,
            agent: object,
            run_input: dict[str, bytes],
            accept: str,
            sdk_version: int,
        ) -> None:
            del agent
            del run_input
            del accept
            del sdk_version
            self.messages = []
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> FakeEventStream:
            return FakeEventStream()

        async def run_stream(
            self,
            *,
            output_type=None,
            deferred_tool_results=None,
            model,
            instructions,
            on_complete,
        ):
            del model
            del instructions
            del on_complete
            del output_type
            del deferred_tool_results
            raise RuntimeError('boom')
            yield 'unreachable'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FailingAdapter)

    await run_agent_task_module.run_agent_task.original_func(
        run_id='run-2',
        conversation_id='conversation-2',
        agent_key='sql',
        request_body='{"messages":[]}',
        selected_model='openai-responses:gpt-5',
        system_prompt=None,
    )

    with db_runtime.session() as session:
        run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-2')).one()
        snapshots = session.exec(select(AgentRunSnapshot)).all()

    assert run.status == ChatRunStatus.FAILED.value
    assert run.error == 'boom'
    assert snapshots == []
    assert len(publish_calls) == 2
    assert publish_calls[0].startswith('data: {"type":"error","errorText":"boom"}')
    assert publish_calls[1] == 'data: [DONE]\n\n'
    assert len(terminal_calls) == 1
    assert fake_redis_client.closed is True
