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


def _fake_agent() -> SimpleNamespace:
    return SimpleNamespace()


def _patch_active_run_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_prepare(_client, run_id: str, conversation_id: str, agent_key: str):
        return SimpleNamespace(
            run_id=run_id,
            conversation_id=conversation_id,
            agent_key=agent_key,
        )

    async def fake_heartbeat(_client, _lease) -> None:
        return None

    async def fake_release(
        _client, _agent_key: str, _conversation_id: str, _run_id: str
    ):
        return True

    monkeypatch.setattr(run_agent_task_module, '_prepare_active_run', fake_prepare)
    monkeypatch.setattr(run_agent_task_module, '_heartbeat_active_run', fake_heartbeat)
    monkeypatch.setattr(run_agent_task_module, 'release_active_run', fake_release)


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
async def test_run_agent_request_task_success_persists_snapshot_and_completes(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_run_execution(monkeypatch)

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
    monkeypatch.setattr(
        run_agent_task_module, 'get_agent', lambda _agent_key: _fake_agent()
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_team_agents',
        lambda: ['sql', 'arxiv'],
    )
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
            deps=None,
            message_history=None,
            toolsets=None,
        ):
            captured_run_stream_args['model'] = model
            captured_run_stream_args['instructions'] = instructions
            captured_run_stream_args['output_type'] = output_type
            captured_run_stream_args['deferred_tool_results'] = deferred_tool_results
            captured_run_stream_args['message_history'] = message_history
            captured_run_stream_args['toolsets'] = toolsets
            captured_run_stream_args['adapter_messages'] = list(self.messages)
            await on_complete(FakeResult())
            yield 'chunk-1'
            yield 'chunk-2'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    async def fake_drain_mailbox(_client, _agent_key, _conv_id):
        return []

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain_mailbox)

    async def fake_mailbox_is_empty(_client, _agent_key, _conv_id):
        return True

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty
    )

    await run_agent_task_module.run_agent_request_task.original_func(
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
    assert captured_run_stream_args['model'] == 'resolved:openai-responses:gpt-5'
    assert captured_run_stream_args['output_type'] == [str, DeferredToolRequests]
    assert captured_run_stream_args['deferred_tool_results'] is None
    assert captured_run_stream_args['message_history'] == []
    assert captured_run_stream_args['adapter_messages'] == []
    assert captured_run_stream_args['instructions'] is not None
    assert 'be concise' in captured_run_stream_args['instructions']
    assert captured_run_stream_args['toolsets'] is not None
    assert len(captured_run_stream_args['toolsets']) == 1
    assert [call[2] for call in publish_calls] == ['encoded:chunk-1', 'encoded:chunk-2']
    assert len(terminal_calls) == 1
    assert fake_redis_client.closed is True


@pytest.mark.anyio
async def test_run_agent_request_task_failure_marks_run_failed_and_publishes_error(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_run_execution(monkeypatch)

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
    monkeypatch.setattr(
        run_agent_task_module, 'get_agent', lambda _agent_key: _fake_agent()
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_team_agents',
        lambda: ['sql', 'arxiv'],
    )
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
            deps=None,
            message_history=None,
            toolsets=None,
        ):
            del model
            del instructions
            del on_complete
            del output_type
            del deferred_tool_results
            del deps
            del message_history
            del toolsets
            raise RuntimeError('boom')
            yield 'unreachable'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FailingAdapter)

    async def fake_drain_mailbox(_client, _agent_key, _conv_id):
        return []

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain_mailbox)

    async def fake_mailbox_is_empty_fail(_client, _agent_key, _conv_id):
        return True

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty_fail
    )

    await run_agent_task_module.run_agent_request_task.original_func(
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


@pytest.mark.anyio
async def test_run_agent_mailbox_task_skips_run_when_mailbox_is_empty(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_run_execution(monkeypatch)

    with db_runtime.session() as session:
        create_chat_run(session, 'run-3', 'conversation-3', 'sql')

    fake_redis_client = _FakeRedisClient()

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
    monkeypatch.setattr(
        run_agent_task_module, 'get_agent', lambda _agent_key: _fake_agent()
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_team_agents',
        lambda: ['sql', 'arxiv'],
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'resolve_model_ref',
        lambda _agent_key, selected_model: selected_model,
    )

    async def fake_publish_chunk(*_args: object) -> None:
        pass

    async def fake_publish_terminal(*_args: object) -> None:
        pass

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    monkeypatch.setattr(
        run_agent_task_module,
        '_load_snapshot_messages',
        lambda *_args: [
            ModelRequest(parts=[]),
            ModelResponse(parts=[]),
        ],
    )

    async def fake_drain_mailbox(*_args: object):
        return []

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain_mailbox)

    async def fake_mailbox_is_empty(_client, _agent_key, _conv_id):
        return True

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty
    )

    class FakeResult:
        run_id = 'result-run-3'

        def all_messages(self):
            return []

    class FakeEventStream:
        @staticmethod
        def encode_event(chunk: str) -> str:
            return chunk

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(
            self,
            *,
            agent: object,
            run_input: object,
            accept: str,
            sdk_version: int,
        ) -> None:
            del agent
            del run_input
            del accept
            del sdk_version
            self.messages = ['should-be-cleared']
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> FakeEventStream:
            return FakeEventStream()

        async def run_stream(
            self,
            *,
            output_type=None,
            deferred_tool_results=None,
            model=None,
            instructions=None,
            on_complete: Any = None,
            deps=None,
            message_history=None,
            toolsets=None,
        ):
            del output_type
            del deferred_tool_results
            del model
            del instructions
            del on_complete
            del deps
            del message_history
            del toolsets
            raise AssertionError(
                'run_stream should not be called for an empty mailbox run'
            )
            yield 'unreachable'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    await run_agent_task_module.run_agent_mailbox_task.original_func(
        run_id='run-3',
        conversation_id='conversation-3',
        agent_key='sql',
        selected_model=None,
        system_prompt=None,
    )

    with db_runtime.session() as session:
        run = session.exec(select(ChatRun).where(ChatRun.run_id == 'run-3')).one()

    assert run.status == ChatRunStatus.COMPLETED.value


