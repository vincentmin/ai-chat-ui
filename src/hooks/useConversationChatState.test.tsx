import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import { useConversationChatState } from './useConversationChatState'

const useQueryMock: Mock = vi.fn()
const useChatMock: Mock = vi.fn()

vi.mock('@tanstack/react-query', () => ({
  useQuery: useQueryMock,
}))

vi.mock('@ai-sdk/react', () => ({
  useChat: useChatMock,
}))

vi.mock('@/lib/api', () => ({
  getConversationMessages: vi.fn(),
}))

describe('useConversationChatState', () => {
  beforeEach(() => {
    useQueryMock.mockReset()
    useChatMock.mockReset()
  })

  it('hydrates history and resumes exactly once per conversation', () => {
    const setMessages = vi.fn()
    const resumeStream = vi.fn().mockResolvedValue(undefined)

    useQueryMock.mockReturnValue({
      data: {
        messages: [{ id: 'assistant-1', role: 'assistant', parts: [{ type: 'text', text: 'Hello' }] }],
      },
      isFetched: true,
      isLoading: false,
    })

    useChatMock.mockReturnValue({
      setMessages,
      resumeStream,
      status: 'ready',
      messages: [],
      sendMessage: vi.fn(),
      regenerate: vi.fn(),
      error: undefined,
      stop: vi.fn(),
      clearError: vi.fn(),
      addToolOutput: vi.fn(),
      addToolResult: vi.fn(),
    })

    const hydrateFromMessages = vi.fn()

    const { rerender } = renderHook(
      ({ conversationId }: { conversationId: string | null }) =>
        useConversationChatState({
          apiBasePath: '/api/v1/sql',
          conversationId,
          onData: vi.fn(),
          onFinish: vi.fn(),
          hydrateFromMessages,
        }),
      {
        initialProps: { conversationId: 'conversation-1' },
      },
    )

    expect(setMessages).toHaveBeenCalledTimes(1)
    expect(hydrateFromMessages).toHaveBeenCalledTimes(1)
    expect(resumeStream).toHaveBeenCalledTimes(1)

    rerender({ conversationId: 'conversation-1' })

    expect(setMessages).toHaveBeenCalledTimes(1)
    expect(hydrateFromMessages).toHaveBeenCalledTimes(1)
    expect(resumeStream).toHaveBeenCalledTimes(1)
  })

  it('clears messages when conversation is unset', () => {
    const setMessages = vi.fn()

    useQueryMock.mockReturnValue({
      data: undefined,
      isFetched: false,
      isLoading: false,
    })

    useChatMock.mockReturnValue({
      setMessages,
      resumeStream: vi.fn().mockResolvedValue(undefined),
      status: 'ready',
      messages: [],
      sendMessage: vi.fn(),
      regenerate: vi.fn(),
      error: undefined,
      stop: vi.fn(),
      clearError: vi.fn(),
      addToolOutput: vi.fn(),
      addToolResult: vi.fn(),
    })

    renderHook(() =>
      useConversationChatState({
        apiBasePath: '/api/v1/sql',
        conversationId: null,
        onData: vi.fn(),
        onFinish: vi.fn(),
        hydrateFromMessages: vi.fn(),
      }),
    )

    expect(setMessages).toHaveBeenCalledWith([])
  })
})
