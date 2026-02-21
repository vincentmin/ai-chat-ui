from __future__ import annotations as _annotations
import os
import logfire
from pydantic_ai.builtin_tools import (
    CodeExecutionTool,
    ImageGenerationTool,
    WebSearchTool,
)

from .agent import agent

# 'if-token-present' means nothing will be sent (and the example will work) if you don't have logfire configured
logfire.configure(send_to_logfire='if-token-present')
logfire.instrument_pydantic_ai()

models = {
    'Claude Sonnet 4.5': 'anthropic:claude-sonnet-4-5',
    'GPT 5': 'openai-responses:gpt-5',
    'Gemini 2.5 Pro': 'google-gla:gemini-2.5-pro',
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

app = agent.to_web(
    models=models,
    builtin_tools=[
        WebSearchTool(),
        CodeExecutionTool(),
        ImageGenerationTool(),
    ],
)
logfire.instrument_starlette(app)
