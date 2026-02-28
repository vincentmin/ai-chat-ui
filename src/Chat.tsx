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
import { SquarePenIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AgentChatDataPanelLayout } from '@/components/agent-chat-data-panel-layout'
import type { AgentDataPanelPlugin } from '@/features/agent-data-panel-plugin'
import { useConversationChatState } from './hooks/useConversationChatState'
import { Part } from './Part'
import { getConfig } from '@/lib/api'
import { useChatSubmit } from '@/hooks/useChatSubmit'

interface ChatProps<TDataPanelData> {
  apiBasePath: string
  conversationId: string | null
  setConversationId: (id: string | null) => void
  dataPanelPlugin: AgentDataPanelPlugin<TDataPanelData>
}

const Chat = <TDataPanelData,>({
  apiBasePath,
  conversationId,
  setConversationId,
  dataPanelPlugin,
}: ChatProps<TDataPanelData>) => {
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
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
  const systemPrompt = systemPromptOverride ?? configQuery.data?.defaultSystemPrompt ?? ''

  useEffect(() => {
    if (isPromptDialogOpen) {
      setSystemPromptDraft(systemPrompt)
    }
  }, [isPromptDialogOpen, systemPrompt])

  useEffect(() => {
    if (!conversationId) {
      resetDataPanel()
    }
  }, [conversationId, resetDataPanel])

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
    configQueryData: configQuery.data,
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
                  addToolApprovalResponse={handleToolApprovalResponse}
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
                <PromptInputModelSelect
                  onValueChange={(value) => {
                    setSelectedModel(value)
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
              <DataPanelToggleButton
                hasData={hasDataPanelData}
                showDataPanel={showDataPanel}
                onToggle={toggleDataPanel}
              />
            </PromptInputTools>
            <PromptInputSubmit disabled={!input} status={status} />
          </PromptInputToolbar>
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
