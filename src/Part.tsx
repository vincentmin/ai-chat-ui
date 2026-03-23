import { Message, MessageContent } from '@/components/ai-elements/message'

import { Actions, Action } from '@/components/ai-elements/actions'
import { Response } from '@/components/ai-elements/response'
import { formatMailboxSenderLabel, parseMailboxMessage } from '@/lib/message-display'
import { cn } from '@/lib/utils'
import { CopyIcon, RefreshCcwIcon } from 'lucide-react'
import type { UIDataTypes, UIMessagePart, UITools, UIMessage } from 'ai'
import { isToolPart, ToolPart } from './Tool'

interface PartProps {
  part: UIMessagePart<UIDataTypes, UITools>
  message: UIMessage
  regen: (id: string) => void
  addToolApprovalResponse: (response: { id: string; approved: boolean }) => void
  index: number
}

function copy(text: string) {
  navigator.clipboard.writeText(text).catch((error: unknown) => {
    console.error('Error copying text:', error)
  })
}

export function Part({ part, message, regen, addToolApprovalResponse, index }: PartProps) {
  const handleRetry = () => {
    regen(message.id)
  }

  const handleCopy = (text: string) => {
    copy(text)
  }

  const handleToolApproval = (approvalId: string | undefined, approved: boolean) => {
    if (!approvalId) {
      return
    }
    addToolApprovalResponse({ id: approvalId, approved })
  }

  if (part.type === 'text') {
    const parsedMailboxMessage = parseMailboxMessage(part.text)
    const isMailboxMessage = parsedMailboxMessage.isMailbox && parsedMailboxMessage.sender !== null
    const bubbleFrom = isMailboxMessage && parsedMailboxMessage.sender !== 'user' ? 'assistant' : message.role
    const senderLabel = parsedMailboxMessage.sender ? formatMailboxSenderLabel(parsedMailboxMessage.sender) : null

    return (
      <div className="py-4">
        <Message from={bubbleFrom}>
          <div className="flex flex-col gap-1">
            {isMailboxMessage && senderLabel && (
              <div
                className={cn(
                  'px-1 text-[11px] font-medium leading-none text-muted-foreground',
                  bubbleFrom === 'user' ? 'text-right' : 'text-left',
                )}
              >
                {senderLabel}
              </div>
            )}
            <MessageContent>
              {message.role === 'assistant' && !isMailboxMessage ? (
                <Response>{parsedMailboxMessage.body}</Response>
              ) : (
                <p className="whitespace-pre-wrap">{parsedMailboxMessage.body}</p>
              )}
            </MessageContent>
          </div>
        </Message>
        {message.role === 'assistant' && index === message.parts.length - 1 && (
          <Actions className="mt-1">
            <Action onClick={handleRetry} label="Retry">
              <RefreshCcwIcon className="size-3" />
            </Action>
            <Action
              onClick={() => {
                handleCopy(parsedMailboxMessage.body)
              }}
              label="Copy"
            >
              <CopyIcon className="size-3" />
            </Action>
          </Actions>
        )}
      </div>
    )
  } else if (isToolPart(part)) {
    return <ToolPart part={part} onApproval={handleToolApproval} />
  }

  return null
}
