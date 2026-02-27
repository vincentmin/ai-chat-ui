import { useQuery } from '@tanstack/react-query'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { useChat } from '@ai-sdk/react'
import { useEffect, useMemo, useRef } from 'react'

import { getConversationMessages } from '@/lib/api'

interface ChatFinishEvent {
  isAbort: boolean
  isDisconnect: boolean
  isError: boolean
}

interface UseConversationChatStateOptions {
  apiBasePath: string
  conversationId: string | null
  onData: (part: unknown) => void
  onFinish: (event: ChatFinishEvent) => void
  hydrateFromMessages: (messages: UIMessage[]) => void
}

export function useConversationChatState({
  apiBasePath,
  conversationId,
  onData,
  onFinish,
  hydrateFromMessages,
}: UseConversationChatStateOptions) {
  const chatApi = conversationId ? `${apiBasePath}/chat/${conversationId}` : `${apiBasePath}/chat/__pending__`

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: chatApi,
        prepareReconnectToStreamRequest: ({ id }) => ({
          api: `${apiBasePath}/chat/${id}/stream`,
        }),
      }),
    [chatApi, apiBasePath],
  )

  const messagesQuery = useQuery({
    queryKey: ['conversation', apiBasePath, conversationId],
    queryFn: () => getConversationMessages(apiBasePath, conversationId!),
    enabled: !!conversationId,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const hydratedConversationIdRef = useRef<string | null>(null)
  const resumedConversationIdRef = useRef<string | null>(null)

  const chat = useChat({
    id: conversationId ?? undefined,
    transport,
    resume: false,
    onData,
    onFinish,
  })

  const { setMessages, status, resumeStream } = chat

  useEffect(() => {
    if (!conversationId) {
      hydratedConversationIdRef.current = null
      resumedConversationIdRef.current = null
      setMessages([])
      return
    }

    if (!messagesQuery.isFetched) {
      return
    }

    if (status !== 'ready') {
      return
    }

    if (hydratedConversationIdRef.current !== conversationId) {
      const historyMessages = messagesQuery.data?.messages ?? []
      setMessages(historyMessages)
      hydrateFromMessages(historyMessages)
      hydratedConversationIdRef.current = conversationId
    }

    if (resumedConversationIdRef.current === conversationId) {
      return
    }

    resumedConversationIdRef.current = conversationId
    resumeStream().catch((error: unknown) => {
      console.error('Error resuming stream:', error)
    })
  }, [
    conversationId,
    messagesQuery.data,
    messagesQuery.isFetched,
    hydrateFromMessages,
    resumeStream,
    setMessages,
    status,
  ])

  return chat
}
