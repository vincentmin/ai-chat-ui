type ToolApprovalLabelFactory = (input: unknown) => string

const labelMap: Record<string, ToolApprovalLabelFactory | undefined> = {
  query: () => 'Approve executing this SQL query?',
  display: () => 'Approve displaying SQL results in the UI?',
  fetch: () => 'Approve fetching this paper PDF?',
  display_paper: () => 'Approve displaying this paper preview?',
}

function normalizeToolId(type: string): string {
  return type.startsWith('tool-') ? type.slice(5) : type
}

export function getToolApprovalLabel(type: string, input: unknown): string {
  const toolId = normalizeToolId(type)
  const labelFactory = labelMap[toolId]

  if (labelFactory) {
    return labelFactory(input)
  }

  return `Approve running ${toolId}?`
}
