import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { useEffect, useRef, type ReactNode } from 'react'
import type { PanelImperativeHandle } from 'react-resizable-panels'

interface AgentChatTopPanelLayoutProps {
  hasTopPanelData: boolean
  showTopPanel: boolean
  chatPane: ReactNode
  topPanel: ReactNode
}

export function AgentChatTopPanelLayout({
  hasTopPanelData,
  showTopPanel,
  chatPane,
  topPanel,
}: AgentChatTopPanelLayoutProps) {
  const topPanelRef = useRef<PanelImperativeHandle | null>(null)

  useEffect(() => {
    if (!hasTopPanelData) {
      return
    }

    const panel = topPanelRef.current
    if (!panel) {
      return
    }

    if (showTopPanel) {
      panel.expand()
      if (panel.getSize().asPercentage < 20) {
        panel.resize('40%')
      }
      return
    }

    panel.collapse()
  }, [hasTopPanelData, showTopPanel])

  if (!hasTopPanelData) {
    return <>{chatPane}</>
  }

  return (
    <ResizablePanelGroup orientation="vertical" className="h-full min-h-0">
      <ResizablePanel
        panelRef={topPanelRef}
        defaultSize={showTopPanel ? '40%' : '0%'}
        minSize="20%"
        collapsedSize="0%"
        collapsible
      >
        {showTopPanel ? topPanel : null}
      </ResizablePanel>
      <ResizableHandle
        withHandle={showTopPanel}
        className={showTopPanel ? 'bg-border/80' : 'opacity-0 pointer-events-none'}
      />
      <ResizablePanel defaultSize={showTopPanel ? '60%' : '100%'} minSize="35%">
        {chatPane}
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
