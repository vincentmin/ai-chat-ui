"""Tests for inter-agent message delivery in team mode."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from chatbot.db import to_json_value
from chatbot.db.runtime import DatabaseRuntime
from chatbot.db.service import create_chat_run, save_run_snapshot

run_agent_task_module = importlib.import_module('chatbot.tasks.run_agent_task')


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


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


class _FakeEventStream:
    @staticmethod
    def encode_event(chunk: str) -> str:
        return f'encoded:{chunk}'


@pytest.mark.anyio
async def test_mailbox_task_processes_follow_up_messages_in_same_run(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mailbox runs should loop and consume follow-up messages without re-enqueueing."""

    _patch_active_run_execution(monkeypatch)

    with db_runtime.session() as session:
        create_chat_run(session, 'run-drain', 'conv-drain', 'sql')

    fake_redis_client = _FakeRedisClient()
    captured_histories: list[list[ModelRequest | ModelResponse]] = []

    monkeypatch.setattr(
        run_agent_task_module, '_get_worker_db_runtime', lambda: db_runtime
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_settings',
        lambda: SimpleNamespace(redis_url='redis://test'),
    )
    monkeypatch.setattr(
        run_agent_task_module.redis, 'from_url', lambda *a, **kw: fake_redis_client
    )
    monkeypatch.setattr(run_agent_task_module, 'get_agent', lambda _k: _fake_agent())
    monkeypatch.setattr(
        run_agent_task_module, 'get_team_agents', lambda: ['sql', 'arxiv']
    )
    monkeypatch.setattr(run_agent_task_module, 'resolve_model_ref', lambda _k, m: m)

    async def fake_publish_chunk(*_a: object) -> None:
        pass

    async def fake_publish_terminal(*_a: object) -> None:
        pass

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    drain_batches = [
        [SimpleNamespace(sender='arxiv', content='foo', timestamp=1.0)],
        [SimpleNamespace(sender='arxiv', content='bar', timestamp=2.0)],
        [],
    ]

    async def tracking_drain_mailbox(_client: object, _agent_key: str, _conv_id: str):
        return drain_batches.pop(0)

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', tracking_drain_mailbox)

    mailbox_empty_results = [False, True]

    async def fake_mailbox_is_empty(
        _client: object, _agent_key: str, _conv_id: str
    ) -> bool:
        return mailbox_empty_results.pop(0)

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty
    )

    class FakeResult:
        run_id = 'result-drain'

        def all_messages(self):
            return [
                {
                    'kind': 'request',
                    'parts': [{'part_kind': 'user-prompt', 'content': 'hi'}],
                }
            ]

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        @staticmethod
        def build_run_input(raw: bytes) -> dict[str, bytes]:
            return {'raw_body': raw}

        def __init__(
            self, *, agent: object, run_input: object, accept: str, sdk_version: int
        ) -> None:
            self.messages: list[object] = []
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> _FakeEventStream:
            return _FakeEventStream()

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
            captured_histories.append(list(message_history or []))
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    await run_agent_task_module.run_agent_mailbox_task.original_func(
        run_id='run-drain',
        conversation_id='conv-drain',
        agent_key='sql',
        selected_model=None,
        system_prompt=None,
    )

    assert len(captured_histories) == 2
    first_cycle_text = [
        part.content
        for part in captured_histories[0]
        if isinstance(part, ModelRequest)
        for part in part.parts
        if isinstance(part, UserPromptPart)
    ]
    second_cycle_text = [
        part.content
        for part in captured_histories[1]
        if isinstance(part, ModelRequest)
        for part in part.parts
        if isinstance(part, UserPromptPart)
    ]
    assert first_cycle_text == ['[Message from arxiv]: foo']
    assert second_cycle_text[-1] == '[Message from arxiv]: bar'


