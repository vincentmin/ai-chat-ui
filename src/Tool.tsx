import {
  Confirmation,
  ConfirmationAccepted,
  ConfirmationAction,
  ConfirmationActions,
  ConfirmationRejected,
  ConfirmationRequest,
} from '@/components/ai-elements/confirmation'
import { CodeBlock } from '@/components/ai-elements/code-block'
import { Tool as ToolContainer, ToolContent, ToolHeader, ToolInput, ToolOutput } from '@/components/ai-elements/tool'
import { getToolApprovalLabel } from '@/lib/tool-approval-labels'
import type { UIDataTypes, UIMessagePart, UITools } from 'ai'
import { useEffect, useState } from 'react'

type AppMessagePart = UIMessagePart<UIDataTypes, UITools>
export type DynamicToolPart = Extract<AppMessagePart, { type: 'dynamic-tool' }>
export type StaticToolPart = Extract<AppMessagePart, { toolCallId: string }>
export type ToolPartData = DynamicToolPart | StaticToolPart

interface ToolPartProps {
  part: ToolPartData
  onApproval: (approvalId: string | undefined, approved: boolean) => void
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

function shouldOpenTool(state: string): boolean {
  return state === 'approval-requested'
}

function getToolHeaderType(part: ToolPartData): `tool-${string}` | null {
  if (part.type === 'dynamic-tool') {
    return `tool-${part.toolName}`
  }

  if ('toolCallId' in part && part.type.startsWith('tool-')) {
    return part.type
  }

  return null
}

export function isToolPart(part: AppMessagePart): part is ToolPartData {
  return part.type === 'dynamic-tool' || 'toolCallId' in part
}

export function ToolPart({ part, onApproval }: ToolPartProps) {
  const headerType = getToolHeaderType(part)
  const [isOpen, setIsOpen] = useState(() => shouldOpenTool(part.state))

  useEffect(() => {
    // defaultOpen only applies on mount; keep approval prompts visible when state updates in place.
    if (shouldOpenTool(part.state)) {
      setIsOpen(true)
    }
  }, [part.state])

  if (!headerType) {
    return null
  }

  const parsedInput = parseMaybeJson(part.input)
  const parsedOutput = part.state === 'output-available' ? parseMaybeJson(part.output) : undefined

  return (
    <ToolContainer open={isOpen} onOpenChange={setIsOpen}>
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
                onApproval(part.approval?.id, false)
              }}
              variant="outline"
            >
              Deny
            </ConfirmationAction>
            <ConfirmationAction
              onClick={() => {
                onApproval(part.approval?.id, true)
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
    </ToolContainer>
  )
}
