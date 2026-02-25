import { PromptInputButton } from '@/components/ai-elements/prompt-input'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SqlResultTable, type SqlResultData } from '@/components/sql-result-table'
import type { UIMessage } from 'ai'
import { DatabaseIcon, EyeOffIcon } from 'lucide-react'
import { useCallback, useState } from 'react'

interface DataPartEvent {
  type: string
  data: unknown
}

function isSqlResultData(value: unknown): value is SqlResultData {
  if (typeof value !== 'object' || value === null) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return typeof candidate.sql_query === 'string' && Array.isArray(candidate.columns) && Array.isArray(candidate.rows)
}

function getLatestSqlResult(messages: UIMessage[]): SqlResultData | null {
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex]
    for (let partIndex = message.parts.length - 1; partIndex >= 0; partIndex -= 1) {
      const part = message.parts[partIndex] as { type?: unknown; data?: unknown }
      if (part.type === 'data-sql-result' && isSqlResultData(part.data)) {
        return part.data
      }
    }
  }

  return null
}

export function useSqlDataPanel() {
  const [data, setData] = useState<SqlResultData | null>(null)
  const [isOpen, setIsOpen] = useState(false)

  const onDataPart = useCallback((part: unknown) => {
    const dataPart = part as DataPartEvent
    if (dataPart.type !== 'data-sql-result' || !isSqlResultData(dataPart.data)) {
      return
    }

    setData(dataPart.data)
  }, [])

  const hydrateFromMessages = useCallback((messages: UIMessage[]) => {
    setData(getLatestSqlResult(messages))
    setIsOpen(false)
  }, [])

  const reset = useCallback(() => {
    setData(null)
    setIsOpen(false)
  }, [])

  const toggle = useCallback(() => {
    setIsOpen((open) => !open)
  }, [])

  const close = useCallback(() => {
    setIsOpen(false)
  }, [])

  return {
    data,
    hasData: data !== null,
    isOpen,
    showTopPanel: isOpen && data !== null,
    onDataPart,
    hydrateFromMessages,
    toggle,
    close,
    reset,
  }
}

interface SqlDataToggleButtonProps {
  hasData: boolean
  isOpen: boolean
  onToggle: () => void
}

export function SqlDataToggleButton({ hasData, isOpen, onToggle }: SqlDataToggleButtonProps) {
  if (!hasData) {
    return null
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <PromptInputButton
          type="button"
          variant={isOpen ? 'outline' : 'default'}
          aria-label={isOpen ? 'Hide data' : 'Show data'}
          className={isOpen ? 'shrink-0' : 'shrink-0 animate-pulse ring-2 ring-primary/40 shadow-md shadow-primary/30'}
          onClick={onToggle}
        >
          {isOpen ? <EyeOffIcon className="size-4" /> : <DatabaseIcon className="size-4" />}
        </PromptInputButton>
      </TooltipTrigger>
      <TooltipContent>{isOpen ? 'Hide data' : 'Show data'}</TooltipContent>
    </Tooltip>
  )
}

interface SqlDataTopPanelProps {
  data: SqlResultData
  onClose: () => void
}

export function SqlDataTopPanel({ data, onClose }: SqlDataTopPanelProps) {
  return (
    <section className="flex h-full min-h-0 flex-col border-b bg-linear-to-b from-background to-muted/20">
      <div className="flex items-start justify-between border-b p-4 gap-3 bg-background/80">
        <div>
          <h2 className="font-semibold">Query result</h2>
          <p className="text-sm text-muted-foreground">{`${data.row_count} rows x ${data.column_count} columns`}</p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          Hide data
        </Button>
      </div>
      <div className="px-4 pb-4 pt-3 overflow-auto min-h-0">
        <div className="rounded-xl border bg-card/80 shadow-sm overflow-hidden">
          <div className="border-b px-3 py-2">
            <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{data.sql_query}</pre>
          </div>
          <div className="p-2">
            <SqlResultTable result={data} />
          </div>
        </div>
      </div>
    </section>
  )
}
