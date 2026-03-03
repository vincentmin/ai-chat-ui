import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation'
import { Loader } from '@/components/ai-elements/loader'
import {
  PromptInput,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
} from '@/components/ai-elements/prompt-input'
import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from '@/components/ai-elements/model-selector'
import { Suggestion, Suggestions } from '@/components/ai-elements/suggestion'
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
import { CheckIcon, ChevronsUpDownIcon, MessageSquareIcon, SquarePenIcon } from 'lucide-react'
import { useEffect, useRef, useState, type SyntheticEvent } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AgentChatDataPanelLayout } from '@/components/agent-chat-data-panel-layout'
import type { AgentDataPanelPlugin } from '@/features/agent-data-panel-plugin'
import { useConversationChatState } from './hooks/useConversationChatState'
import { Message } from './Message'
import { getConfig } from '@/lib/api'
import { useChatSubmit } from '@/hooks/useChatSubmit'

interface ChatProps<TDataPanelData> {
  apiBasePath: string
  conversationId: string | null
  setConversationId: (id: string | null) => void
  dataPanelPlugin: AgentDataPanelPlugin<TDataPanelData>
  quickSuggestions?: string[]
}

const DEFAULT_QUICK_SUGGESTIONS = ['What can you do?', 'Explain your available tools in detail.']

