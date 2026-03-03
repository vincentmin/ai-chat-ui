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
import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai-elements/reasoning'
import { Tool, ToolHeader, ToolInput, ToolOutput, ToolContent } from '@/components/ai-elements/tool'
import { CodeBlock } from '@/components/ai-elements/code-block'
import { getToolApprovalLabel } from '@/lib/tool-approval-labels'

interface PartProps {
  part: UIMessagePart<UIDataTypes, UITools>
  message: UIMessage
  status: string
  regen: (id: string) => void
  addToolApprovalResponse: (response: { id: string; approved: boolean }) => void
  index: number
  lastMessage: boolean
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
  return (
    state === 'approval-requested' ||
    state === 'approval-responded' ||
    state === 'output-available' ||
    state === 'output-denied' ||
    state === 'output-error'
  )
}

export function Part({ part, message, status, regen, addToolApprovalResponse, index, lastMessage }: PartProps) {
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
            <Action
              onClick={() => {
                regen(message.id)
              }}
              label="Retry"
            >
              <RefreshCcwIcon className="size-3" />
            </Action>
            <Action
              onClick={() => {
                copy(part.text)
              }}
              label="Copy"
            >
              <CopyIcon className="size-3" />
            </Action>
          </Actions>
        )}
      </div>
    )
  } else if (part.type === 'reasoning') {
    const firstReasoningIndex = message.parts.findIndex((candidate) => candidate.type === 'reasoning')
    if (index !== firstReasoningIndex) {
      return null
    }

    const reasoningText = message.parts
      .filter((candidate) => candidate.type === 'reasoning')
      .map((candidate) => candidate.text)
      .join('\n\n')
    const isReasoningStreaming = status === 'streaming' && lastMessage && message.parts.at(-1)?.type === 'reasoning'

    return (
      <Reasoning className="w-full" isStreaming={isReasoningStreaming}>
        <ReasoningTrigger />
        <ReasoningContent>{reasoningText}</ReasoningContent>
      </Reasoning>
    )
  } else if (part.type === 'dynamic-tool') {
    const parsedInput = parseMaybeJson(part.input)
    const parsedOutput = part.state === 'output-available' ? parseMaybeJson(part.output) : undefined

    return (
      <Tool defaultOpen={shouldOpenTool(part.state)}>
        <ToolHeader type={`tool-${part.toolName}`} state={part.state} />
        <ToolContent>
          <ToolInput input={parsedInput} />
          <Confirmation approval={part.approval} state={part.state}>
            <ConfirmationRequest>{getToolApprovalLabel(`tool-${part.toolName}`, parsedInput)}</ConfirmationRequest>
            <ConfirmationAccepted>Tool execution approved.</ConfirmationAccepted>
            <ConfirmationRejected>Tool execution denied.</ConfirmationRejected>
            <ConfirmationActions>
              <ConfirmationAction
                onClick={() => {
                  if (!part.approval) {
                    return
                  }
                  addToolApprovalResponse({ id: part.approval.id, approved: false })
                }}
                variant="outline"
              >
                Deny
              </ConfirmationAction>
              <ConfirmationAction
                onClick={() => {
                  if (!part.approval) {
                    return
                  }
                  addToolApprovalResponse({ id: part.approval.id, approved: true })
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
  } else if ('toolCallId' in part) {
    const parsedInput = parseMaybeJson(part.input)
    const parsedOutput = part.state === 'output-available' ? parseMaybeJson(part.output) : undefined

    return (
      <Tool defaultOpen={shouldOpenTool(part.state)}>
        <ToolHeader type={part.type} state={part.state} />
        <ToolContent>
          <ToolInput input={parsedInput} />
          <Confirmation approval={part.approval} state={part.state}>
            <ConfirmationRequest>{getToolApprovalLabel(part.type, parsedInput)}</ConfirmationRequest>
            <ConfirmationAccepted>Tool execution approved.</ConfirmationAccepted>
            <ConfirmationRejected>Tool execution denied.</ConfirmationRejected>
            <ConfirmationActions>
              <ConfirmationAction
                onClick={() => {
                  if (!part.approval) {
                    return
                  }
                  addToolApprovalResponse({ id: part.approval.id, approved: false })
                }}
                variant="outline"
              >
                Deny
              </ConfirmationAction>
              <ConfirmationAction
                onClick={() => {
                  if (!part.approval) {
                    return
                  }
                  addToolApprovalResponse({ id: part.approval.id, approved: true })
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
}
