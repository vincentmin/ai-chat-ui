import App from './App'
import { ThemeProvider } from './components/theme-provider'
import { SidebarProvider } from './components/ui/sidebar'
import { Toaster } from './components/ui/sonner'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
  useNavigate,
  useParams,
} from '@tanstack/react-router'

const queryClient = new QueryClient()

function handleNavigationError(error: unknown) {
  console.error('Navigation failed', error)
}

function RootLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider defaultTheme="system" storageKey="pydantic-chat-ui-theme">
        <SidebarProvider defaultOpen>
          <Outlet />
        </SidebarProvider>
      </ThemeProvider>
      <Toaster richColors />
    </QueryClientProvider>
  )
}

function SqlRoutePage() {
  const navigate = useNavigate()

  return (
    <App
      kind="sql"
      conversationId={null}
      onConversationIdChange={(id) => {
        if (!id) {
          navigate({ to: '/sql' }).catch(handleNavigationError)
          return
        }

        navigate({ to: '/sql/chat/$conversationId', params: { conversationId: id } }).catch(handleNavigationError)
      }}
    />
  )
}

function SqlConversationRoutePage() {
  const navigate = useNavigate()
  const { conversationId } = useParams({ from: '/sql/chat/$conversationId' })

  return (
    <App
      kind="sql"
      conversationId={conversationId}
      onConversationIdChange={(id) => {
        if (!id) {
          navigate({ to: '/sql' }).catch(handleNavigationError)
          return
        }

        navigate({ to: '/sql/chat/$conversationId', params: { conversationId: id } }).catch(handleNavigationError)
      }}
    />
  )
}

function ArxivRoutePage() {
  const navigate = useNavigate()

  return (
    <App
      kind="arxiv"
      conversationId={null}
      onConversationIdChange={(id) => {
        if (!id) {
          navigate({ to: '/arxiv' }).catch(handleNavigationError)
          return
        }

        navigate({ to: '/arxiv/chat/$conversationId', params: { conversationId: id } }).catch(handleNavigationError)
      }}
    />
  )
}

function ArxivConversationRoutePage() {
  const navigate = useNavigate()
  const { conversationId } = useParams({ from: '/arxiv/chat/$conversationId' })

  return (
    <App
      kind="arxiv"
      conversationId={conversationId}
      onConversationIdChange={(id) => {
        if (!id) {
          navigate({ to: '/arxiv' }).catch(handleNavigationError)
          return
        }

        navigate({ to: '/arxiv/chat/$conversationId', params: { conversationId: id } }).catch(handleNavigationError)
      }}
    />
  )
}

export function createAppRouter() {
  const rootRoute = createRootRoute({
    component: RootLayout,
  })

  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/',
    beforeLoad: () => redirect({ to: '/sql' }),
  })

  const legacyConversationRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/chat/$conversationId',
    beforeLoad: ({ params }) =>
      redirect({
        to: '/sql/chat/$conversationId',
        params: { conversationId: params.conversationId },
      }),
  })

  const sqlRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/sql',
    component: SqlRoutePage,
  })

  const sqlConversationRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/sql/chat/$conversationId',
    component: SqlConversationRoutePage,
  })

  const arxivRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/arxiv',
    component: ArxivRoutePage,
  })

  const arxivConversationRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: '/arxiv/chat/$conversationId',
    component: ArxivConversationRoutePage,
  })

  const routeTree = rootRoute.addChildren([
    indexRoute,
    legacyConversationRoute,
    sqlRoute,
    sqlConversationRoute,
    arxivRoute,
    arxivConversationRoute,
  ])

  return createRouter({
    routeTree,
  })
}

export const router = createAppRouter()

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
