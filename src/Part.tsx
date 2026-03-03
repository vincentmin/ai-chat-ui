import { Message, MessageContent } from '@/components/ai-elements/message'

import { Actions, Action } from '@/components/ai-elements/actions'
import { Response } from '@/components/ai-elements/response'
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
    return (
      <div className="py-4">
        <Message from={message.role}>
          <MessageContent>
            <Response>{part.text}</Response>
          </MessageContent>
        </Message>
        {message.role === 'assistant' && index === message.parts.length - 1 && (
          <Actions className="mt-1">
            <Action onClick={handleRetry} label="Retry">
              <RefreshCcwIcon className="size-3" />
            </Action>
            <Action
              onClick={() => {
                handleCopy(part.text)
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
