import { Conversation, ConversationContent, ConversationScrollButton } from '@/components/ai-elements/conversation'
import { Loader } from '@/components/ai-elements/loader'
import {
  PromptInput,
  PromptInputButton,
  PromptInputModelSelect,
  PromptInputModelSelectContent,
  PromptInputModelSelectItem,
  PromptInputModelSelectTrigger,
  PromptInputModelSelectValue,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputToolbar,
  PromptInputTools,
} from '@/components/ai-elements/prompt-input'
import { Source, Sources, SourcesContent, SourcesTrigger } from '@/components/ai-elements/sources'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { DatabaseIcon, EyeOffIcon, SquarePenIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type SyntheticEvent } from 'react'
import type { PanelImperativeHandle } from 'react-resizable-panels'

import { useQuery } from '@tanstack/react-query'
import { SqlResultTable, type SqlResultData } from '@/components/sql-result-table'
import { useConversationIdFromUrl } from './hooks/useConversationIdFromUrl'
import { Part } from './Part'

interface ModelConfig {
  id: string
  name: string
}

interface RemoteConfig {
  models: ModelConfig[]
  canOverrideSystemPrompt: boolean
  defaultSystemPrompt: string | null
}

interface CreateConversationResponse {
  id: string
}

interface ChatHistoryResponse {
  messages: UIMessage[]
}

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

async function getConfig() {
  const res = await fetch('/api/configure')
  return (await res.json()) as RemoteConfig
}

