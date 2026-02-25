from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

import httpx
import pydantic_ai
from pydantic_ai.ui.vercel_ai.response_types import DataChunk

ARXIV_API_URL = 'https://export.arxiv.org/api/query'
ARXIV_ABS_BASE_URL = 'https://arxiv.org/abs/'
ARXIV_PDF_BASE_URL = 'https://arxiv.org/pdf/'
ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}


def _normalize_arxiv_id(arxiv_id: str) -> str:
    normalized_id = arxiv_id.strip()

    if normalized_id.startswith('http://') or normalized_id.startswith('https://'):
        normalized_id = normalized_id.rstrip('/').rsplit('/', maxsplit=1)[-1]

    if normalized_id.endswith('.pdf'):
        normalized_id = normalized_id[:-4]

    return normalized_id


def _pdf_url(arxiv_id: str) -> str:
    return f'{ARXIV_PDF_BASE_URL}{arxiv_id}.pdf'


def _abs_url(arxiv_id: str) -> str:
    return f'{ARXIV_ABS_BASE_URL}{arxiv_id}'


def _proxy_pdf_url(arxiv_id: str) -> str:
    encoded_id = quote(arxiv_id, safe='')
    return f'/api/v1/arxiv/paper/{encoded_id}/pdf'


agent = pydantic_ai.Agent(
    model='openai-responses:gpt-4.1-nano',
    instructions=(
        'You are an expert research assistant with access to Arxiv. '
        'Use search to find papers, fetch to read paper PDFs, and display_paper '
        'to show or preview a paper to the user in the UI. Be proactive in suggesting '
        'to display papers that might be relevant to the user.'
    ),
)


@agent.tool_plain
async def search(query: str) -> list[dict[str, str]]:
    """Search Arxiv and return paper metadata including abstracts."""
    max_results = 5
    params = urlencode(
        {
            'search_query': f'all:{query}',
            'start': 0,
            'max_results': max_results,
            'sortBy': 'relevance',
            'sortOrder': 'descending',
        }
    )

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(f'{ARXIV_API_URL}?{params}')
            response.raise_for_status()
            payload = response.content
    except Exception as e:
        raise pydantic_ai.ModelRetry(f'Failed to search Arxiv: {e}') from e

    root = ET.fromstring(payload)
    results: list[dict[str, str]] = []

    for entry in root.findall('atom:entry', namespaces=ATOM_NS):
        raw_id = entry.findtext('atom:id', default='', namespaces=ATOM_NS).strip()
        title = entry.findtext('atom:title', default='', namespaces=ATOM_NS).strip()
        abstract = entry.findtext(
            'atom:summary', default='', namespaces=ATOM_NS
        ).strip()
        published = entry.findtext(
            'atom:published', default='', namespaces=ATOM_NS
        ).strip()

        arxiv_id = raw_id.rsplit('/', maxsplit=1)[-1] if raw_id else ''
        pdf_url = _pdf_url(arxiv_id) if arxiv_id else ''

        results.append(
            {
                'id': arxiv_id,
                'title': ' '.join(title.split()),
                'abstract': ' '.join(abstract.split()),
                'published': published,
                'url': raw_id or _abs_url(arxiv_id),
                'pdf_url': pdf_url,
            }
        )

    return results


@agent.tool_plain
def fetch(arxiv_id: str) -> pydantic_ai.ToolReturn:
    """Provide a paper PDF to the model as document content."""
    normalized_id = _normalize_arxiv_id(arxiv_id)
    if not normalized_id:
        raise pydantic_ai.ModelRetry(f'Invalid Arxiv ID: {arxiv_id}')

    return pydantic_ai.ToolReturn(
        return_value=f'Loaded PDF for Arxiv paper {normalized_id}',
        content=[
            pydantic_ai.DocumentUrl(
                url=_pdf_url(normalized_id),
                media_type='application/pdf',
            )
        ],
    )


@agent.tool_plain
def display_paper(arxiv_id: str) -> pydantic_ai.ToolReturn:
    """Send a paper preview payload so the frontend can render a PDF iframe panel."""
    resolved_id = _normalize_arxiv_id(arxiv_id)
    if not resolved_id:
        raise pydantic_ai.ModelRetry(f'Invalid Arxiv ID: {arxiv_id}')

    return pydantic_ai.ToolReturn(
        return_value=f'Paper preview displayed for {resolved_id}',
        metadata=[
            DataChunk(
                type='data-arxiv-paper',
                data={
                    'arxiv_id': resolved_id,
                    'title': f'Arxiv Paper {resolved_id}',
                    'url': _abs_url(resolved_id),
                    'pdf_url': _proxy_pdf_url(resolved_id),
                },
            ),
        ],
    )


if __name__ == '__main__':
    agent.to_cli_sync()
