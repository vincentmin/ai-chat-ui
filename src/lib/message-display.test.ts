import { describe, expect, it } from 'vitest'

import { formatConversationPreview, parseMailboxMessage } from './message-display'

describe('message display helpers', () => {
  it('parses the structured mailbox envelope', () => {
    expect(parseMailboxMessage('[[mailbox {"sender":"arxiv"}]]\nhello')).toEqual({
      body: 'hello',
      sender: 'arxiv',
      isMailbox: true,
    })
  })

  it('keeps parsing the legacy mailbox prefix for existing conversations', () => {
    expect(parseMailboxMessage('[Message from arxiv]: hello')).toEqual({
      body: 'hello',
      sender: 'arxiv',
      isMailbox: true,
    })
  })

  it('formats mailbox previews with a readable sender label', () => {
    expect(formatConversationPreview('[[mailbox {"sender":"user"}]]\nhello')).toBe('You: hello')
  })
})