@pytest.mark.anyio
async def test_run_agent_mailbox_task_uses_snapshot_and_mailbox_history(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_active_run_execution(monkeypatch)

    with db_runtime.session() as session:
        create_chat_run(session, 'run-4', 'conversation-4', 'sql')

    fake_redis_client = _FakeRedisClient()
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
    monkeypatch.setattr(
        run_agent_task_module, 'get_agent', lambda _agent_key: _fake_agent()
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_team_agents',
        lambda: ['sql', 'arxiv'],
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'resolve_model_ref',
        lambda _agent_key, selected_model: selected_model,
    )

    async def fake_publish_chunk(*_args: object) -> None:
        pass

    async def fake_publish_terminal(*_args: object) -> None:
        pass

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    monkeypatch.setattr(
        run_agent_task_module,
        '_load_snapshot_messages',
        lambda *_args: [
            ModelRequest(parts=[]),
            ModelResponse(parts=[]),
        ],
    )

    async def fake_drain_mailbox(*_args: object):
        return [SimpleNamespace(sender='arxiv', content='hello', timestamp=1.0)]

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain_mailbox)

    async def fake_mailbox_is_empty(_client, _agent_key, _conv_id):
        return True

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty
    )

    class FakeResult:
        run_id = 'result-run-4'

        def all_messages(self):
            return []

    class FakeEventStream:
        @staticmethod
        def encode_event(chunk: str) -> str:
            return chunk

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(
            self,
            *,
            agent: object,
            run_input: object,
            accept: str,
            sdk_version: int,
        ) -> None:
            del agent
            del run_input
            del accept
            del sdk_version
            self.messages = ['should-be-cleared']
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> FakeEventStream:
            return FakeEventStream()

        async def run_stream(
            self,
            *,
            output_type=None,
            deferred_tool_results=None,
            model=None,
            instructions=None,
            on_complete: Any = None,
            deps=None,
            message_history=None,
            toolsets=None,
        ):
            del output_type
            del deferred_tool_results
            del model
            del instructions
            del deps
            del toolsets
            captured_run_stream_args['message_history'] = message_history
            captured_run_stream_args['adapter_messages'] = list(self.messages)
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    await run_agent_task_module.run_agent_mailbox_task.original_func(
        run_id='run-4',
        conversation_id='conversation-4',
        agent_key='sql',
        selected_model=None,
        system_prompt=None,
    )

    message_history = captured_run_stream_args['message_history']
    assert len(message_history) == 3
    assert isinstance(message_history[0], ModelRequest)
    assert isinstance(message_history[1], ModelResponse)
    assert isinstance(message_history[2], ModelRequest)
    assert captured_run_stream_args['adapter_messages'] == []
