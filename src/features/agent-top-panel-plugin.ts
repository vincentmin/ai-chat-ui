import type { UIMessage } from 'ai'
import type { ComponentType } from 'react'

export type DataPanelPosition = 'top' | 'right' | 'bottom' | 'left'

export interface AgentDataPanelController<TData> {
  data: TData | null
  hasData: boolean
  showDataPanel: boolean
  onDataPart: (part: unknown) => void
  hydrateFromMessages: (messages: UIMessage[]) => void
  toggleDataPanel: () => void
  closeDataPanel: () => void
  resetDataPanel: () => void
}

export interface AgentDataPanelToggleButtonProps {
  hasData: boolean
  showDataPanel: boolean
  onToggle: () => void
}

export interface AgentDataPanelProps<TData> {
  data: TData
  onClose: () => void
}

export interface AgentDataPanelPlugin<TData> {
  useDataPanelController: () => AgentDataPanelController<TData>
  ToggleButton: ComponentType<AgentDataPanelToggleButtonProps>
  DataPanel: ComponentType<AgentDataPanelProps<TData>>
  dataPanelPosition?: DataPanelPosition
}
