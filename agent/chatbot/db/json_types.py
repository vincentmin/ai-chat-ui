from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

type JsonValue = (
    dict[str, 'JsonValue'] | list['JsonValue'] | str | int | float | bool | None
)

JSON_SQL_TYPE = JSON().with_variant(JSONB, 'postgresql')

_any_adapter = TypeAdapter(Any)


def to_json_value(value: Any) -> JsonValue:
    """Convert any Python object to a JSON-compatible value."""
    return cast(JsonValue, _any_adapter.dump_python(value, mode='json'))


def to_json_snapshot(value: Any) -> JsonValue:
    """Serialize from __dict__ when available to preserve `_state` and peers."""
    if hasattr(value, '__dict__'):
        return to_json_value(vars(value))
    return to_json_value(value)
