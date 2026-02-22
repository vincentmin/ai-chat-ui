from __future__ import annotations as _annotations

import os

import logfire
from fastapi import FastAPI

from .agent import agent
from .chat_router import create_chat_router

# 'if-token-present' means nothing will be sent (and the example will work) if you don't
# have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

if not (
    os.getenv('OPENAI_API_KEY')
    or os.getenv('ANTHROPIC_API_KEY')
    or os.getenv('GOOGLE_API_KEY')
):
    raise ValueError(
        'No models configured. Please set OPENAI_API_KEY, ANTHROPIC_API_KEY, or '
        'GOOGLE_API_KEY environment variable.'
    )

agents = {
    'assistant': agent,
    'assistant2': agent,
}

app = FastAPI(title='AI Chat API')
app.include_router(
    create_chat_router(
        agents=agents,
    ),
    prefix='/api',
)
logfire.instrument_fastapi(app)
