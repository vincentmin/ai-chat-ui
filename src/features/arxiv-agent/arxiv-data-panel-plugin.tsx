import type { AgentDataPanelPlugin } from '@/features/agent-data-panel-plugin'
import type { UIMessage } from 'ai'
import { useCallback } from 'react'

function useArxivDataPanelController() {
  const onDataPart = useCallback((_part: unknown) => undefined, [])
  const hydrateFromMessages = useCallback((_messages: UIMessage[]) => undefined, [])
  const toggleDataPanel = useCallback(() => undefined, [])
  const closeDataPanel = useCallback(() => undefined, [])
  const resetDataPanel = useCallback(() => undefined, [])

  return {
    data: null,
    hasData: false,
    showDataPanel: false,
    onDataPart,
    hydrateFromMessages,
    toggleDataPanel,
    closeDataPanel,
    resetDataPanel,
  }
}

function ArxivDataPanelToggleButton() {
  return null
}

function ArxivDataPanelView() {
  return null
}

export const arxivDataPanelPlugin: AgentDataPanelPlugin<null> = {
  useDataPanelController: useArxivDataPanelController,
  ToggleButton: ArxivDataPanelToggleButton,
  DataPanel: ArxivDataPanelView,
}
