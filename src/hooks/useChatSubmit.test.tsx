import { renderHook, act, waitFor } from '@testing-library/react'
import type { ReactNode, SyntheticEvent } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatSubmit } from './useChatSubmit'

function createWrapper() {
  return ({ children }: { children: ReactNode }) => children
}

describe('useChatSubmit', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
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

  it('generates conversation id and sends pending message after id is set', async () => {
    const randomUUIDSpy = vi
      .spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('00000000-0000-4000-8000-000000000001')

    let conversationId: string | null = null
    const sendMessage = vi.fn().mockResolvedValue(undefined)
    const setConversationId = vi.fn()
    const dispatchEventSpy = vi.spyOn(window, 'dispatchEvent')

    const { result, rerender } = renderHook(
      () =>
        useChatSubmit({
          apiBasePath: '/api/v1/sql',
          conversationId,
          setConversationId,
          model: 'gpt-5',
          systemPrompt: 'custom prompt',
          canOverrideSystemPrompt: true,
          sendMessage,
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
      expect(setConversationId).toHaveBeenCalledWith('00000000-0000-4000-8000-000000000001')
    })

    expect(sendMessage).not.toHaveBeenCalled()

    conversationId = '00000000-0000-4000-8000-000000000001'
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
    randomUUIDSpy.mockRestore()
  })

  it('sends pending first message after route remount', async () => {
    const randomUUIDSpy = vi
      .spyOn(globalThis.crypto, 'randomUUID')
      .mockReturnValue('00000000-0000-4000-8000-000000000002')

    const sendMessage = vi.fn().mockResolvedValue(undefined)
    const setConversationId = vi.fn()

    const firstRender = renderHook(
      () =>
        useChatSubmit({
          apiBasePath: '/api/v1/sql',
          conversationId: null,
          setConversationId,
          model: 'gpt-5',
          systemPrompt: 'custom prompt',
          canOverrideSystemPrompt: true,
          sendMessage,
        }),
      {
        wrapper: createWrapper(),
      },
    )

    act(() => {
      firstRender.result.current.setInput('Message that survives remount')
    })

    act(() => {
      firstRender.result.current.handleSubmit({ preventDefault: vi.fn() } as unknown as SyntheticEvent)
    })

    await waitFor(() => {
      expect(setConversationId).toHaveBeenCalledWith('00000000-0000-4000-8000-000000000002')
    })

    firstRender.unmount()

    renderHook(
      () =>
        useChatSubmit({
          apiBasePath: '/api/v1/sql',
          conversationId: '00000000-0000-4000-8000-000000000002',
          setConversationId,
          model: 'gpt-5',
          systemPrompt: 'custom prompt',
          canOverrideSystemPrompt: true,
          sendMessage,
        }),
      {
        wrapper: createWrapper(),
      },
    )

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith(
        { text: 'Message that survives remount' },
        {
          body: {
            model: 'gpt-5',
            systemPrompt: 'custom prompt',
          },
        },
      )
    })

    expect(sendMessage).toHaveBeenCalledTimes(1)
    randomUUIDSpy.mockRestore()
  })
})
