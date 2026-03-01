import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getConfig, getConversationMessages, getConversations, removeConversation } from './api'

describe('api helpers', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('getConfig fetches and returns remote config', async () => {
    const payload = {
      models: [{ id: 'gpt-5', name: 'GPT-5' }],
      canOverrideSystemPrompt: true,
      defaultSystemPrompt: 'default prompt',
    }

    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const result = await getConfig('/api/v1/sql')

    expect(fetch).toHaveBeenCalledWith('/api/v1/sql/configure')
    expect(result).toEqual(payload)
  })

  it('getConfig throws when response is not ok', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 500 }))

    await expect(getConfig('/api/v1/sql')).rejects.toThrow('Failed to load configuration')
  })

  it('getConversationMessages throws when response is not ok', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }))

    await expect(getConversationMessages('/api/v1/sql', 'conversation-1')).rejects.toThrow(
      'Failed to load conversation',
    )
    expect(fetch).toHaveBeenCalledWith('/api/v1/sql/chat/conversation-1')
  })

  it('getConversations fetches and returns conversations', async () => {
    const payload = {
      conversations: [{ id: 'conversation-1', timestamp: 1735689600000, firstMessage: 'hello' }],
    }

    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const result = await getConversations('/api/v1/sql')

    expect(fetch).toHaveBeenCalledWith('/api/v1/sql/chats')
    expect(result).toEqual(payload)
  })

  it('removeConversation sends delete request', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))

    await removeConversation('/api/v1/sql', 'conversation-1')

    expect(fetch).toHaveBeenCalledWith('/api/v1/sql/chat/conversation-1', {
      method: 'DELETE',
    })
  })

  it('removeConversation throws when delete fails', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 500 }))

    await expect(removeConversation('/api/v1/sql', 'conversation-1')).rejects.toThrow('Failed to delete conversation')
  })
})
