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
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { SquarePenIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type SyntheticEvent } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AgentChatTopPanelLayout } from '@/components/agent-chat-top-panel-layout'
import type { AgentTopPanelPlugin } from '@/features/agent-top-panel-plugin'
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

async function getConfig(apiBasePath: string) {
  const res = await fetch(`${apiBasePath}/configure`)
  return (await res.json()) as RemoteConfig
}

async function createConversation(apiBasePath: string) {
  const res = await fetch(`${apiBasePath}/chat`, {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error('Failed to create conversation')
  }
  return (await res.json()) as CreateConversationResponse
}

async function getConversationMessages(apiBasePath: string, conversationId: string) {
  const res = await fetch(`${apiBasePath}/chat/${conversationId}`)
  if (!res.ok) {
    throw new Error('Failed to load conversation')
  }
  return (await res.json()) as ChatHistoryResponse
}

interface ChatProps<TTopPanelData> {
  apiBasePath: string
  conversationBasePath: string
  topPanelPlugin: AgentTopPanelPlugin<TTopPanelData>
}

const Chat = <TTopPanelData,>({ apiBasePath, conversationBasePath, topPanelPlugin }: ChatProps<TTopPanelData>) => {
  const [input, setInput] = useState('')
  const [model, setModel] = useState<string>('')
  const [systemPrompt, setSystemPrompt] = useState<string>('')
  const [systemPromptDraft, setSystemPromptDraft] = useState<string>('')
  const [isPromptDialogOpen, setIsPromptDialogOpen] = useState(false)
  const [pendingMessage, setPendingMessage] = useState<string | null>(null)
  const TopPanelToggleButton = topPanelPlugin.ToggleButton
  const TopPanelView = topPanelPlugin.TopPanel
  const {
    data: topPanelData,
    hasData: hasTopPanelData,
    showTopPanel,
    onDataPart,
    hydrateFromMessages,
    toggleTopPanel,
    closeTopPanel,
    resetTopPanel,
  } = topPanelPlugin.useTopPanelController()
  const [conversationId, setConversationId] = useConversationIdFromUrl(conversationBasePath)
  const chatApi = conversationId ? `${apiBasePath}/chat/${conversationId}` : `${apiBasePath}/chat/__pending__`
  const transport = useMemo(() => new DefaultChatTransport({ api: chatApi }), [chatApi])
  const { messages, sendMessage, status, setMessages, regenerate, error } = useChat({
    id: conversationId ?? undefined,
    transport,
    onData: onDataPart,
    onFinish: ({ isAbort, isDisconnect, isError }) => {
      if (conversationId && !isAbort && !isDisconnect && !isError) {
        window.dispatchEvent(new Event('conversations-changed'))
      }
    },
  })
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const configQuery = useQuery({
    queryFn: () => getConfig(apiBasePath),
    queryKey: ['chat-config', apiBasePath],
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
        resetTopPanel()
        return
      }

      try {
        const response = await getConversationMessages(apiBasePath, conversationId)
        if (!disposed) {
          setMessages(response.messages)
          hydrateFromMessages(response.messages)
        }
      } catch (error: unknown) {
        console.error('Error loading conversation:', error)
        if (!disposed) {
          setMessages([])
          resetTopPanel()
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
  }, [apiBasePath, conversationId, hydrateFromMessages, resetTopPanel, setMessages])

  useEffect(() => {
    resetTopPanel()
  }, [conversationId, resetTopPanel])

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
        createConversation(apiBasePath)
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
              <TopPanelToggleButton hasData={hasTopPanelData} showTopPanel={showTopPanel} onToggle={toggleTopPanel} />
            </PromptInputTools>
            <PromptInputSubmit disabled={!input} status={status} />
          </PromptInputToolbar>
        </PromptInput>
      </div>
    </div>
  )

  return (
    <AgentChatTopPanelLayout
      hasTopPanelData={hasTopPanelData}
      showTopPanel={showTopPanel}
      chatPane={chatPane}
      topPanel={topPanelData ? <TopPanelView data={topPanelData} onClose={closeTopPanel} /> : null}
    />
  )
}

export default Chat
