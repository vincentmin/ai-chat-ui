import { CodeIcon, DownloadIcon, GlobeIcon, ImagePlusIcon, WrenchIcon } from 'lucide-react'
import type { ComponentType, ReactNode } from 'react'

const iconMap: Record<string, ComponentType<{ className?: string }> | undefined> = {
  web_search: GlobeIcon,
  web_fetch: DownloadIcon,
  code_execution: CodeIcon,
  image_generation: ImagePlusIcon,
}

export function getToolIcon(toolId: string, className = 'size-4'): ReactNode {
  const Icon = iconMap[toolId]
  return Icon ? <Icon className={className} /> : <WrenchIcon className={className} />
}
