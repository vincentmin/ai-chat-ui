import { AppSidebar } from '@/components/app-sidebar'
import { TeamLayout } from '@/components/TeamLayout'
import { getTeamConfig } from '@/lib/api'
import { useQuery } from '@tanstack/react-query'

interface TeamPageProps {
  conversationId: string | null
  onConversationIdChange: (id: string | null) => void
}

export default function TeamPage({ conversationId, onConversationIdChange }: TeamPageProps) {
  const teamConfigQuery = useQuery({
    queryKey: ['team-config'],
    queryFn: getTeamConfig,
  })

  const agents = teamConfigQuery.data?.agents ?? []

  return (
    <>
      <AppSidebar
        apiBasePath="/api/v1/team"
        conversationBasePath="/team"
        title="Pydantic AI Team"
        conversationId={conversationId}
        onConversationIdChange={onConversationIdChange}
      />

      {agents.length > 0 ? (
        <TeamLayout agents={agents} conversationId={conversationId} setConversationId={onConversationIdChange} />
      ) : (
        <div className="flex flex-1 items-center justify-center text-muted-foreground">Loading team…</div>
      )}
    </>
  )
}
