from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from urllib.request import urlopen

import pydantic_ai
from bs4 import BeautifulSoup

ARXIV_API_URL = 'https://export.arxiv.org/api/query'
ARXIV_HTML_BASE_URL = 'https://arxiv.org/html/'
ATOM_NS = {'atom': 'http://www.w3.org/2005/Atom'}


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text('\n').splitlines()]
    return '\n'.join(line for line in lines if line)


agent = pydantic_ai.Agent(
    model='openai-responses:gpt-5-nano',
    instructions='You are an expert research assistant with access to Arxiv.',
)


@agent.tool_plain
def search(query: str) -> list[dict[str, str]]:
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
        with urlopen(f'{ARXIV_API_URL}?{params}', timeout=20) as response:
            payload = response.read()
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
        html_url = f'{ARXIV_HTML_BASE_URL}{arxiv_id}' if arxiv_id else ''

        results.append(
            {
                'id': arxiv_id,
                'title': ' '.join(title.split()),
                'abstract': ' '.join(abstract.split()),
                'published': published,
                'url': raw_id,
                'html_url': html_url,
            }
        )

    return results


@agent.tool_plain
def fetch(arxiv_id: str) -> str:
    """Fetch an Arxiv paper and return a readable plain-text version."""
    normalized_id = arxiv_id.strip()
    if normalized_id.startswith('http://') or normalized_id.startswith('https://'):
        normalized_id = normalized_id.rsplit('/', maxsplit=1)[-1]

    try:
        with urlopen(f'{ARXIV_HTML_BASE_URL}{normalized_id}', timeout=20) as response:
            charset = response.headers.get_content_charset() or 'utf-8'
            html = response.read().decode(charset, errors='replace')
            text = _html_to_text(html)
            if not text:
                raise pydantic_ai.ModelRetry(
                    f'No readable text extracted for Arxiv ID {arxiv_id}'
                )
            return text
    except Exception as e:
        raise pydantic_ai.ModelRetry(
            f'Failed to fetch and parse Arxiv paper {arxiv_id}: {e}'
        ) from e


if __name__ == '__main__':
    agent.to_cli_sync()
