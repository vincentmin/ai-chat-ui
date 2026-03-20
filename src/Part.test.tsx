import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { UIMessage } from 'ai'

import { Part } from './Part'

const noop = vi.fn()

describe('Part', () => {
  it('renders user message text that looks like a markdown reference link definition', () => {
    // [Message from sql]: Hi  is valid markdown reference-link-definition syntax
    // which produces NO visible output under CommonMark.
    // User messages must render text literally, not through a markdown renderer.
    const message: UIMessage = {
      id: 'msg-1',
      role: 'user',
      parts: [{ type: 'text' as const, text: '[Message from sql]: Hi' }],
    }
    const part = message.parts[0]

    render(<Part part={part} message={message} regen={noop} addToolApprovalResponse={noop} index={0} />)

    // The text MUST be visible in the DOM — not swallowed by markdown parsing.
    expect(screen.getByText('[Message from sql]: Hi')).toBeTruthy()
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
})
