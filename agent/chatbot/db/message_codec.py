from __future__ import annotations

import logging
from typing import Any

from pydantic import TypeAdapter
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ToolReturnPart,
)
from pydantic_ai.ui.vercel_ai.response_types import (
    DataChunk,
    FileChunk,
    SourceDocumentChunk,
    SourceUrlChunk,
)

from .json_types import JsonValue

logger = logging.getLogger(__name__)

MetadataChunk = DataChunk | SourceUrlChunk | SourceDocumentChunk | FileChunk
_metadata_chunk_adapter = TypeAdapter(MetadataChunk)


def messages_from_json(messages_json: JsonValue) -> list[ModelMessage]:
    if not isinstance(messages_json, list):
        return []

    try:
        messages = ModelMessagesTypeAdapter.validate_python(messages_json)
        return rehydrate_tool_return_metadata(messages)
    except Exception:
        logger.exception('Failed to deserialize model messages')
        return []


def rehydrate_metadata_item(value: Any) -> Any:
    if isinstance(value, (DataChunk, SourceUrlChunk, SourceDocumentChunk, FileChunk)):
        return value

    if not isinstance(value, dict):
        return value

    chunk_type = value.get('type')
    if not isinstance(chunk_type, str):
        return value

    try:
        return _metadata_chunk_adapter.validate_python(value)
    except Exception:
        return value


def rehydrate_tool_return_metadata(messages: list[ModelMessage]) -> list[ModelMessage]:
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue

        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue

            metadata = part.metadata
            if isinstance(metadata, list):
                part.metadata = [rehydrate_metadata_item(item) for item in metadata]
            else:
                part.metadata = rehydrate_metadata_item(metadata)

    return messages
