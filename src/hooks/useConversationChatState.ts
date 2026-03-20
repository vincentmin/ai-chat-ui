import { useQuery } from '@tanstack/react-query'
import { DefaultChatTransport, lastAssistantMessageIsCompleteWithApprovalResponses, type UIMessage } from 'ai'
import { useChat } from '@ai-sdk/react'
import { useEffect, useMemo, useRef } from 'react'

import { getConversationMessages } from '@/lib/api'
import { useAgentActivityPoller } from './useAgentActivityPoller'

/**
 * Wraps the global fetch to handle 202 Accepted responses from the chat endpoint.
 * When the backend returns 202 it means the agent is already active and the user's
 * message was pushed to its mailbox. We return a synthetic empty-stream response
 * so the AI SDK transport can complete without error.
 */
async function mailboxAwareFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await fetch(input, init)
  if (res.status === 202) {
    // Return a 200 with an empty done-stream so the transport completes cleanly.
    const body = new ReadableStream({
      start(controller) {
        controller.close()
      },
    })
    return new Response(body, {
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
    })
  }
  return res
}

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
  /** Enable polling for agent-initiated runs (team mode). */
  pollForActivity?: boolean
}

export function useConversationChatState({
  apiBasePath,
  conversationId,
  onData,
  onFinish,
  hydrateFromMessages,
  pollForActivity = false,
}: UseConversationChatStateOptions) {
  const chatApi = conversationId ? `${apiBasePath}/chat/${conversationId}` : `${apiBasePath}/chat/__pending__`

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: chatApi,
        fetch: pollForActivity ? mailboxAwareFetch : undefined,
        prepareReconnectToStreamRequest: ({ id }) => ({
          api: `${apiBasePath}/chat/${id}/stream`,
        }),
      }),
    [chatApi, apiBasePath, pollForActivity],
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
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
  })

  const { setMessages, status, resumeStream } = chat

  useEffect(() => {
    if (!conversationId) {
      const hadHydratedConversation = hydratedConversationIdRef.current !== null
      const hadResumedConversation = resumedConversationIdRef.current !== null

      hydratedConversationIdRef.current = null
      resumedConversationIdRef.current = null

      if (hadHydratedConversation || hadResumedConversation) {
        setMessages([])
      }

      return
    }

    if (!messagesQuery.isFetched) {
      return
    }

    if (status !== 'ready') {
      if (hydratedConversationIdRef.current !== conversationId) {
        // Mark hydration as handled so a late transition to ready does not clobber active turn messages.
        hydratedConversationIdRef.current = conversationId
      }
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
  useAgentActivityPoller({
    apiBasePath,
    conversationId,
    chatStatus: pollForActivity ? status : 'disabled',
    resumeStream,
  })
  return chat
}
