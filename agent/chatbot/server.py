from __future__ import annotations as _annotations

from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI

from .agent import agent
from .chat_router import create_chat_router
from .settings import RedisRuntime, get_settings

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
    redis_runtime.startup()
    app.state.settings = settings
    app.state.redis_runtime = redis_runtime
    try:
        yield
    finally:
        redis_runtime.shutdown()


app = FastAPI(title='AI Chat API', lifespan=lifespan)
app.include_router(
    create_chat_router(
        agent=agent,
        models=models,
    ),
    prefix='/api',
)
logfire.instrument_fastapi(app)
