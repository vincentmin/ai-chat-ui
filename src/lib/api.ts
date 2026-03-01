import type { RemoteConfig, ChatHistoryResponse } from '@/types'

export async function getConfig(apiBasePath: string): Promise<RemoteConfig> {
  const res = await fetch(`${apiBasePath}/configure`)
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
