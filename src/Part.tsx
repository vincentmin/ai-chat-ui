import { Message, MessageContent } from '@/components/ai-elements/message'

import { Actions, Action } from '@/components/ai-elements/actions'
import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
} from '@/components/ai-elements/confirmation'
import { Response } from '@/components/ai-elements/response'
import { CopyIcon, RefreshCcwIcon } from 'lucide-react'
import type { UIDataTypes, UIMessagePart, UITools, UIMessage } from 'ai'
import { Tool, ToolHeader, ToolInput, ToolOutput, ToolContent } from '@/components/ai-elements/tool'
import { CodeBlock } from '@/components/ai-elements/code-block'
import { getToolApprovalLabel } from '@/lib/tool-approval-labels'

interface PartProps {
  part: UIMessagePart<UIDataTypes, UITools>
  message: UIMessage
  regen: (id: string) => void
  addToolApprovalResponse: (response: { id: string; approved: boolean }) => void
  index: number
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== 'string') {
    return value
  }

  try {
    return JSON.parse(value)
  } catch {
    return value
  }
}

function copy(text: string) {
  navigator.clipboard.writeText(text).catch((error: unknown) => {
    console.error('Error copying text:', error)
  })
}

function shouldOpenTool(state: string): boolean {
  return state === 'approval-requested'
}

function getToolHeaderType(part: UIMessagePart<UIDataTypes, UITools>): `tool-${string}` | null {
  if (part.type === 'dynamic-tool') {
    return `tool-${part.toolName}`
  }

  if ('toolCallId' in part && part.type.startsWith('tool-')) {
    return part.type
  }

  return null
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
  } else if (part.type === 'dynamic-tool' || 'toolCallId' in part) {
    const headerType = getToolHeaderType(part)
    if (!headerType) {
      return null
    }

    const parsedInput = parseMaybeJson(part.input)
    const parsedOutput = part.state === 'output-available' ? parseMaybeJson(part.output) : undefined

    return (
      <Tool defaultOpen={shouldOpenTool(part.state)}>
        <ToolHeader type={headerType} state={part.state} />
        <ToolContent>
          <ToolInput input={parsedInput} />
          <Confirmation approval={part.approval} state={part.state}>
            <ConfirmationRequest>{getToolApprovalLabel(headerType, parsedInput)}</ConfirmationRequest>
            <ConfirmationAccepted>Tool execution approved.</ConfirmationAccepted>
            <ConfirmationRejected>Tool execution denied.</ConfirmationRejected>
            <ConfirmationActions>
              <ConfirmationAction
                onClick={() => {
                  handleToolApproval(part.approval?.id, false)
                }}
                variant="outline"
              >
                Deny
              </ConfirmationAction>
              <ConfirmationAction
                onClick={() => {
                  handleToolApproval(part.approval?.id, true)
                }}
              >
                Approve
              </ConfirmationAction>
            </ConfirmationActions>
          </Confirmation>
          {(part.state === 'output-available' || part.state === 'output-error') && (
            <ToolOutput
              errorText={part.errorText}
              output={
                part.state === 'output-available' ? (
                  <CodeBlock code={JSON.stringify(parsedOutput, null, 2)} language="json" />
                ) : null
              }
            />
          )}
        </ToolContent>
      </Tool>
    )
  }

  return null
}
