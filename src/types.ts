import type { UIMessage } from 'ai'

export interface ConversationEntry {
  id: string
  firstMessage?: string
  timestamp: number
}

export interface ModelConfig {
  id: string
  name: string
}

export interface RemoteConfig {
  models: ModelConfig[]
  canOverrideSystemPrompt: boolean
  defaultSystemPrompt: string | null
}

export interface ChatHistoryResponse {
  messages: UIMessage[]
}

export interface ConversationsResponse {
  conversations: ConversationEntry[]
}

export interface TeamAgentInfo {
  key: string
  title: string
  apiBasePath: string
}

export interface TeamConfig {
  agents: TeamAgentInfo[]
}
