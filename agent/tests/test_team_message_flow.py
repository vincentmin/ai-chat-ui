"""Tests for inter-agent message delivery in team mode.

Covers:
  - Post-run mailbox check must be non-destructive (Bug 1a)
  - User-initiated runs must use backend snapshot history (Bug 1b)
"""

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
from chatbot.mailbox import MailboxMessage

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
    return SimpleNamespace(history_processors=[])


class _FakeEventStream:
    @staticmethod
    def encode_event(chunk: str) -> str:
        return f'encoded:{chunk}'


# ---------------------------------------------------------------------------
# Bug 1a: post-run mailbox check must NOT drain messages
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_post_run_mailbox_check_does_not_consume_messages(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a run completes, the post-run check should peek at the mailbox
    (non-destructive) rather than drain it, so that the subsequent wake-up
    run can actually read the messages."""

    with db_runtime.session() as session:
        create_chat_run(session, 'run-drain', 'conv-drain', 'sql')

    fake_redis_client = _FakeRedisClient()
    drain_calls: list[tuple[str, str]] = []
    wakeup_calls: list[tuple[str, str]] = []

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

    # Track drain_mailbox calls — the post-run check should NOT call it
    async def tracking_drain_mailbox(
        _client: object, agent_key: str, conv_id: str
    ) -> list[MailboxMessage]:
        drain_calls.append((agent_key, conv_id))
        return [MailboxMessage(sender='arxiv', content='foo', timestamp=1.0)]

    monkeypatch.setattr(run_agent_task_module, 'drain_mailbox', tracking_drain_mailbox)

    # Provide mailbox_is_empty — returns False (has messages)
    async def fake_mailbox_is_empty(
        _client: object, _agent_key: str, _conv_id: str
    ) -> bool:
        return False

    monkeypatch.setattr(
        run_agent_task_module, 'mailbox_is_empty', fake_mailbox_is_empty
    )

    # Track _enqueue_self_wakeup calls
    async def tracking_enqueue(agent_key: str, conversation_id: str) -> None:
        wakeup_calls.append((agent_key, conversation_id))

    monkeypatch.setattr(run_agent_task_module, '_enqueue_self_wakeup', tracking_enqueue)

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
        ):
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    await run_agent_task_module.run_agent_task.original_func(
        run_id='run-drain',
        conversation_id='conv-drain',
        agent_key='sql',
        request_body='{"messages":[]}',
        selected_model=None,
        system_prompt=None,
    )

    # The post-run check MUST NOT call drain_mailbox (it should only peek)
    assert drain_calls == [], (
        f'drain_mailbox was called {len(drain_calls)} time(s) — '
        'the post-run check should use mailbox_is_empty instead'
    )

    # The wake-up should still be enqueued because the mailbox has messages
    assert ('sql', 'conv-drain') in wakeup_calls


# ---------------------------------------------------------------------------
# Bug 1b: user-initiated run must use backend snapshot for history
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_user_initiated_run_uses_snapshot_history_for_team_agents(
    db_runtime: DatabaseRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a user sends a new message but the frontend's history is stale
    (missing wake-up run messages), the backend should use the latest
    snapshot as canonical history so the agent sees all prior messages."""

    # Persist a snapshot that includes a wake-up run exchange
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
        ):
            captured_message_history['value'] = message_history
            await on_complete(FakeResult())
            yield 'chunk'

    monkeypatch.setattr(run_agent_task_module, 'VercelAIAdapter', FakeAdapter)

    # Create a new run for the user-initiated request
    with db_runtime.session() as session:
        create_chat_run(session, 'run-snap-2', 'conv-snap', 'sql')

    await run_agent_task_module.run_agent_task.original_func(
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
