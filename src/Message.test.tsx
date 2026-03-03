import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { UIMessage } from 'ai'

import { Message } from './Message'

vi.mock('./Part', () => ({
  Part: ({ part }: { part: { type: string } }) => <div data-testid={`part-${part.type}`} />,
}))

describe('Message', () => {
  it('renders sources and aggregates reasoning while delegating only non-source/non-reasoning parts to Part', () => {
    const message = {
      id: 'assistant-1',
      role: 'assistant',
      parts: [
        { type: 'source-url', url: 'https://docs.example.com/guide' },
        { type: 'text', text: 'Hello' },
        { type: 'source-url', url: 'https://www.example.com/blog' },
        { type: 'reasoning', text: 'Thinking one...' },
        { type: 'reasoning', text: 'Thinking two...' },
      ],
    } as UIMessage

    render(
      <Message
        message={message}
        status="ready"
        regen={vi.fn()}
        addToolApprovalResponse={vi.fn()}
        lastMessage={true}
      />,
    )

    expect(screen.getByText('Used 2 sources')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Used 2 sources' }))
    expect(screen.getByRole('link', { name: 'docs.example.com' })).toBeTruthy()
    expect(screen.getByRole('link', { name: 'example.com' })).toBeTruthy()
    expect(screen.getByText('Thinking one...')).toBeTruthy()
    expect(screen.getByText('Thinking two...')).toBeTruthy()

    expect(screen.getByTestId('part-text')).toBeTruthy()
    expect(screen.queryByTestId('part-reasoning')).toBeNull()
    expect(screen.queryByTestId('part-source-url')).toBeNull()
  })
})
