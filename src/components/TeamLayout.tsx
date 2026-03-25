import Chat from '@/Chat'
import { noopDataPanelPlugin } from '@/features/noop-data-panel-plugin'
import type { TeamAgentInfo } from '@/types'

const TEAM_QUICK_SUGGESTIONS: Record<string, string[]> = {
  sql: ['List the top 5 artists.', 'Show me the total number of songs.'],
  arxiv: ['Find recent papers on retrieval-augmented generation.', 'Search for papers on multimodal agents.'],
}

interface TeamLayoutProps {
  agents: TeamAgentInfo[]
  conversationId: string | null
  setConversationId: (id: string | null) => void
}

export function TeamLayout({ agents, conversationId, setConversationId }: TeamLayoutProps) {
  return (
    <div className="flex flex-1 h-screen overflow-hidden divide-x">
      {agents.map((agent) => (
        <div key={agent.key} className="flex flex-col flex-1 min-w-0 h-full overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2 border-b bg-muted/30">
            <h2 className="text-sm font-medium truncate">{agent.title}</h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <Chat
              apiBasePath={agent.apiBasePath}
              conversationId={conversationId}
              setConversationId={setConversationId}
              dataPanelPlugin={noopDataPanelPlugin}
              quickSuggestions={TEAM_QUICK_SUGGESTIONS[agent.key] ?? []}
              pollForActivity
            />
          </div>
        </div>
      ))}
    </div>
  )
}
