import Chat from './Chat.tsx'
import { AppSidebar } from './components/app-sidebar.tsx'
import { ThemeProvider } from './components/theme-provider.tsx'
import { SidebarProvider } from './components/ui/sidebar.tsx'
import { Toaster } from './components/ui/sonner.tsx'
import type { SqlResultData } from './components/sql-result-table.tsx'
import type { AgentDataPanelPlugin } from './features/agent-data-panel-plugin.ts'
import { arxivDataPanelPlugin } from './features/arxiv-agent/arxiv-data-panel-plugin.tsx'
import { sqlDataPanelPlugin } from './features/sql-agent/sql-data-panel.tsx'
import { cn } from './lib/utils.ts'
import { useEffect, useState } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient()

interface AgentPageConfig<TData> {
  kind: 'sql' | 'arxiv'
  apiBasePath: string
  conversationBasePath: string
  title: string
  dataPanelPlugin: AgentDataPanelPlugin<TData>
}

type SqlPageConfig = AgentPageConfig<SqlResultData> & { kind: 'sql' }
type ArxivPageConfig = AgentPageConfig<null> & { kind: 'arxiv' }
type AnyAgentPageConfig = SqlPageConfig | ArxivPageConfig

function resolveAgentPage(pathname: string): AnyAgentPageConfig {
  if (pathname.startsWith('/arxiv')) {
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

export default function App() {
  const [pathname, setPathname] = useState(() => window.location.pathname)

  useEffect(() => {
    const handleNavigation = () => {
      setPathname(window.location.pathname)
    }

    window.addEventListener('popstate', handleNavigation)
    window.addEventListener('history-state-changed', handleNavigation)

    return () => {
      window.removeEventListener('popstate', handleNavigation)
      window.removeEventListener('history-state-changed', handleNavigation)
    }
  }, [])

  useEffect(() => {
    if (pathname === '/' || pathname.startsWith('/chat/')) {
      const nextPath = pathname === '/' ? '/sql' : `/sql${pathname}`
      window.history.replaceState({}, '', nextPath)
      setPathname(nextPath)
    }
  }, [pathname])

  const page = resolveAgentPage(pathname)

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" storageKey="pydantic-chat-ui-theme">
        <SidebarProvider defaultOpen>
          <AppSidebar
            apiBasePath={page.apiBasePath}
            conversationBasePath={page.conversationBasePath}
            title={page.title}
          />

          <div className="flex flex-col justify-center flex-1 h-screen overflow-hidden">
            <div
              className={cn(
                'flex flex-col max-w-4xl mx-auto relative w-full basis-[100vh] overflow-hidden',
                'has-[.stick-to-bottom:empty]:overflow-visible has-[.stick-to-bottom:empty]:basis-0 transition-[flex-basis] duration-200',
              )}
            >
              {page.kind === 'sql' ? (
                <Chat
                  apiBasePath={page.apiBasePath}
                  conversationBasePath={page.conversationBasePath}
                  dataPanelPlugin={page.dataPanelPlugin}
                />
              ) : (
                <Chat
                  apiBasePath={page.apiBasePath}
                  conversationBasePath={page.conversationBasePath}
                  dataPanelPlugin={page.dataPanelPlugin}
                />
              )}
            </div>
          </div>
        </SidebarProvider>
      </ThemeProvider>
      <Toaster richColors />
    </QueryClientProvider>
  )
}
