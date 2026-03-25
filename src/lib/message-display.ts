const STRUCTURED_MAILBOX_PREFIX = '[[mailbox '
const STRUCTURED_MAILBOX_DELIMITER = ']]'

export interface ParsedMailboxMessage {
  body: string
  sender: string | null
  isMailbox: boolean
}

export function parseMailboxMessage(text: string): ParsedMailboxMessage {
  if (text.startsWith(STRUCTURED_MAILBOX_PREFIX)) {
    const delimIdx = text.indexOf(STRUCTURED_MAILBOX_DELIMITER, STRUCTURED_MAILBOX_PREFIX.length)
    if (delimIdx !== -1) {
      const metadataStr = text.slice(STRUCTURED_MAILBOX_PREFIX.length, delimIdx)
      const afterDelim = text.slice(delimIdx + STRUCTURED_MAILBOX_DELIMITER.length)
      const body = afterDelim.startsWith('\n') ? afterDelim.slice(1) : afterDelim
      try {
        const metadata = JSON.parse(metadataStr) as { sender?: unknown }
        if (typeof metadata.sender === 'string' && metadata.sender.trim()) {
          return { body, sender: metadata.sender, isMailbox: true }
        }
      } catch {
        // Fall through to plain text handling.
      }
    }
  }

  return {
    body: text,
    sender: null,
    isMailbox: false,
  }
}

export function formatMailboxSenderLabel(sender: string): string {
  return sender === 'user' ? 'You' : sender
}

export function formatConversationPreview(text: string | null | undefined): string | undefined {
  if (!text) {
    return text ?? undefined
  }

  const parsed = parseMailboxMessage(text)
  if (!parsed.isMailbox || !parsed.sender) {
    return text
  }

  const senderLabel = formatMailboxSenderLabel(parsed.sender)
  return parsed.body ? `${senderLabel}: ${parsed.body}` : senderLabel
}
