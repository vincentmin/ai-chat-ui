import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { RouterProvider } from '@tanstack/react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppRouter } from './router'

vi.mock('./Chat.tsx', () => ({
  default: () => <div data-testid="chat-panel" />,
}))

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function createFetchMock() {
  return vi.fn((input: RequestInfo | URL) => {
    const requestUrl =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.toString()
          : input instanceof Request
            ? input.url
            : ''

    if (requestUrl.endsWith('/api/v1/sql/chats')) {
      return jsonResponse({
        conversations: [
          {
            id: 'conversation-1',
            firstMessage: 'Hello SQL',
            timestamp: 1_700_000_000_000,
          },
        ],
      })
    }

    if (requestUrl.endsWith('/api/v1/arxiv/chats')) {
      return jsonResponse({ conversations: [] })
    }

    return jsonResponse({})
  })
}

function renderAt(pathname: string) {
  window.history.pushState({}, '', pathname)
  const router = createAppRouter()
  render(<RouterProvider router={router} />)
  return router
}

describe('router integration', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', createFetchMock())
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    )
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('redirects root route to /sql', async () => {
    const router = renderAt('/')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/sql')
    })
  })

  it('navigates from /sql to /sql/chat/:id and updates sidebar selection', async () => {
    renderAt('/sql')

    const conversationText = await screen.findByText('Hello SQL')
    let conversationLink = conversationText.closest('a')

    expect(conversationLink).not.toBeNull()
    expect(conversationLink?.className.includes('bg-accent')).toBe(false)

    fireEvent.click(conversationLink!)

    await waitFor(() => {
      expect(window.location.pathname).toBe('/sql/chat/conversation-1')
    })

    conversationLink = screen.getByText('Hello SQL').closest('a')
    expect(conversationLink).not.toBeNull()
    expect(conversationLink?.className.includes('bg-accent')).toBe(true)
  })
})
