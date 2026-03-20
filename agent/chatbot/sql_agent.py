from __future__ import annotations

import io
import json
from collections.abc import Sequence
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import duckdb
import pydantic_ai
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.ui.vercel_ai.response_types import DataChunk

from chatbot.agent_deps import AgentDeps

CHINOOK_DB_PATH = Path(__file__).with_name('chinook.db')

_INSTRUCTIONS = (
    'You are an expert SQL assistant using the Chinook sample database. '
    'Use the query tool for analysis and the display tool when the user asks '
    'to show tabular results in the UI.\n\n'
    '## Team collaboration\n'
    'You are part of a team of agents. Your teammates are:\n'
    '- arxiv: An expert research assistant with access to Arxiv papers.\n\n'
    'Messages from other agents appear as user messages prefixed with '
    '"[Message from <agent>]: ". When another agent asks you to do '
    'something or requests a reply, you MUST use the `tell` tool to '
    'send your response back — simply writing text in your reply does '
    'NOT deliver it to the other agent.\n\n'
    'The `tell` tool is asynchronous: it delivers your message and '
    'returns immediately. You do not need to wait for a reply. '
    'If the other agent responds later, you will be automatically '
    'woken up with their reply as a new "[Message from ...]" message. '
    'So after calling `tell`, finish your current turn normally — '
    'you can continue doing other work if there is any, or end with '
    'a brief status message to the user.'
    'The end user has visibility into all your messages, '
    'so you can inform them using your regular messages.'
)


def _connect() -> duckdb.DuckDBPyConnection:
    if not CHINOOK_DB_PATH.exists():
        raise pydantic_ai.ModelRetry(
            f'Chinook database not found at {CHINOOK_DB_PATH}. '
            'Add a chinook.db file next to sql_agent.py.'
        )
    return duckdb.connect(str(CHINOOK_DB_PATH))


def make_agent(
    history_processors: Sequence[Any] | None = None,
) -> pydantic_ai.Agent[AgentDeps, Any]:
    """Create a new sql agent instance, optionally with per-run history processors."""
    new_agent: pydantic_ai.Agent[AgentDeps, Any] = pydantic_ai.Agent(
        model=OpenAIResponsesModel(
            'gpt-5-mini',
            settings=OpenAIResponsesModelSettings(
                openai_store=True,  # This is necessary to see the reasoning traces
                openai_reasoning_summary='auto',
                openai_reasoning_effort='low',
            ),
        ),
        output_type=[str, pydantic_ai.DeferredToolRequests],
        instructions=_INSTRUCTIONS,
        deps_type=AgentDeps,
        history_processors=list(history_processors) if history_processors else [],
    )

    @new_agent.tool_plain(requires_approval=True)
    def query(sql_query: str) -> str:
        """Run a SQL query and return a truncated preview of the result."""
        try:
            with _connect() as conn:
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    # DuckDB handles preview truncation in show().
                    conn.sql(sql_query).show()
                return buffer.getvalue().strip() or '(no rows)'
        except Exception as e:
            raise pydantic_ai.ModelRetry(f'Failed to run SQL query: {e}') from e

    @new_agent.tool_plain(requires_approval=True)
    def display(sql_query: str) -> pydantic_ai.ToolReturn:
        """Run a SQL query and send full results to the frontend as data metadata."""
        try:
            with _connect() as conn:
                relation = conn.sql(sql_query)
                columns = list(relation.columns)
                rows = json.loads(relation.pl().write_json(file=None))
        except Exception as e:
            raise pydantic_ai.ModelRetry(f'Failed to run SQL query: {e}') from e

        return pydantic_ai.ToolReturn(
            return_value='Query result displayed to user',
            metadata=[
                DataChunk(
                    type='data-sql-result',
                    data={
                        'sql_query': sql_query,
                        'columns': columns,
                        'rows': rows,
                        'row_count': len(rows),
                        'column_count': len(columns),
                    },
                ),
            ],
        )

    return new_agent


# Module-level singleton used for CLI and model/tool introspection only.
# Do not use this instance for actual agent runs — use make_agent() instead.
agent = make_agent()


if __name__ == '__main__':
    agent.to_cli_sync()
