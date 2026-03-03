import type { ChatStatus, UIMessage } from 'ai'

import { Reasoning, ReasoningContent, ReasoningTrigger } from '@/components/ai-elements/reasoning'
import { Source, Sources, SourcesContent, SourcesTrigger } from '@/components/ai-elements/sources'
import { Part } from './Part'

interface MessageProps {
  message: UIMessage
  status: ChatStatus
  regen: (id: string) => void
  addToolApprovalResponse: (response: { id: string; approved: boolean }) => void
  lastMessage: boolean
}

function getSourceTitle(url: string): string {
  try {
    const parsedUrl = new URL(url)
    return parsedUrl.hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function Message({ message, status, regen, addToolApprovalResponse, lastMessage }: MessageProps) {
  const sourceParts = message.parts.filter((part) => part.type === 'source-url')
  const reasoningParts = message.parts.filter((part) => part.type === 'reasoning')
  const reasoningText = reasoningParts.map((part) => part.text).join('\n\n')
  const isReasoningStreaming = status === 'streaming' && lastMessage && message.parts.at(-1)?.type === 'reasoning'

  const nonSourceParts = message.parts
    .map((part, index) => ({ part, index }))
    .filter(({ part }) => part.type !== 'source-url' && part.type !== 'reasoning')

  return (
    <div>
      {sourceParts.length > 0 && (
        <Sources>
          <SourcesTrigger count={sourceParts.length} />
          <SourcesContent>
            {sourceParts.map((part, i) => (
              <Source href={part.url} key={`${message.id}-${part.url}-${i}`} title={getSourceTitle(part.url)}>
                {getSourceTitle(part.url)}
              </Source>
            ))}
          </SourcesContent>
        </Sources>
      )}
      {reasoningParts.length > 0 && (
        <Reasoning className="w-full" isStreaming={isReasoningStreaming}>
          <ReasoningTrigger />
          <ReasoningContent>{reasoningText}</ReasoningContent>
        </Reasoning>
      )}
      {nonSourceParts.map(({ part, index }) => (
        <Part
          key={`${message.id}-${index}`}
          part={part}
          message={message}
          index={index}
          regen={regen}
          addToolApprovalResponse={addToolApprovalResponse}
        />
      ))}
    </div>
  )
}
