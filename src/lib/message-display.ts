const LEGACY_MAILBOX_MESSAGE_RE = /^\[Message from (?<sender>[^\]]+)\]:\s?(?<body>[\s\S]*)$/
const STRUCTURED_MAILBOX_MESSAGE_RE = /^\[\[mailbox (?<metadata>\{.*\})\]\]\n?(?<body>[\s\S]*)$/

export interface ParsedMailboxMessage {
  body: string
  sender: string | null
  isMailbox: boolean
}

export function parseMailboxMessage(text: string): ParsedMailboxMessage {
  const structuredMatch = STRUCTURED_MAILBOX_MESSAGE_RE.exec(text)
  if (structuredMatch?.groups) {
    try {
      const metadata = JSON.parse(structuredMatch.groups.metadata) as { sender?: unknown }
      if (typeof metadata.sender === 'string' && metadata.sender.trim()) {
        return {
          body: structuredMatch.groups.body,
          sender: metadata.sender,
          isMailbox: true,
        }
      }
    } catch {
      // Fall through to legacy/plain text handling.
    }
  }

  const legacyMatch = LEGACY_MAILBOX_MESSAGE_RE.exec(text)
  if (legacyMatch?.groups) {
    return {
      body: legacyMatch.groups.body,
      sender: legacyMatch.groups.sender,
      isMailbox: true,
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
