import type { UIMessage } from 'ai'
import type { ComponentType } from 'react'

export interface AgentTopPanelController<TData> {
  data: TData | null
  hasData: boolean
  showTopPanel: boolean
  onDataPart: (part: unknown) => void
  hydrateFromMessages: (messages: UIMessage[]) => void
  toggleTopPanel: () => void
  closeTopPanel: () => void
  resetTopPanel: () => void
}

export interface AgentTopPanelToggleButtonProps {
  hasData: boolean
  showTopPanel: boolean
  onToggle: () => void
}

export interface AgentTopPanelProps<TData> {
  data: TData
  onClose: () => void
}

export interface AgentTopPanelPlugin<TData> {
  useTopPanelController: () => AgentTopPanelController<TData>
  ToggleButton: ComponentType<AgentTopPanelToggleButtonProps>
  TopPanel: ComponentType<AgentTopPanelProps<TData>>
}
