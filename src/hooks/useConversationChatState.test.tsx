import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'

import { useConversationChatState } from './useConversationChatState'

const { useQueryMock, useChatMock } = vi.hoisted(() => ({
  useQueryMock: vi.fn(),
  useChatMock: vi.fn(),
})) as { useQueryMock: Mock; useChatMock: Mock }

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
      addToolApprovalResponse: vi.fn(),
    })

    const hydrateFromMessages = vi.fn()

    const { rerender } = renderHook<ReturnType<typeof useConversationChatState>, { conversationId: string | null }>(
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
    const firstUseChatCall = useChatMock.mock.calls[0] as [unknown] | undefined
    const firstUseChatArg = firstUseChatCall?.[0] as { sendAutomaticallyWhen?: unknown } | undefined
    expect(typeof firstUseChatArg?.sendAutomaticallyWhen).toBe('function')

    rerender({ conversationId: 'conversation-1' })

    expect(setMessages).toHaveBeenCalledTimes(1)
    expect(hydrateFromMessages).toHaveBeenCalledTimes(1)
    expect(resumeStream).toHaveBeenCalledTimes(1)
  })

  it('clears messages when conversation transitions to unset', () => {
    const setMessages = vi.fn()

    useQueryMock.mockReturnValue({
      data: undefined,
      isFetched: true,
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
      addToolApprovalResponse: vi.fn(),
    })

    const { rerender } = renderHook<ReturnType<typeof useConversationChatState>, { conversationId: string | null }>(
      ({ conversationId }: { conversationId: string | null }) =>
        useConversationChatState({
          apiBasePath: '/api/v1/sql',
          conversationId,
          onData: vi.fn(),
          onFinish: vi.fn(),
          hydrateFromMessages: vi.fn(),
        }),
      {
        initialProps: { conversationId: 'conversation-1' },
      },
    )

    rerender({ conversationId: '' })

    expect(setMessages).toHaveBeenCalledWith([])
  })

  it('does not hydrate late when chat becomes ready after submission', () => {
    const setMessages = vi.fn()
    const resumeStream = vi.fn().mockResolvedValue(undefined)
    const chatState = {
      setMessages,
      resumeStream,
      status: 'submitted',
      messages: [{ id: 'user-1', role: 'user', parts: [{ type: 'text', text: 'hello' }] }],
      sendMessage: vi.fn(),
      regenerate: vi.fn(),
      error: undefined,
      stop: vi.fn(),
      clearError: vi.fn(),
      addToolOutput: vi.fn(),
      addToolResult: vi.fn(),
      addToolApprovalResponse: vi.fn(),
    }

    useQueryMock.mockReturnValue({
      data: { messages: [] },
      isFetched: true,
      isLoading: false,
    })

    useChatMock.mockImplementation(() => chatState)

    const hydrateFromMessages = vi.fn()

    const { rerender } = renderHook(() =>
      useConversationChatState({
        apiBasePath: '/api/v1/sql',
        conversationId: 'conversation-1',
        onData: vi.fn(),
        onFinish: vi.fn(),
        hydrateFromMessages,
      }),
    )

    expect(setMessages).not.toHaveBeenCalled()
    expect(hydrateFromMessages).not.toHaveBeenCalled()
    expect(resumeStream).not.toHaveBeenCalled()

    chatState.status = 'ready'
    rerender()

    expect(setMessages).not.toHaveBeenCalled()
    expect(hydrateFromMessages).not.toHaveBeenCalled()
    expect(resumeStream).toHaveBeenCalledTimes(1)
  })
})
