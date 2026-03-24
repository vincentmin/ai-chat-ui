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

  it('correctly parses body that contains }]] without treating it as metadata', () => {
    expect(parseMailboxMessage('[[mailbox {"sender":"arxiv"}]]\nbody with }]] inside')).toEqual({
      body: 'body with }]] inside',
      sender: 'arxiv',
      isMailbox: true,
    })
  })

  it('returns plain text for unrecognised messages', () => {
    expect(parseMailboxMessage('[Message from arxiv]: hello')).toEqual({
      body: '[Message from arxiv]: hello',
      sender: null,
      isMailbox: false,
    })
  })

  it('formats mailbox previews with a readable sender label', () => {
    expect(formatConversationPreview('[[mailbox {"sender":"user"}]]\nhello')).toBe('You: hello')
  })
})