@pytest.mark.anyio
async def test_user_initiated_run_uses_snapshot_history_for_team_agents(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a user sends a new message but the frontend's history is stale
    (missing wake-up run messages), the backend should use the latest
    snapshot as canonical history so the agent sees all prior messages."""

    _patch_active_run_execution(monkeypatch)

    wakeup_messages = [
        ModelRequest(parts=[UserPromptPart(content='Tell arxiv hi')]),
        ModelResponse(parts=[TextPart(content='Done — told arxiv.')]),
        # These are from the wake-up run (frontend doesn't know about them):
        ModelRequest(parts=[UserPromptPart(content='[Message from arxiv]: foo')]),
        ModelResponse(parts=[TextPart(content='Got it, foo received.')]),
    ]

    with db_runtime.session() as session:
        create_chat_run(session, 'run-snap', 'conv-snap', 'sql')
        save_run_snapshot(
            session,
            conversation_id='conv-snap',
            run_id='run-snap',
            agent_key='sql',
            model_messages_json=to_json_value(wakeup_messages),
        )

    fake_redis_client = _FakeRedisClient()
    captured_message_history: dict[str, Any] = {}
    captured_adapter_messages: dict[str, Any] = {}

    monkeypatch.setattr(
        run_agent_task_module, '_get_worker_db_runtime', lambda: db_runtime
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_settings',
        lambda: SimpleNamespace(redis_url='redis://test'),
    )
    monkeypatch.setattr(
        run_agent_task_module.redis, 'from_url', lambda *a, **kw: fake_redis_client
    )
    monkeypatch.setattr(run_agent_task_module, 'get_agent', lambda _k: _fake_agent())
    monkeypatch.setattr(
        run_agent_task_module, 'get_team_agents', lambda: ['sql', 'arxiv']
    )
    monkeypatch.setattr(run_agent_task_module, 'resolve_model_ref', lambda _k, m: m)

    async def fake_publish_chunk(*_a: object) -> None:
        pass

    async def fake_publish_terminal(*_a: object) -> None:
        pass

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    async def fake_drain(*_a: object) -> list[object]:
        return []

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain)

    class FakeResult:
        run_id = 'result-snap'

        def all_messages(self):
            return [
                {
                    'kind': 'request',
                    'parts': [{'part_kind': 'user-prompt', 'content': 'hi'}],
                }
            ]

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        @staticmethod
        def build_run_input(raw: bytes) -> SimpleNamespace:
            """Simulate the Vercel AI adapter parsing request body."""
            return SimpleNamespace(
                id='conv-snap',
                messages=[
                    SimpleNamespace(
                        role='user',
                        parts=[SimpleNamespace(text='Tell arxiv hi')],
                    ),
                    SimpleNamespace(
                        role='assistant',
                        parts=[SimpleNamespace(text='Done — told arxiv.', type='text')],
                    ),
                    # The new user message:
                    SimpleNamespace(
                        role='user',
                        parts=[SimpleNamespace(text='Did you receive foo?')],
                    ),
                ],
                __pydantic_extra__={},
            )

        def __init__(
            self, *, agent: object, run_input: object, accept: str, sdk_version: int
        ) -> None:
            # Adapter messages from frontend (stale — missing wake-ups)
            self.messages = [
                ModelRequest(parts=[UserPromptPart(content='Tell arxiv hi')]),
                ModelResponse(parts=[TextPart(content='Done — told arxiv.')]),
                ModelRequest(parts=[UserPromptPart(content='Did you receive foo?')]),
            ]
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> _FakeEventStream:
            return _FakeEventStream()

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
            del toolsets
            captured_message_history['value'] = message_history
            captured_adapter_messages['value'] = list(self.messages)
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    # Create a new run for the user-initiated request
    with db_runtime.session() as session:
        create_chat_run(session, 'run-snap-2', 'conv-snap', 'sql')

    await run_agent_task_module.run_agent_request_task.original_func(
        run_id='run-snap-2',
        conversation_id='conv-snap',
        agent_key='sql',
        request_body=(
            '{"messages":[{"role":"user","parts"'
            ':[{"type":"text","text":"Did you receive foo?"}]}]}'
        ),
        selected_model=None,
        system_prompt=None,
    )

    # The message_history should include the snapshot's wake-up messages
    mh = captured_message_history.get('value')
    assert mh is not None, 'message_history should be provided (not None)'
    assert captured_adapter_messages.get('value') == []

    # Should contain the wake-up run exchange
    user_texts = [
        part.content
        for msg in mh
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, UserPromptPart)
    ]
    assert '[Message from arxiv]: foo' in user_texts, (
        f'Wake-up run mailbox message not found in message_history. '
        f'User texts seen: {user_texts}'
    )


@pytest.mark.anyio
async def test_user_initiated_run_does_not_duplicate_snapshot_messages(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When backend snapshot history is used, the effective agent input should
    not duplicate messages already present in the snapshot."""

    _patch_active_run_execution(monkeypatch)

    persisted_messages = [
        ModelRequest(parts=[UserPromptPart(content='Tell arxiv hi')]),
        ModelResponse(parts=[TextPart(content='Done - told arxiv.')]),
        ModelRequest(parts=[UserPromptPart(content='[Message from arxiv]: foo')]),
        ModelResponse(parts=[TextPart(content='Got it, foo received.')]),
    ]

    with db_runtime.session() as session:
        create_chat_run(session, 'run-no-dupe', 'conv-no-dupe', 'sql')
        save_run_snapshot(
            session,
            conversation_id='conv-no-dupe',
            run_id='run-no-dupe',
            agent_key='sql',
            model_messages_json=to_json_value(persisted_messages),
        )

    fake_redis_client = _FakeRedisClient()
    captured_effective_history: dict[str, list[ModelRequest | ModelResponse]] = {}

    monkeypatch.setattr(
        run_agent_task_module, '_get_worker_db_runtime', lambda: db_runtime
    )
    monkeypatch.setattr(
        run_agent_task_module,
        'get_settings',
        lambda: SimpleNamespace(redis_url='redis://test'),
    )
    monkeypatch.setattr(
        run_agent_task_module.redis, 'from_url', lambda *a, **kw: fake_redis_client
    )
    monkeypatch.setattr(run_agent_task_module, 'get_agent', lambda _k: _fake_agent())
    monkeypatch.setattr(
        run_agent_task_module, 'get_team_agents', lambda: ['sql', 'arxiv']
    )
    monkeypatch.setattr(run_agent_task_module, 'resolve_model_ref', lambda _k, m: m)

    async def fake_publish_chunk(*_a: object) -> None:
        pass

    async def fake_publish_terminal(*_a: object) -> None:
        pass

    monkeypatch.setattr(run_agent_task_module, 'publish_chunk', fake_publish_chunk)
    monkeypatch.setattr(
        run_agent_task_module, 'publish_terminal', fake_publish_terminal
    )

    async def fake_drain(*_a: object) -> list[object]:
        return []

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', fake_drain)

    class FakeResult:
        run_id = 'result-no-dupe'

        def all_messages(self):
            return [
                {
                    'kind': 'request',
                    'parts': [{'part_kind': 'user-prompt', 'content': 'hi'}],
                }
            ]

    class FakeAdapter:
        def __class_getitem__(cls, _item):
            return cls

        @staticmethod
        def build_run_input(raw: bytes) -> SimpleNamespace:
            del raw
            return SimpleNamespace(
                id='conv-no-dupe',
                messages=[
                    SimpleNamespace(
                        role='user',
                        parts=[SimpleNamespace(text='Tell arxiv hi')],
                    ),
                    SimpleNamespace(
                        role='assistant',
                        parts=[SimpleNamespace(text='Done - told arxiv.', type='text')],
                    ),
                    SimpleNamespace(
                        role='user',
                        parts=[SimpleNamespace(text='Did you receive foo?')],
                    ),
                ],
                __pydantic_extra__={},
            )

        def __init__(
            self, *, agent: object, run_input: object, accept: str, sdk_version: int
        ) -> None:
            del agent
            del run_input
            del accept
            del sdk_version
            self.messages = [
                ModelRequest(parts=[UserPromptPart(content='Tell arxiv hi')]),
                ModelResponse(parts=[TextPart(content='Done - told arxiv.')]),
                ModelRequest(parts=[UserPromptPart(content='Did you receive foo?')]),
            ]
            self.deferred_tool_results = None

        @staticmethod
        def build_event_stream() -> _FakeEventStream:
            return _FakeEventStream()

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
            captured_effective_history['value'] = list(message_history or [])
            assert self.messages == []
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    with db_runtime.session() as session:
        create_chat_run(session, 'run-no-dupe-2', 'conv-no-dupe', 'sql')

    await run_agent_task_module.run_agent_request_task.original_func(
        run_id='run-no-dupe-2',
        conversation_id='conv-no-dupe',
        agent_key='sql',
        request_body=(
            '{"messages":[{"role":"user","parts"'
            ':[{"type":"text","text":"Did you receive foo?"}]}]}'
        ),
        selected_model=None,
        system_prompt=None,
    )

    effective_history = captured_effective_history.get('value')
    assert effective_history is not None

    user_texts = [
        part.content
        for msg in effective_history
        if isinstance(msg, ModelRequest)
        for part in msg.parts
        if isinstance(part, UserPromptPart)
    ]
    assistant_texts = [
        part.content
        for msg in effective_history
        if isinstance(msg, ModelResponse)
        for part in msg.parts
        if isinstance(part, TextPart)
    ]

    assert user_texts == [
        'Tell arxiv hi',
        '[Message from arxiv]: foo',
        'Did you receive foo?',
    ]
    assert assistant_texts == [
        'Done - told arxiv.',
        'Got it, foo received.',
    ]
