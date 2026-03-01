import type { ChatHistoryResponse, ConversationsResponse, RemoteConfig } from '@/types'

export async function getConfig(apiBasePath: string): Promise<RemoteConfig> {
  const res = await fetch(`${apiBasePath}/configure`)
  if (!res.ok) {
    throw new Error('Failed to load configuration')
  }
  return (await res.json()) as RemoteConfig
}

export async function getConversationMessages(
  apiBasePath: string,
  conversationId: string,
): Promise<ChatHistoryResponse> {
  const res = await fetch(`${apiBasePath}/chat/${conversationId}`)
  if (!res.ok) {
    throw new Error('Failed to load conversation')
  }
  return (await res.json()) as ChatHistoryResponse
}

export async function getConversations(apiBasePath: string): Promise<ConversationsResponse> {
  const res = await fetch(`${apiBasePath}/chats`)
  if (!res.ok) {
    throw new Error('Failed to fetch conversations')
  }
  return (await res.json()) as ConversationsResponse
}

export async function removeConversation(apiBasePath: string, conversationId: string): Promise<void> {
  const res = await fetch(`${apiBasePath}/chat/${conversationId}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    throw new Error('Failed to delete conversation')
  }
}
