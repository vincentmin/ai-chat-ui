import { useState, useEffect, useCallback, type SyntheticEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { createConversation } from '@/lib/api'

interface UseChatSubmitOptions {
  apiBasePath: string
  conversationId: string | null
  setConversationId: (id: string) => void
  model: string
  systemPrompt: string
  canOverrideSystemPrompt: boolean | undefined
  sendMessage: (msg: { text: string }, opts: { body: Record<string, unknown> }) => Promise<void>
  configQueryData: { canOverrideSystemPrompt: boolean } | undefined
}

interface UseChatSubmitResult {
  input: string
  setInput: (value: string) => void
  handleSubmit: (e: SyntheticEvent) => void
  isCreatingConversation: boolean
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
    if (!conversationId || !pendingMessage) return
    sendTextMessage(pendingMessage)
    setPendingMessage(null)
  }, [conversationId, pendingMessage, sendTextMessage])

  const createConversationMutation = useMutation({
    mutationFn: () => createConversation(apiBasePath),
  })

  const handleSubmit = (e: SyntheticEvent) => {
    e.preventDefault()
    if (input.trim()) {
      const submittedText = input
      setInput('')

      if (!conversationId) {
        createConversationMutation.mutate(undefined, {
          onSuccess: (response) => {
            setConversationId(response.id)
            setPendingMessage(submittedText)
            window.dispatchEvent(new Event('conversations-changed'))
          },
          onError: (error: unknown) => {
            console.error('Error creating conversation:', error)
          },
        })
        return
      }

      sendTextMessage(submittedText)
    }
  }

  return {
    input,
    setInput,
    handleSubmit,
    isCreatingConversation: createConversationMutation.isPending,
  }
}
