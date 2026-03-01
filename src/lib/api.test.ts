import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getConfig, getConversationMessages } from './api'

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

  it('getConversationMessages throws when response is not ok', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 404 }))

    await expect(getConversationMessages('/api/v1/sql', 'conversation-1')).rejects.toThrow(
      'Failed to load conversation',
    )
    expect(fetch).toHaveBeenCalledWith('/api/v1/sql/chat/conversation-1')
  })
})
