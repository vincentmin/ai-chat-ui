import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act, waitFor } from '@testing-library/react'
import type { ReactNode, SyntheticEvent } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatSubmit } from './useChatSubmit'

const { createConversationMock } = vi.hoisted(() => ({
  createConversationMock: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  createConversation: createConversationMock,
}))

interface HookProps {
  conversationId: string | null
}

type UseChatSubmitResult = ReturnType<typeof useChatSubmit>

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  })

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('useChatSubmit', () => {
  beforeEach(() => {
    createConversationMock.mockReset()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('sends message directly when conversation already exists', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    const setConversationId = vi.fn()

    const { result } = renderHook(
      () =>
        useChatSubmit({
          apiBasePath: '/api/v1/sql',
          conversationId: 'conversation-1',
          setConversationId,
          model: 'gpt-5',
          systemPrompt: 'custom prompt',
          canOverrideSystemPrompt: false,
          sendMessage,
          configQueryData: { canOverrideSystemPrompt: false },
        }),
      {
        wrapper: createWrapper(),
      },
    )

    const preventDefault = vi.fn()

    act(() => {
      result.current.setInput('Hello existing conversation')
    })

    act(() => {
      result.current.handleSubmit({ preventDefault } as unknown as SyntheticEvent)
    })

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledTimes(1)
    })

    expect(preventDefault).toHaveBeenCalledTimes(1)
    expect(createConversationMock).not.toHaveBeenCalled()
    expect(setConversationId).not.toHaveBeenCalled()
    expect(result.current.input).toBe('')
    expect(sendMessage).toHaveBeenCalledWith(
      { text: 'Hello existing conversation' },
      {
        body: {
          model: 'gpt-5',
          systemPrompt: undefined,
        },
      },
    )
  })

  it('creates conversation first and sends pending message after id is set', async () => {
    createConversationMock.mockResolvedValue({ id: 'conversation-new' })

    let conversationId: string | null = null
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    const setConversationId = vi.fn()
    const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent')

    const { result, rerender } = renderHook<UseChatSubmitResult, HookProps>(
      () =>
        useChatSubmit({
          apiBasePath: '/api/v1/sql',
          conversationId,
          setConversationId,
          model: 'gpt-5',
          systemPrompt: 'custom prompt',
          canOverrideSystemPrompt: true,
          sendMessage,
          configQueryData: { canOverrideSystemPrompt: true },
        }),
      {
        wrapper: createWrapper(),
      },
    )

    act(() => {
      result.current.setInput('Hello from pending state')
    })

    act(() => {
      result.current.handleSubmit({ preventDefault: vi.fn() } as unknown as SyntheticEvent)
    })

    await waitFor(() => {
      expect(createConversationMock).toHaveBeenCalledWith('/api/v1/sql')
    })

    await waitFor(() => {
      expect(setConversationId).toHaveBeenCalledWith('conversation-new')
    })

    expect(sendMessage).not.toHaveBeenCalled()

    conversationId = 'conversation-new'
    rerender()

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith(
        { text: 'Hello from pending state' },
        {
          body: {
            model: 'gpt-5',
            systemPrompt: 'custom prompt',
          },
        },
      )
    })

    expect(dispatchEventSpy).toHaveBeenCalledTimes(1)
  })
})
