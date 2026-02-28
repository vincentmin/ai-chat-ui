from __future__ import annotations

from pydantic_ai.ui.vercel_ai.response_types import DataChunk

from chatbot.db import message_codec


def test_messages_from_json_returns_empty_for_non_list_input() -> None:
    assert message_codec.messages_from_json({'not': 'a-list'}) == []


def test_messages_from_json_returns_empty_on_deserialization_error(
    monkeypatch,
) -> None:
    def raise_error(_value):
        raise ValueError('boom')

    monkeypatch.setattr(
        message_codec.ModelMessagesTypeAdapter,
        'validate_python',
        raise_error,
    )

    assert message_codec.messages_from_json([{'broken': True}]) == []


def test_messages_from_json_rehydrates_when_deserialization_succeeds(
    monkeypatch,
) -> None:
    validated_messages = ['validated-message']
    rehydrated_messages = ['rehydrated-message']

    monkeypatch.setattr(
        message_codec.ModelMessagesTypeAdapter,
        'validate_python',
        lambda _value: validated_messages,
    )
    monkeypatch.setattr(
        message_codec,
        'rehydrate_tool_return_metadata',
        lambda messages: rehydrated_messages if messages is validated_messages else [],
    )

    assert message_codec.messages_from_json([{'ok': True}]) == rehydrated_messages


def test_rehydrate_metadata_item_converts_valid_chunk_dict() -> None:
    result = message_codec.rehydrate_metadata_item(
        {
            'type': 'data-sql-result',
            'data': {'columns': ['id'], 'rows': [[1]]},
        }
    )

    assert isinstance(result, DataChunk)
    assert result.type == 'data-sql-result'
    assert result.data['columns'] == ['id']


def test_rehydrate_metadata_item_returns_original_for_unknown_shape() -> None:
    raw = {'type': 123, 'data': {'hello': 'world'}}

    assert message_codec.rehydrate_metadata_item(raw) is raw
    assert message_codec.rehydrate_metadata_item('plain-text') == 'plain-text'
