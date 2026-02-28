from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import duckdb
import pydantic_ai
from pydantic_ai.ui.vercel_ai.response_types import DataChunk

CHINOOK_DB_PATH = Path(__file__).with_name('chinook.db')


def _connect() -> duckdb.DuckDBPyConnection:
    if not CHINOOK_DB_PATH.exists():
        raise pydantic_ai.ModelRetry(
            f'Chinook database not found at {CHINOOK_DB_PATH}. '
            'Add a chinook.db file next to sql_agent.py.'
        )
    return duckdb.connect(str(CHINOOK_DB_PATH))


agent = pydantic_ai.Agent(
    model='openai-responses:gpt-4.1-nano',
    output_type=[str, pydantic_ai.DeferredToolRequests],
    instructions=(
        'You are an expert SQL assistant using the Chinook sample database. '
        'Use the query tool for analysis and the display tool when the user asks '
        'to show tabular results in the UI.'
    ),
)


@agent.tool_plain(requires_approval=True)
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


@agent.tool_plain(requires_approval=True)
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


if __name__ == '__main__':
    agent.to_cli_sync()
