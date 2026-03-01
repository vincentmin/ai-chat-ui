import { useState, useEffect, useCallback, type SyntheticEvent } from 'react'

const PENDING_FIRST_MESSAGE_KEY = 'pending-first-message'

function getPendingMessageStorageKey(apiBasePath: string, conversationId: string): string {
  return `${PENDING_FIRST_MESSAGE_KEY}:${apiBasePath}:${conversationId}`
}

function persistPendingMessage(apiBasePath: string, conversationId: string, message: string) {
  try {
    window.sessionStorage.setItem(getPendingMessageStorageKey(apiBasePath, conversationId), message)
  } catch {
    // sessionStorage may be unavailable in some environments; continue with in-memory fallback.
  }
}

function consumePendingMessage(apiBasePath: string, conversationId: string): string | null {
  try {
    const key = getPendingMessageStorageKey(apiBasePath, conversationId)
    const value = window.sessionStorage.getItem(key)
    if (value) {
      window.sessionStorage.removeItem(key)
    }
    return value
  } catch {
    return null
  }
}

function clearPendingMessage(apiBasePath: string, conversationId: string) {
  try {
    window.sessionStorage.removeItem(getPendingMessageStorageKey(apiBasePath, conversationId))
  } catch {
    // Ignore storage failures; sending can still proceed with in-memory state.
  }
}

interface UseChatSubmitOptions {
  apiBasePath: string
  conversationId: string | null
  setConversationId: (id: string) => void
  model: string
  systemPrompt: string
  canOverrideSystemPrompt: boolean | undefined
  sendMessage: (msg: { text: string }, opts: { body: Record<string, unknown> }) => Promise<void>
}

interface UseChatSubmitResult {
  input: string
  setInput: (value: string) => void
  handleSubmit: (e: SyntheticEvent) => void
}

function generateConversationId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function useChatSubmit({
  apiBasePath,
  conversationId,
  setConversationId,
  model,
  systemPrompt,
  canOverrideSystemPrompt,
  sendMessage,
}: UseChatSubmitOptions): UseChatSubmitResult {
  const [input, setInput] = useState('')
  const [pendingMessage, setPendingMessage] = useState<string | null>(null)

  const sendTextMessage = useCallback(
    (text: string) => {
      sendMessage(
        { text },
        {
          body: {
            model,
            systemPrompt: canOverrideSystemPrompt ? systemPrompt : undefined,
          },
        },
      ).catch((error: unknown) => {
        console.error('Error sending message:', error)
      })
    },
    [sendMessage, model, systemPrompt, canOverrideSystemPrompt],
  )

  useEffect(() => {
    if (!conversationId) return

    const messageToSend = pendingMessage ?? consumePendingMessage(apiBasePath, conversationId)
    if (!messageToSend) {
      return
    }

    if (pendingMessage) {
      clearPendingMessage(apiBasePath, conversationId)
      setPendingMessage(null)
    }

    sendTextMessage(messageToSend)
  }, [apiBasePath, conversationId, pendingMessage, sendTextMessage])

  const handleSubmit = (e: SyntheticEvent) => {
    e.preventDefault()
    if (input.trim()) {
      const submittedText = input
      setInput('')

      if (!conversationId) {
        const newConversationId = generateConversationId()
        persistPendingMessage(apiBasePath, newConversationId, submittedText)
        setConversationId(newConversationId)
        setPendingMessage(submittedText)
        window.dispatchEvent(new Event('conversations-changed'))
        return
      }

      sendTextMessage(submittedText)
    }
  }

  return {
    input,
    setInput,
    handleSubmit,
  }
}