async function createConversation() {
  const res = await fetch('/api/chat', {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error('Failed to create conversation')
  }
  return (await res.json()) as CreateConversationResponse
}

async function getConversationMessages(conversationId: string) {
  const res = await fetch(`/api/chat/${conversationId}`)
  if (!res.ok) {
    throw new Error('Failed to load conversation')
  }
  return (await res.json()) as ChatHistoryResponse
}

const Chat = () => {
  const [input, setInput] = useState('')
  const [model, setModel] = useState<string>('')
  const [systemPrompt, setSystemPrompt] = useState<string>('')
  const [systemPromptDraft, setSystemPromptDraft] = useState<string>('')
  const [isPromptDialogOpen, setIsPromptDialogOpen] = useState(false)
  const [pendingMessage, setPendingMessage] = useState<string | null>(null)
  const [sqlResult, setSqlResult] = useState<SqlResultData | null>(null)
  const [isSqlPanelOpen, setIsSqlPanelOpen] = useState(false)
  const dataPanelRef = useRef<PanelImperativeHandle | null>(null)
  const [conversationId, setConversationId] = useConversationIdFromUrl()
  const chatApi = conversationId ? `/api/chat/${conversationId}` : '/api/chat/__pending__'
  const transport = useMemo(() => new DefaultChatTransport({ api: chatApi }), [chatApi])
  const { messages, sendMessage, status, setMessages, regenerate, error } = useChat({
    id: conversationId ?? undefined,
    transport,
    onData: (part) => {
      const dataPart = part as DataPartEvent
      if (dataPart.type !== 'data-sql-result' || !isSqlResultData(dataPart.data)) {
        return
      }

      setSqlResult(dataPart.data)
    },
    onFinish: ({ isAbort, isDisconnect, isError }) => {
      if (conversationId && !isAbort && !isDisconnect && !isError) {
        window.dispatchEvent(new Event('conversations-changed'))
      }
    },
  })
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const configQuery = useQuery({
    queryFn: getConfig,
    queryKey: ['chat-config'],
  })

  useEffect(() => {
    if (configQuery.data?.models[0]) {
      setModel(configQuery.data.models[0].id)
    }
    if (configQuery.data?.canOverrideSystemPrompt) {
      const defaultPrompt = configQuery.data.defaultSystemPrompt ?? ''
      setSystemPrompt(defaultPrompt)
      setSystemPromptDraft(defaultPrompt)
    }
  }, [configQuery.data])

  useEffect(() => {
    if (isPromptDialogOpen) {
      setSystemPromptDraft(systemPrompt)
    }
  }, [isPromptDialogOpen, systemPrompt])

  useEffect(() => {
    let disposed = false

    async function loadConversation() {
      if (!conversationId) {
        setMessages([])
        setSqlResult(null)
        setIsSqlPanelOpen(false)
        dataPanelRef.current?.collapse()
        return
      }

      try {
        const response = await getConversationMessages(conversationId)
        if (!disposed) {
          const latestSqlResult = getLatestSqlResult(response.messages)
          setMessages(response.messages)
          setSqlResult(latestSqlResult)
          setIsSqlPanelOpen(false)
          dataPanelRef.current?.collapse()
        }
      } catch (error: unknown) {
        console.error('Error loading conversation:', error)
        if (!disposed) {
          setMessages([])
          setSqlResult(null)
          setIsSqlPanelOpen(false)
          dataPanelRef.current?.collapse()
        }
      }
    }

    loadConversation().catch((error: unknown) => {
      console.error('Error loading conversation:', error)
    })
    textareaRef.current?.focus()

    return () => {
      disposed = true
    }
  }, [conversationId, setMessages])

  useEffect(() => {
    setSqlResult(null)
    setIsSqlPanelOpen(false)
    dataPanelRef.current?.collapse()
  }, [conversationId])

  useEffect(() => {
    const panel = dataPanelRef.current
    if (!panel) {
      return
    }

    if (isSqlPanelOpen && sqlResult) {
      panel.expand()
      if (panel.getSize().asPercentage < 20) {
        panel.resize(40)
      }
      return
    }

    panel.collapse()
  }, [isSqlPanelOpen, sqlResult])

  const sendTextMessage = (text: string) => {
    sendMessage(
      { text },
      {
        body: {
          model,
          systemPrompt: configQuery.data?.canOverrideSystemPrompt ? systemPrompt : undefined,
        },
      },
    ).catch((error: unknown) => {
      console.error('Error sending message:', error)
    })
  }

  useEffect(() => {
    if (!conversationId || !pendingMessage) {
      return
    }

    sendTextMessage(pendingMessage)
    setPendingMessage(null)
  }, [conversationId, pendingMessage, model, systemPrompt, configQuery.data])

  const handleSubmit = (e: SyntheticEvent) => {
    e.preventDefault()
    if (input.trim()) {
      const submittedText = input
      setInput('')

      if (!conversationId) {
        createConversation()
          .then((response) => {
            setConversationId(response.id)
            setPendingMessage(submittedText)
            window.dispatchEvent(new Event('conversations-changed'))
          })
          .catch((error: unknown) => {
            console.error('Error creating conversation:', error)
          })
        return
      }

      sendTextMessage(submittedText)
    }
  }

  function regen(messageId: string) {
    regenerate({ messageId }).catch((error: unknown) => {
      console.error('Error regenerating message:', error)
    })
  }

  const showSqlPanel = isSqlPanelOpen && sqlResult !== null
  const hasSqlResult = sqlResult !== null
  const chatPane = (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation className="h-full">
        <ConversationContent>
          {messages.map((message) => (
            <div key={message.id}>
              {message.parts.filter((part) => part.type === 'source-url').length > 0 && (
                <Sources>
                  <SourcesTrigger count={message.parts.filter((part) => part.type === 'source-url').length} />
                  {message.parts
                    .filter((part) => part.type === 'source-url')
                    .map((part, i) => (
                      <SourcesContent key={`${message.id}-${i}`}>
                        <Source key={`${message.id}-${i}`} href={part.url} title={part.url} />
                      </SourcesContent>
                    ))}
                </Sources>
              )}
              {message.parts.map((part, i) => (
                <Part
                  key={`${message.id}-${i}`}
                  part={part}
                  message={message}
                  status={status}
                  index={i}
                  regen={regen}
                  lastMessage={message.id === messages.at(-1)?.id}
                />
              ))}
            </div>
          ))}
          {status === 'submitted' && <Loader />}
          {status === 'error' && error && (
            <div className="px-4 py-3 mx-4 my-2 bg-destructive/10 border border-destructive/20 rounded-md text-destructive text-sm">
              <strong>Error:</strong> {error.message}
            </div>
          )}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>

      <div className="sticky bottom-0 p-3">
        <PromptInput onSubmit={handleSubmit}>
          <PromptInputTextarea
            ref={textareaRef}
            onChange={(e) => {
              setInput(e.target.value)
            }}
            value={input}
            autoFocus={true}
          />
          <PromptInputToolbar>
            <PromptInputTools>
              {configQuery.data?.canOverrideSystemPrompt && (
                <Dialog open={isPromptDialogOpen} onOpenChange={setIsPromptDialogOpen}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <DialogTrigger asChild>
                        <PromptInputButton variant="outline" aria-label="Edit system prompt">
                          <SquarePenIcon className="size-4" />
                        </PromptInputButton>
                      </DialogTrigger>
                    </TooltipTrigger>
                    <TooltipContent>Edit system prompt</TooltipContent>
                  </Tooltip>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>System Prompt</DialogTitle>
                      <DialogDescription>Changes apply to new messages in this chat session.</DialogDescription>
                    </DialogHeader>
                    <Textarea
                      value={systemPromptDraft}
                      onChange={(e) => {
                        setSystemPromptDraft(e.target.value)
                      }}
                      placeholder="Override system prompt"
                      className="min-h-36"
                    />
                    <DialogFooter>
                      <DialogClose asChild>
                        <Button variant="outline">Cancel</Button>
                      </DialogClose>
                      <Button
                        type="button"
                        onClick={() => {
                          setSystemPrompt(systemPromptDraft)
                          setIsPromptDialogOpen(false)
                        }}
                      >
                        Save
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              )}
              {configQuery.data && model && (
                <PromptInputModelSelect
                  onValueChange={(value) => {
                    setModel(value)
                  }}
                  value={model}
                >
                  <PromptInputModelSelectTrigger>
                    <PromptInputModelSelectValue />
                  </PromptInputModelSelectTrigger>
                  <PromptInputModelSelectContent>
                    {configQuery.data.models.map((entry) => (
                      <PromptInputModelSelectItem key={entry.id} value={entry.id}>
                        {entry.name}
                      </PromptInputModelSelectItem>
                    ))}
                  </PromptInputModelSelectContent>
                </PromptInputModelSelect>
              )}
              {sqlResult && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <PromptInputButton
                      type="button"
                      variant={showSqlPanel ? 'outline' : 'default'}
                      aria-label={showSqlPanel ? 'Hide data' : 'Show data'}
                      className={
                        showSqlPanel
                          ? 'shrink-0'
                          : 'shrink-0 animate-pulse ring-2 ring-primary/40 shadow-md shadow-primary/30'
                      }
                      onClick={() => {
                        setIsSqlPanelOpen((open) => !open)
                      }}
                    >
                      {showSqlPanel ? <EyeOffIcon className="size-4" /> : <DatabaseIcon className="size-4" />}
                    </PromptInputButton>
                  </TooltipTrigger>
                  <TooltipContent>{showSqlPanel ? 'Hide data' : 'Show data'}</TooltipContent>
                </Tooltip>
              )}
            </PromptInputTools>
            <PromptInputSubmit disabled={!input} status={status} />
          </PromptInputToolbar>
        </PromptInput>
      </div>
    </div>
  )

  if (!hasSqlResult) {
    return chatPane
  }

  return (
    <ResizablePanelGroup orientation="vertical" className="h-full min-h-0">
      <ResizablePanel panelRef={dataPanelRef} defaultSize={40} minSize={20} collapsedSize={0} collapsible>
        {showSqlPanel ? (
          <section className="flex h-full min-h-0 flex-col border-b bg-linear-to-b from-background to-muted/20">
            <div className="flex items-start justify-between border-b p-4 gap-3 bg-background/80">
              <div>
                <h2 className="font-semibold">Query result</h2>
                <p className="text-sm text-muted-foreground">
                  {`${sqlResult.row_count} rows x ${sqlResult.column_count} columns`}
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setIsSqlPanelOpen(false)
                }}
              >
                Hide data
              </Button>
            </div>
            <div className="px-4 pb-4 pt-3 overflow-auto min-h-0">
              <div className="rounded-xl border bg-card/80 shadow-sm overflow-hidden">
                <div className="border-b px-3 py-2">
                  <pre className="text-xs text-muted-foreground whitespace-pre-wrap">{sqlResult.sql_query}</pre>
                </div>
                <div className="p-2">
                  <SqlResultTable result={sqlResult} />
                </div>
              </div>
            </div>
          </section>
        ) : null}
      </ResizablePanel>
      <ResizableHandle
        withHandle={showSqlPanel}
        className={showSqlPanel ? 'bg-border/80' : 'opacity-0 pointer-events-none'}
      />
      <ResizablePanel defaultSize={60} minSize={35}>
        {chatPane}
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}

export default Chat
