import { PromptInputButton } from '@/components/ai-elements/prompt-input'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type {
  AgentDataPanelPlugin,
  AgentDataPanelProps,
  AgentDataPanelToggleButtonProps,
} from '@/features/agent-data-panel-plugin'
import type { UIMessage } from 'ai'
import { BookOpenIcon, EyeOffIcon } from 'lucide-react'
import { useCallback, useState } from 'react'

export interface ArxivPaperData {
  arxiv_id: string
  title: string
  url: string
  pdf_url: string
}

interface DataPartEvent {
  type: string
  data: unknown
}

function isArxivPaperData(value: unknown): value is ArxivPaperData {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.arxiv_id === 'string' &&
    typeof candidate.title === 'string' &&
    typeof candidate.url === 'string' &&
    typeof candidate.pdf_url === 'string'
  )
}

function getLatestPaper(messages: UIMessage[]): ArxivPaperData | null {
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex]
    for (let partIndex = message.parts.length - 1; partIndex >= 0; partIndex -= 1) {
      const part = message.parts[partIndex] as { type?: unknown; data?: unknown }
      if (part.type === 'data-arxiv-paper' && isArxivPaperData(part.data)) {
        return part.data
      }
    }
  }

  return null
}

function useArxivDataPanelController() {
  const [data, setData] = useState<ArxivPaperData | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  const onDataPart = useCallback((part: unknown) => {
    const dataPart = part as DataPartEvent
    if (dataPart.type !== 'data-arxiv-paper' || !isArxivPaperData(dataPart.data)) {
      return
    }

    setData(dataPart.data)
  }, [])

  const hydrateFromMessages = useCallback((messages: UIMessage[]) => {
    setData(getLatestPaper(messages))
    setIsOpen(false)
  }, [])

  const toggleDataPanel = useCallback(() => {
    setIsOpen((open) => !open)
  }, [])

  const closeDataPanel = useCallback(() => {
    setIsOpen(false)
  }, [])

  const resetDataPanel = useCallback(() => {
    setData(null)
    setIsOpen(false)
  }, [])

  return {
    data,
    hasData: data !== null,
    showDataPanel: isOpen && data !== null,
    onDataPart,
    hydrateFromMessages,
    toggleDataPanel,
    closeDataPanel,
    resetDataPanel,
  }
}

function ArxivDataPanelToggleButton({ hasData, showDataPanel, onToggle }: AgentDataPanelToggleButtonProps) {
  if (!hasData) {
    return null
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <PromptInputButton
          type="button"
          variant={showDataPanel ? 'outline' : 'default'}
          aria-label={showDataPanel ? 'Hide paper preview' : 'Show paper preview'}
          className={
            showDataPanel ? 'shrink-0' : 'shrink-0 animate-pulse ring-2 ring-primary/40 shadow-md shadow-primary/30'
          }
          onClick={onToggle}
        >
          {showDataPanel ? <EyeOffIcon className="size-4" /> : <BookOpenIcon className="size-4" />}
        </PromptInputButton>
      </TooltipTrigger>
      <TooltipContent>{showDataPanel ? 'Hide paper preview' : 'Show paper preview'}</TooltipContent>
    </Tooltip>
  )
}

function ArxivDataPanelView({ data, onClose }: AgentDataPanelProps<ArxivPaperData>) {
  return (
    <section className="flex h-full min-h-0 flex-col border-b bg-linear-to-b from-background to-muted/20">
      <div className="flex items-start justify-between gap-3 border-b bg-background/80 p-4">
        <div className="min-w-0">
          <h2 className="font-semibold">Paper preview</h2>
          <p className="truncate text-sm text-muted-foreground">{data.title}</p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Hide data
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-4 pb-4 pt-3">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded-md border bg-muted/40 px-2 py-1 font-medium">Arxiv ID {data.arxiv_id}</span>
          <a
            className="underline underline-offset-2 hover:text-foreground"
            href={data.url}
            rel="noreferrer"
            target="_blank"
          >
            Open on arXiv
          </a>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden rounded-xl border bg-card/80 shadow-sm">
          <iframe className="size-full" src={data.pdf_url} title={`Arxiv paper ${data.arxiv_id}`}>
            <p className="p-4 text-sm text-muted-foreground">
              PDF preview unavailable.{' '}
              <a className="underline underline-offset-2 hover:text-foreground" href={data.pdf_url}>
                Open the PDF directly.
              </a>
            </p>
          </iframe>
        </div>
      </div>
    </section>
  )
}

export const arxivDataPanelPlugin: AgentDataPanelPlugin<ArxivPaperData> = {
  useDataPanelController: useArxivDataPanelController,
  ToggleButton: ArxivDataPanelToggleButton,
  DataPanel: ArxivDataPanelView,
  dataPanelPosition: 'right',
}
