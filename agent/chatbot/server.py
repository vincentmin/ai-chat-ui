from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import logfire
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from . import arxiv_agent as arxiv_agent_module
from .chat_router import create_chat_router
from .lifespan import lifespan
from .settings import get_settings
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
        agent=arxiv_agent_module.agent,
        models=models,
        agent_key='arxiv',
    ),
    prefix='/api/v1/arxiv',
)


@app.get('/api/v1/arxiv/paper/{arxiv_id:path}/pdf')
async def arxiv_pdf_proxy(arxiv_id: str) -> Response:
    normalized_id = arxiv_agent_module._normalize_arxiv_id(arxiv_id)
    if not normalized_id:
        raise HTTPException(status_code=400, detail='Invalid arXiv id')

    pdf_url = arxiv_agent_module._pdf_url(normalized_id)

    async def stream_pdf() -> AsyncIterator[bytes]:
        try:
            async with (
                httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client,
                client.stream('GET', pdf_url) as upstream,
            ):
                upstream.raise_for_status()
                async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                    if chunk:
                        yield chunk
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502,
                detail=f'Failed to fetch arXiv PDF: {e}',
            ) from e

    filename = normalized_id.replace('/', '_')
    return StreamingResponse(
        stream_pdf(),
        media_type='application/pdf',
        headers={
            'Content-Disposition': f'inline; filename="{filename}.pdf"',
            'Cache-Control': 'public, max-age=300',
        },
    )


logfire.instrument_fastapi(app)
