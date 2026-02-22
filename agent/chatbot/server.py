from __future__ import annotations as _annotations

import os

from fastapi import FastAPI
import logfire
from pydantic_ai.builtin_tools import (
    CodeExecutionTool,
    ImageGenerationTool,
    WebSearchTool,
)

from .agent import agent
from .chat_router import create_chat_router

# 'if-token-present' means nothing will be sent (and the example will work) if you don't have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

models = {
    'Claude Sonnet 4.5': 'anthropic:claude-haiku-4-5',
    'GPT 5': 'openai-responses:gpt-5-nano',
    'Gemini 2.5 Pro': 'google-gla:gemini-3-flash-preview',
}
if not os.getenv('OPENAI_API_KEY'):
    del models['GPT 5']
if not os.getenv('ANTHROPIC_API_KEY'):
    del models['Claude Sonnet 4.5']
if not os.getenv('GOOGLE_API_KEY'):
    del models['Gemini 2.5 Pro']
if not models:
    raise ValueError(
        'No models configured. Please set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GOOGLE_API_KEY environment variable.'
    )

app = FastAPI(title='AI Chat API')
app.include_router(
    create_chat_router(
        agent=agent,
        models=models,
        builtin_tools=[
            WebSearchTool(),
            CodeExecutionTool(),
            ImageGenerationTool(),
        ],
    ),
    prefix='/api',
)
logfire.instrument_fastapi(app)
