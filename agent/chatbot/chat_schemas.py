from __future__ import annotations

from pydantic import BaseModel
from pydantic.alias_generators import to_camel
from pydantic_ai.ui.vercel_ai.request_types import UIMessage


class ModelInfo(BaseModel, alias_generator=to_camel, populate_by_name=True):
    id: str
    name: str


class ConfigureFrontend(BaseModel, alias_generator=to_camel, populate_by_name=True):
    models: list[ModelInfo]
    can_override_system_prompt: bool
    default_system_prompt: str | None


class HealthResponse(BaseModel, alias_generator=to_camel, populate_by_name=True):
    ok: bool


class ChatRequestExtra(
    BaseModel,
    extra='ignore',
    alias_generator=to_camel,
    populate_by_name=True,
):
    model: str | None = None
    system_prompt: str | None = None
    agent_key: str | None = None


class ConversationSummary(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    id: str
    first_message: str | None = None
    timestamp: int


class ConversationsResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    conversations: list[ConversationSummary]


class DeleteChatResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    ok: bool


class ChatMessagesResponse(
    BaseModel,
    alias_generator=to_camel,
    populate_by_name=True,
):
    messages: list[UIMessage]
