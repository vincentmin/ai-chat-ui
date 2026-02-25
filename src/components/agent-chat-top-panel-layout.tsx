import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { useEffect, useRef, type ReactNode } from 'react'
import type { PanelImperativeHandle } from 'react-resizable-panels'
import type { DataPanelPosition } from '@/features/agent-top-panel-plugin'

interface AgentChatDataPanelLayoutProps {
  hasDataPanelData: boolean
  showDataPanel: boolean
  dataPanelPosition: DataPanelPosition
  chatPane: ReactNode
  dataPanel: ReactNode
}

export function AgentChatDataPanelLayout({
  hasDataPanelData,
  showDataPanel,
  dataPanelPosition,
  chatPane,
  dataPanel,
}: AgentChatDataPanelLayoutProps) {
  const dataPanelRef = useRef<PanelImperativeHandle | null>(null)

  useEffect(() => {
    if (!hasDataPanelData) {
      return
    }

    const panel = dataPanelRef.current
    if (!panel) {
      return
    }

    if (showDataPanel) {
      panel.expand()
      if (panel.getSize().asPercentage < 20) {
        panel.resize('40%')
      }
      return
    }

    panel.collapse()
  }, [hasDataPanelData, showDataPanel])

  if (!hasDataPanelData) {
    return <>{chatPane}</>
  }

  const orientation = dataPanelPosition === 'left' || dataPanelPosition === 'right' ? 'horizontal' : 'vertical'
  const isDataPanelFirst = dataPanelPosition === 'top' || dataPanelPosition === 'left'
  const dataPanelMinSize = orientation === 'vertical' ? '20%' : '25%'
  const chatPaneMinSize = orientation === 'vertical' ? '35%' : '40%'

  const dataPanelNode = (
    <ResizablePanel
      panelRef={dataPanelRef}
      defaultSize={showDataPanel ? '40%' : '0%'}
      minSize={dataPanelMinSize}
      collapsedSize="0%"
      collapsible
    >
      {showDataPanel ? dataPanel : null}
    </ResizablePanel>
  )

  const chatPaneNode = (
    <ResizablePanel defaultSize={showDataPanel ? '60%' : '100%'} minSize={chatPaneMinSize}>
      {chatPane}
    </ResizablePanel>
  )

  const resizeHandle = (
    <ResizableHandle
      withHandle={showDataPanel}
      className={showDataPanel ? 'bg-border/80' : 'opacity-0 pointer-events-none'}
    />
  )

  return (
    <ResizablePanelGroup orientation={orientation} className="h-full min-h-0">
      {isDataPanelFirst ? dataPanelNode : chatPaneNode}
      {resizeHandle}
      {isDataPanelFirst ? chatPaneNode : dataPanelNode}
    </ResizablePanelGroup>
  )
}

export const AgentChatTopPanelLayout = AgentChatDataPanelLayout
