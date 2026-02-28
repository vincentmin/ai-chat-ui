import { describe, expect, it } from 'vitest'

import { getToolApprovalLabel } from './tool-approval-labels'

describe('getToolApprovalLabel', () => {
  it('returns tool specific copy for mapped tools', () => {
    expect(getToolApprovalLabel('tool-query', {})).toBe('Approve executing this SQL query?')
    expect(getToolApprovalLabel('tool-display_paper', {})).toBe('Approve displaying this paper preview?')
  })

  it('falls back to generic copy for unknown tools', () => {
    expect(getToolApprovalLabel('tool-unknown_action', {})).toBe('Approve running unknown_action?')
  })
})
