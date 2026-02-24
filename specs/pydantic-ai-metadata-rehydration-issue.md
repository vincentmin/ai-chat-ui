# Bug: `dump_messages()` loses tool metadata chunks after message JSON roundtrip

## Summary

When `ModelMessage[]` is serialized to JSON and later restored with `ModelMessagesTypeAdapter`, `ToolReturnPart.metadata` is deserialized as plain `dict`/`list` values.

`VercelAIAdapter.dump_messages()` then fails to emit metadata-derived UI parts (for example `source-url`, `data-*`) because `_utils.iter_metadata_chunks()` only yields typed chunk instances (`DataChunk`, `SourceUrlChunk`, `SourceDocumentChunk`, `FileChunk`) via `isinstance(...)` checks.

This causes a mismatch between:

- live streaming responses (correctly include metadata parts), and
- replayed history from persisted `ModelMessage[]` (metadata parts missing).

## Environment

- `pydantic-ai` 1.14.x (observed in local venv)
- Python 3.13

## Minimal Reproduction

```python
from pydantic_ai.messages import (
    ModelRequest,
    ModelMessagesTypeAdapter,
    ToolReturnPart,
)
from pydantic_ai.ui.vercel_ai._utils import iter_metadata_chunks
from pydantic_ai.ui.vercel_ai.response_types import SourceUrlChunk

# 1) Build a model message containing typed metadata chunks
messages = [
    ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name='fetch',
                tool_call_id='call_1',
                content='ok',
                metadata=[
                    SourceUrlChunk(
                        source_id='paper-1',
                        url='https://example.com/paper-1',
                        title='Paper 1',
                    )
                ],
            )
        ]
    )
]

# 2) JSON roundtrip through ModelMessagesTypeAdapter
payload = ModelMessagesTypeAdapter.dump_python(messages, mode='json')
restored = ModelMessagesTypeAdapter.validate_python(payload)

part = restored[0].parts[0]
print(type(part.metadata[0]).__name__)  # -> dict

# 3) Metadata chunk extraction used by VercelAIAdapter.dump_messages
chunks = list(iter_metadata_chunks(part))
print(chunks)  # -> []
```

## Expected

After roundtrip, metadata chunk entries should still be usable by `iter_metadata_chunks` so `dump_messages()` can emit equivalent UI parts (`source-url`, `data-*`, etc.).

## Actual

Metadata entries become plain dicts, `iter_metadata_chunks` returns no chunks, and `dump_messages()` omits metadata-derived UI parts.

## Why this matters

This creates a protocol inconsistency:

- streaming path includes source/data metadata chunks,
- persisted/replayed path does not,
  which breaks UI parity between live responses and restored chat history.

## Suggested Fix

One of:

1. In `pydantic_ai.ui.vercel_ai._utils.iter_metadata_chunks`, accept dict-like values and validate/coerce into chunk models (`DataChunk | SourceUrlChunk | SourceDocumentChunk | FileChunk`) before `isinstance` filtering.
2. Narrow/validate `ToolReturnPart.metadata` at deserialize time to preserve typed chunk objects when possible.

Option 1 is likely the least invasive and preserves backward compatibility for arbitrary metadata.

## Workaround in app code

A local workaround is to rehydrate `ToolReturnPart.metadata` dicts into typed chunk objects after `ModelMessagesTypeAdapter.validate_python(...)` and before `VercelAIAdapter.dump_messages(...)`.
