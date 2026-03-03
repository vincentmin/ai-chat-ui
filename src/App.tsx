import Chat from './Chat.tsx'
import { AppSidebar } from './components/app-sidebar.tsx'
import type { SqlResultData } from './components/sql-result-table.tsx'
import type { AgentDataPanelPlugin } from './features/agent-data-panel-plugin.ts'
import type { ArxivPaperData } from './features/arxiv-agent/arxiv-data-panel-plugin.tsx'
import { arxivDataPanelPlugin } from './features/arxiv-agent/arxiv-data-panel-plugin.tsx'
import { sqlDataPanelPlugin } from './features/sql-agent/sql-data-panel.tsx'
import { cn } from './lib/utils.ts'

const SQL_QUICK_SUGGESTIONS = [
  'List the top 5 customers by total revenue with SQL and explain each clause.',
  'Find monthly sales trends for the last 12 months and suggest one actionable insight.',
  'Write a query to detect duplicate rows in a table and show how to fix them safely.',
]

const ARXIV_QUICK_SUGGESTIONS = [
  'Find recent arXiv papers on retrieval-augmented generation and summarize key approaches.',
  'Compare 3 arXiv papers on multimodal agents with strengths, limitations, and datasets.',
  'Give me a reading order for arXiv papers to learn transformer interpretability quickly.',
]

interface AgentPageConfig<TData> {
  kind: 'sql' | 'arxiv'
  apiBasePath: string
  conversationBasePath: string
  title: string
  dataPanelPlugin: AgentDataPanelPlugin<TData>
}

type SqlPageConfig = AgentPageConfig<SqlResultData> & { kind: 'sql' }
type ArxivPageConfig = AgentPageConfig<ArxivPaperData> & { kind: 'arxiv' }
type AnyAgentPageConfig = SqlPageConfig | ArxivPageConfig

function resolveAgentPage(kind: 'sql' | 'arxiv'): AnyAgentPageConfig {
  if (kind === 'arxiv') {
    return {
      kind: 'arxiv',
      apiBasePath: '/api/v1/arxiv',
      conversationBasePath: '/arxiv',
      title: 'Pydantic AI Arxiv',
      dataPanelPlugin: arxivDataPanelPlugin,
    }
  }

  return {
    kind: 'sql',
    apiBasePath: '/api/v1/sql',
    conversationBasePath: '/sql',
    title: 'Pydantic AI SQL',
    dataPanelPlugin: sqlDataPanelPlugin,
  }
}

interface AppProps {
  kind: 'sql' | 'arxiv'
  conversationId: string | null
  onConversationIdChange: (id: string | null) => void
}

export default function App({ kind, conversationId, onConversationIdChange }: AppProps) {
  const page = resolveAgentPage(kind)

  return (
    <>
      <AppSidebar
        apiBasePath={page.apiBasePath}
        conversationBasePath={page.conversationBasePath}
        title={page.title}
        conversationId={conversationId}
        onConversationIdChange={onConversationIdChange}
      />

      <div className="flex flex-col justify-center flex-1 h-screen overflow-hidden">
        <div
          className={cn(
            'flex flex-col max-w-4xl mx-auto relative w-full basis-[100vh] overflow-hidden',
            'has-[.stick-to-bottom:empty]:overflow-visible transition-[flex-basis] duration-200',
          )}
        >
          {page.kind === 'sql' ? (
            <Chat
              apiBasePath={page.apiBasePath}
              conversationId={conversationId}
              setConversationId={onConversationIdChange}
              dataPanelPlugin={page.dataPanelPlugin}
              quickSuggestions={SQL_QUICK_SUGGESTIONS}
            />
          ) : (
            <Chat
              apiBasePath={page.apiBasePath}
              conversationId={conversationId}
              setConversationId={onConversationIdChange}
              dataPanelPlugin={page.dataPanelPlugin}
              quickSuggestions={ARXIV_QUICK_SUGGESTIONS}
            />
          )}
        </div>
      </div>
    </>
  )
}
