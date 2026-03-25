from __future__ import annotations

from fastapi import APIRouter, Depends

from .chat_schemas import (
    ConversationsResponse,
    ConversationSummary,
    DeleteChatResponse,
    TeamAgentInfo,
    TeamConfigureResponse,
)
from .db.json_types import JsonValue
from .db.message_codec import messages_from_json
from .db.runtime import DatabaseRuntime
from .db.service import delete_team_chat_records, get_team_conversations
from .lifespan import get_db_runtime
from .tasks.agent_registry import AGENT_KEYS

# Hardcoded team agent definitions. Extend this when new agents are added.
TEAM_AGENTS: list[TeamAgentInfo] = [
    TeamAgentInfo(key='sql', title='SQL Agent', api_base_path='/api/v1/sql'),
    TeamAgentInfo(key='arxiv', title='Arxiv Agent', api_base_path='/api/v1/arxiv'),
]


def _first_user_text(model_messages_json: JsonValue) -> str | None:
    """Extract the first user message text from a serialised message list."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    messages = messages_from_json(model_messages_json)
    for message in messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                return part.content
    return None


router = APIRouter()


@router.get('/configure')
async def team_configure() -> TeamConfigureResponse:
    return TeamConfigureResponse(agents=TEAM_AGENTS)


@router.get('/chats')
async def team_chats(
    db_runtime: DatabaseRuntime = Depends(get_db_runtime),
) -> ConversationsResponse:
    with db_runtime.session() as session:
        conversations = get_team_conversations(session, AGENT_KEYS)

    summaries: list[ConversationSummary] = []
    for conversation_id, agent_snapshots in conversations.items():
        # Pick the earliest snapshot across agents for the timestamp,
        # and the first user message from any snapshot for the label.
        first_message: str | None = None
        earliest_ts: float | None = None
        for snapshot in agent_snapshots.values():
            ts = snapshot.created_at.timestamp()
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
            if first_message is None:
                first_message = _first_user_text(snapshot.model_messages_json)

        summaries.append(
            ConversationSummary(
                id=conversation_id,
                first_message=first_message,
                timestamp=int((earliest_ts or 0) * 1000),
            )
        )

    summaries.sort(key=lambda s: s.timestamp, reverse=True)
    return ConversationsResponse(conversations=summaries)


@router.delete('/chat/{conversation_id}')
async def team_delete_chat(
    conversation_id: str,
    db_runtime: DatabaseRuntime = Depends(get_db_runtime),
) -> DeleteChatResponse:
    with db_runtime.session() as session:
        delete_team_chat_records(session, conversation_id, AGENT_KEYS)
    return DeleteChatResponse(ok=True)
