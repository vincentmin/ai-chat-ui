import type { AgentTopPanelPlugin } from '@/features/agent-top-panel-plugin'
import type { UIMessage } from 'ai'
import { useCallback } from 'react'

function useArxivTopPanelController() {
  const onDataPart = useCallback((_part: unknown) => undefined, [])
  const hydrateFromMessages = useCallback((_messages: UIMessage[]) => undefined, [])
  const toggleTopPanel = useCallback(() => undefined, [])
  const closeTopPanel = useCallback(() => undefined, [])
  const resetTopPanel = useCallback(() => undefined, [])

  return {
    data: null,
    hasData: false,
    showTopPanel: false,
    onDataPart,
    hydrateFromMessages,
    toggleTopPanel,
    closeTopPanel,
    resetTopPanel,
  }
}

function ArxivTopPanelToggleButton() {
  return null
}

function ArxivTopPanelView() {
  return null
}

export const arxivTopPanelPlugin: AgentTopPanelPlugin<null> = {
  useTopPanelController: useArxivTopPanelController,
  ToggleButton: ArxivTopPanelToggleButton,
  TopPanel: ArxivTopPanelView,
}
