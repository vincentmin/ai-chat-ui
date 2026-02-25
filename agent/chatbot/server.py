from __future__ import annotations as _annotations

from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI

from .arxiv_agent import agent as arxiv_agent
from .chat_router import create_chat_router
from .db.runtime import DatabaseRuntime
from .settings import RedisRuntime, get_settings
from .sql_agent import agent as sql_agent

# 'if-token-present' means nothing will be sent (and the example will work) if you don't
# have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

settings = get_settings()
models = settings.available_models()
if not models:
    raise ValueError(
        'No models configured. Please set OPENAI_API_KEY, ANTHROPIC_API_KEY, or '
        'GOOGLE_API_KEY environment variable.'
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_runtime = RedisRuntime(settings)
    db_runtime = DatabaseRuntime(settings.resolved_database_url)
    redis_runtime.startup()
    db_runtime.startup()
    app.state.settings = settings
    app.state.redis_runtime = redis_runtime
    app.state.db_runtime = db_runtime
    try:
        yield
    finally:
        db_runtime.shutdown()
        redis_runtime.shutdown()


app = FastAPI(title='AI Chat API', lifespan=lifespan)
app.include_router(
    create_chat_router(
        agent=sql_agent,
        models=models,
        agent_key='sql',
    ),
    prefix='/api/v1/sql',
)
app.include_router(
    create_chat_router(
        agent=arxiv_agent,
        models=models,
        agent_key='arxiv',
    ),
    prefix='/api/v1/arxiv',
)
logfire.instrument_fastapi(app)