const Chat = <TDataPanelData,>({
  apiBasePath,
  conversationId,
  setConversationId,
  dataPanelPlugin,
  quickSuggestions = DEFAULT_QUICK_SUGGESTIONS,
}: ChatProps<TDataPanelData>) => {
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [isModelSelectorOpen, setIsModelSelectorOpen] = useState(false)
  const [systemPromptOverride, setSystemPromptOverride] = useState<string | null>(null)
  const [systemPromptDraft, setSystemPromptDraft] = useState<string>('')
  const [isPromptDialogOpen, setIsPromptDialogOpen] = useState(false)
  const DataPanelToggleButton = dataPanelPlugin.ToggleButton
  const DataPanelView = dataPanelPlugin.DataPanel
  const {
    data: dataPanelData,
    hasData: hasDataPanelData,
    showDataPanel,
    onDataPart,
    hydrateFromMessages,
    toggleDataPanel,
    closeDataPanel,
    resetDataPanel,
  } = dataPanelPlugin.useDataPanelController()

  const { messages, sendMessage, status, regenerate, error, addToolApprovalResponse } = useConversationChatState({
    apiBasePath,
    conversationId,
    onData: onDataPart,
    hydrateFromMessages,
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
  const model = selectedModel ?? configQuery.data?.models[0]?.id ?? ''
  const modelName = configQuery.data?.models.find((entry) => entry.id === model)?.name ?? model
  const systemPrompt = systemPromptOverride ?? configQuery.data?.defaultSystemPrompt ?? ''

  useEffect(() => {
    if (isPromptDialogOpen) {
      setSystemPromptDraft(systemPrompt)
    }
  }, [isPromptDialogOpen, systemPrompt])

  // Focus the textarea when the active conversation changes
  useEffect(() => {
    textareaRef.current?.focus()
  }, [conversationId])

  useEffect(() => {
    resetDataPanel()
  }, [conversationId, resetDataPanel])

  const { input, setInput, handleSubmit } = useChatSubmit({
    apiBasePath,
    conversationId,
    setConversationId: (id) => {
      setConversationId(id)
    },
    model,
    systemPrompt,
    canOverrideSystemPrompt: configQuery.data?.canOverrideSystemPrompt,
    sendMessage,
  })

  function regen(messageId: string) {
    regenerate({ messageId }).catch((error: unknown) => {
      console.error('Error regenerating message:', error)
    })
  }

  function handleToolApprovalResponse(response: { id: string; approved: boolean }) {
    Promise.resolve(addToolApprovalResponse(response)).catch((error: unknown) => {
      console.error('Error sending tool approval response:', error)
    })
  }

  const chatPane = (
    <div className="flex h-full min-h-0 flex-col">
      <Conversation className="h-full">
        <ConversationContent>
          {messages.length === 0 && (
            <ConversationEmptyState
              description="Ask a question to begin."
              icon={<MessageSquareIcon className="size-8 text-primary/80" />}
              className="rounded-xl border border-dashed bg-linear-to-b from-muted/45 to-background"
              title="Start a conversation"
            >
              <Suggestions className="mt-3 w-full max-w-2xl">
                {quickSuggestions.map((suggestion: string) => (
                  <Suggestion
                    className="rounded-lg border-muted-foreground/25 bg-background/70 text-xs hover:bg-accent"
                    key={suggestion}
                    onClick={() => {
                      setInput(suggestion)
                      textareaRef.current?.focus()
                    }}
                    suggestion={suggestion}
                    size="sm"
                    variant="outline"
                  />
                ))}
              </Suggestions>
            </ConversationEmptyState>
          )}
          {messages.map((message) => {
            return (
              <Message
                key={message.id}
                message={message}
                status={status}
                regen={regen}
                addToolApprovalResponse={handleToolApprovalResponse}
                lastMessage={message.id === messages.at(-1)?.id}
              />
            )
          })}
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
        <PromptInput
          onSubmit={(_message, event) => {
            handleSubmit(event as unknown as SyntheticEvent)
          }}
        >
          <PromptInputTextarea
            ref={textareaRef}
            onChange={(e) => {
              setInput(e.target.value)
            }}
            value={input}
            autoFocus={true}
          />
          <PromptInputFooter>
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
                          setSystemPromptOverride(systemPromptDraft)
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
                <ModelSelector open={isModelSelectorOpen} onOpenChange={setIsModelSelectorOpen}>
                  <ModelSelectorTrigger asChild>
                    <PromptInputButton className="min-w-44 justify-between border border-transparent px-2.5 hover:border-border">
                      <span className="truncate text-left">{modelName}</span>
                      <ChevronsUpDownIcon className="size-4 text-muted-foreground" />
                    </PromptInputButton>
                  </ModelSelectorTrigger>
                  <ModelSelectorContent className="sm:max-w-md">
                    <ModelSelectorInput placeholder="Search models..." />
                    <ModelSelectorList>
                      <ModelSelectorEmpty>No models found.</ModelSelectorEmpty>
                      <ModelSelectorGroup>
                        {configQuery.data.models.map((entry) => {
                          const isSelected = entry.id === model

                          return (
                            <ModelSelectorItem
                              key={entry.id}
                              onSelect={(value: string) => {
                                setSelectedModel(value)
                                setIsModelSelectorOpen(false)
                              }}
                              value={entry.id}
                            >
                              <ModelSelectorName>{entry.name}</ModelSelectorName>
                              {isSelected && <CheckIcon className="size-4" />}
                            </ModelSelectorItem>
                          )
                        })}
                      </ModelSelectorGroup>
                    </ModelSelectorList>
                  </ModelSelectorContent>
                </ModelSelector>
              )}
              <DataPanelToggleButton
                hasData={hasDataPanelData}
                showDataPanel={showDataPanel}
                onToggle={toggleDataPanel}
              />
            </PromptInputTools>
            <PromptInputSubmit disabled={!input} status={status} />
          </PromptInputFooter>
        </PromptInput>
      </div>
    </div>
  )

  return (
    <AgentChatDataPanelLayout
      hasDataPanelData={hasDataPanelData}
      showDataPanel={showDataPanel}
      dataPanelPosition={dataPanelPlugin.dataPanelPosition ?? 'top'}
      chatPane={chatPane}
      dataPanel={dataPanelData ? <DataPanelView data={dataPanelData} onClose={closeDataPanel} /> : null}
    />
  )
}

export default Chat
