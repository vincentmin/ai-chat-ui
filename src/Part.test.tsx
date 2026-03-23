import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { UIMessage } from 'ai'

import { Part } from './Part'

const noop = vi.fn()

describe('Part', () => {
  it('renders mailbox user messages literally and shows You instead of the raw mailbox prefix', () => {
    const message: UIMessage = {
      id: 'msg-1',
      role: 'user',
      parts: [{ type: 'text' as const, text: '[[mailbox {"sender":"user"}]]\nHi' }],
    }
    const part = message.parts[0]

    render(<Part part={part} message={message} regen={noop} addToolApprovalResponse={noop} index={0} />)

    expect(screen.getByText('You')).toBeTruthy()
    expect(screen.getByText('Hi')).toBeTruthy()
    expect(screen.queryByText('[[mailbox {"sender":"user"}]]')).toBeNull()
  })

  it('renders assistant message text through markdown', () => {
    const message: UIMessage = {
      id: 'msg-2',
      role: 'assistant',
      parts: [{ type: 'text' as const, text: 'Hello, how can I help?' }],
    }
    const part = message.parts[0]

    render(<Part part={part} message={message} regen={noop} addToolApprovalResponse={noop} index={0} />)

    expect(screen.getByText('Hello, how can I help?')).toBeTruthy()
  })

  it('renders agent mailbox messages without the transport header', () => {
    const message: UIMessage = {
      id: 'msg-3',
      role: 'user',
      parts: [{ type: 'text' as const, text: '[[mailbox {"sender":"arxiv"}]]\nFound two relevant papers.' }],
    }
    const part = message.parts[0]

    render(<Part part={part} message={message} regen={noop} addToolApprovalResponse={noop} index={0} />)

    expect(screen.getByText('arxiv')).toBeTruthy()
    expect(screen.getByText('Found two relevant papers.')).toBeTruthy()
    expect(screen.queryByText('[[mailbox {"sender":"arxiv"}]]')).toBeNull()
  })
})
