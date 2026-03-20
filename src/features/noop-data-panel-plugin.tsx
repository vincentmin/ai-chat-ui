import { useCallback, useState } from 'react'
import type {
  AgentDataPanelController,
  AgentDataPanelPlugin,
  AgentDataPanelProps,
  AgentDataPanelToggleButtonProps,
} from '@/features/agent-data-panel-plugin'

function NoopToggleButton(_props: AgentDataPanelToggleButtonProps) {
  return null
}

function NoopDataPanel(_props: AgentDataPanelProps<never>) {
  return null
}

function useNoopDataPanelController(): AgentDataPanelController<never> {
  const [, setToggle] = useState(false)
  // eslint-disable-next-line @typescript-eslint/no-empty-function
  const noop = useCallback(() => {}, [])
  return {
    data: null,
    hasData: false,
    showDataPanel: false,
    onDataPart: noop,
    hydrateFromMessages: noop,
    toggleDataPanel: () => {
      setToggle((v) => !v)
    },
    closeDataPanel: noop,
    resetDataPanel: noop,
  }
}

export const noopDataPanelPlugin: AgentDataPanelPlugin<never> = {
  useDataPanelController: useNoopDataPanelController,
  ToggleButton: NoopToggleButton,
  DataPanel: NoopDataPanel,
}
