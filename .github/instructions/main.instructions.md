---
applyTo: '**/*'
---

## Project Overview

A fullstack chatbot platform with a React frontend and a FastAPI backend. The frontend uses Vercel AI SDK (`useChat`) with AI Elements and shadcn UI components, while the backend owns conversation persistence, orchestrates long-running Pydantic AI agent runs through Taskiq workers, and streams AI SDK-compatible events to clients.

## Philosophy

- development experience is a priority: easy local setup without third party or docker services, hot reload, clear error messages, and minimal boilerplate
- frontend focuses on rendering and interaction, while backend handles state management, persistence, and long-running execution
- streaming architecture supports responsive UX and resilience to interruptions/client disconnects
- clear separation of concerns and single ownership areas for each subsystem (frontend, API service, workers, database, broker) to improve maintainability and testability

## Development Commands

```bash
pnpm install
pnpm run dev              # Start dev server
pnpm run dev:server       # Start backend server
pnpm run dev:worker       # Start Taskiq worker for agent execution
pnpm run build            # Build for production (CDN deployment via jsdelivr)
pnpm run typecheck        # Type check without emitting
pnpm run lint             # Run ESLint
pnpm run lint-fix         # Fix ESLint issues
pnpm run format           # Format with Prettier
pnpm run lefthook         # Run pre-commit hooks (includes typecheck, lint, ruff, ty-check)
```

If you expect or encounter any linting or formatting issues, consider running `pnpm run lefthook` to automatically fix and check for issues. You don't have to linting/formatting hooks always though, as it is simple for your human to handle those themselves.

## Architecture

### Runtime Boundaries (Step 1)

- **Frontend (React + AI SDK UI)**
  - Owns presentation, interaction state, and request initiation only.
  - Must not be the source of truth for persisted conversation history.
  - Renders backend-provided messages and stream events, including reconnect/resume UX.
- **API Service (FastAPI)**
  - Owns HTTP contract, auth/session validation, chat lifecycle orchestration, and SSE relay.
  - Persists and reads canonical chat state via database services.
  - Triggers or resumes worker execution; does not run long agent workloads inline with request threads.
- **Worker Service (Taskiq)**
  - Owns long-running Pydantic AI execution and tool orchestration.
  - Reads required conversation context from persistence and emits ordered agent events.
  - Must be idempotent and safe to resume/retry for the same chat/run identifiers.
- **Broker/Stream Transport**
  - Owns decoupled delivery between API and worker runtimes.
  - In development: Redis (defaulting to in-process redislite) for queueing and stream transport.
  - In production: Managed Redis for broker + stream transport and resumable event consumption.
- **Database (SQLModel-backed)**
  - Owns durable chat state, message parts, run metadata, and processing status.
  - SQLite is the local development default; PostgreSQL is the production default.

### Cross-Boundary Contracts

- Frontend communicates with backend only through `/api/configure`, `POST /api/chat/{id}`, and `GET /api/chat/{id}/stream`.
- API-to-worker handoff is asynchronous through Taskiq; API should treat worker processing as external to request lifetime.
- Worker-to-API event handoff uses ordered stream events adapted to AI SDK-compatible payloads.
- API remains the only HTTP surface; workers and broker are internal infrastructure components.
- Persistence writes are backend-owned; frontend never mutates canonical history directly.

### Environment Profiles (Step 2)

- Use `pydantic-settings` as the single source of configuration loading and profile inference.
- Profiles:
  - `development`: default when no production-only environment markers are present.
  - `production`: inferred when `REDIS_URL` is provided or when `APP_ENV=production` is explicitly set.
- Redis transport:
  - `production` requires `REDIS_URL` and must connect to managed Redis.
  - `development` defaults to in-process `redislite` and derives a runtime Redis URL from its unix socket unless `REDIS_URL` is provided.
- Keep environment-sensitive infrastructure decisions (database URL, broker backend, stream transport) in backend settings modules, not in frontend code.

### Frontend Structure

- **src/Chat.tsx**: Main chat component handling message sending, streaming UX, and conversation lifecycle with backend-managed history
- **src/Part.tsx**: Renders individual message parts (text, reasoning, tools, etc.)
- **src/App.tsx**: Root component with theme provider, sidebar, and React Query setup
- **src/components/ai-elements/**: Vercel AI Elements wrappers (conversation, prompt-input, message, tool, reasoning, sources, etc.)
- **src/components/ui/**: Radix UI and shadcn/ui components

### Key Frontend Concepts

**Conversation Management:**

- Conversations are identified by backend chat IDs and loaded from API persistence
- URL-based routing maps clients to persisted chat sessions
- Messages are streamed via `useChat` and sourced from backend state
- Reconnect flows use a dedicated stream endpoint for resumable runs

**Model & Tool Selection:**

- Dynamic model/tool configuration fetched from `/api/configure`
- Models and available builtin tools configured per-model
- Tools toggled via checkboxes in prompt toolbar

**Message Parts:**

- Messages contain multiple parts: text, reasoning, tool calls, sources
- Part rendering delegated to `Part.tsx` component
- Tool calls show input/output with collapsible UI

### Backend Structure

- **agent/chatbot/server.py**: FastAPI API layer for chat/session endpoints and stream relays
- **agent/chatbot/agent.py**: Pydantic AI agent implementation
- **agent/chatbot/tasks/**: Taskiq task handlers for long-running agent execution
- **agent/chatbot/db/**: SQLModel entities, sessions, and persistence services
- **agent/chatbot/streaming/**: Redis stream publishing/consumption utilities

### Persistence & Infrastructure

- SQLModel is used as the ORM for chat persistence.
- Development database is SQLite.
- Production database is PostgreSQL.
- Taskiq broker uses Redis in development and production.
- Worker tasks publish ordered agent output events to Redis streams keyed by chat/session.

### Backend Integration

**Endpoints:**

- `GET /api/configure`: Returns available models and builtin tools (camelCase)
- `POST /api/chat/{id}`: Starts or resumes an agent run and streams results to the client
  - Accepts model and tool selections as request metadata
  - Enqueues/coordinates Taskiq execution for long-running work
  - Relays AI SDK-compatible SSE from Redis stream events
- `GET /api/chat/{id}/stream`: Attaches to an in-progress or resumable stream for reconnect support

### Streaming Contract

- Pydantic AI output is adapted through `VercelAIAdapter` to AI SDK protocol events.
- Taskiq workers capture and forward stream events into Redis streams.
- API endpoints consume stream events and deliver them to frontend clients over SSE.
- Stream consumers support resume semantics for interrupted client connections.

## Best Practices

### Separation of Concerns

Each layer has a single, well-defined responsibility. Do not let concerns bleed across boundaries.

**Frontend layers:**

- **UI components** (`src/components/`): Purely presentational. Accept props, emit events. No direct API calls, no business logic, no global state reads. Stateless where possible.
- **Feature/page components** (`src/Chat.tsx`, `src/App.tsx`): Compose UI components, wire up hooks, handle interaction logic. Owns local UI state (open/close, hover, etc.) only.
- **Hooks** (`src/hooks/`): Encapsulate data-fetching, derived state, and side-effect logic. The only layer that calls TanStack Query or `useChat`. Components should not call `fetch` directly.
- **API layer** (`src/lib/api.ts`): Raw HTTP calls. Functions that construct requests and parse responses. No React dependencies, no state — just `async` functions that return typed data. This is the only place `fetch` is called directly.
- **Types** (`src/types.ts`): All API response shapes and shared TypeScript interfaces. No runtime logic. Never define API response types inside component or hook files.

**Backend layers:**

- **Router/endpoint** (`server.py`, `chat_router.py`): HTTP boundary only. Validate inputs, delegate to services, return responses. No SQL, no agent logic inline. Route handler bodies should be short — if a handler exceeds ~15 lines, extract the orchestration into a service function.
- **Service/business logic** (e.g. `tasks/run_agent_task.py`): Orchestrates agent execution, coordinates persistence calls, and publishes stream events. No direct HTTP or SQLModel session management.
- **Database/persistence** (`db/`): All SQLModel queries and session management live here. No business logic, no HTTP concerns. Services call into this layer, never the router directly. Never write SQL or call `session.add`/`session.commit` outside of this layer.
- **Infrastructure** (`streaming/`, `tasks/broker.py`): Redis streams, Taskiq broker config. Not called from UI-facing code paths.

### Classes vs Simple Functions

**Prefer plain functions by default.** Only introduce a class when there is genuine shared mutable state or lifecycle that a function cannot cleanly encapsulate.

- **Use functions for**: utilities, data transformations, API call wrappers, FastAPI route handlers, Pydantic AI tools, Taskiq task definitions, and any stateless operation.
- **Use classes for**: SQLModel entities (required by the ORM), Pydantic `BaseModel`/`BaseSettings` subclasses (required by pydantic-settings), and objects with meaningful identity and state that outlive a single call (e.g. a stream consumer that holds a connection open across multiple reads).
- **Avoid class-based patterns** that are idiomatic in other languages but unnecessary in Python/TypeScript: service classes with only one instance, static-method-only classes, classes used purely as namespaces. Use a module instead.
- In React, always use function components. Never use class components.

### fetch vs TanStack Query

**Use TanStack Query (`useQuery`, `useMutation`) for all data fetching in React components** except for the AI streaming use case.

| Situation                                                         | Use                                                                |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| Read data from the API (e.g. `/api/configure`, chat history)      | `useQuery`                                                         |
| Trigger a mutation (create, delete, update)                       | `useMutation`                                                      |
| AI chat streaming via Vercel AI SDK                               | `useChat` (wraps fetch internally; do not combine with `useQuery`) |
| One-shot fetch inside an event handler that does not need caching | raw `fetch` via a typed API helper function                        |
| Server-sent events / stream consumption                           | raw `fetch` with `ReadableStream` or `EventSource` in a hook       |

Rules:

- Never call `fetch` directly inside a component body. Put raw `fetch` calls in a dedicated API helper function and call that from a hook or query function.
- Do not duplicate query key logic. Define query keys as constants or factory functions and share them.
- Do not use TanStack Query for the streaming chat turn — `useChat` from Vercel AI SDK owns that lifecycle.

### Additional Best Practices

**TypeScript:**

- Enable strict mode. Never use `any` — use `unknown` and narrow it, or define a proper type.
- Define API response shapes as TypeScript interfaces in `src/types.ts`. Parse and validate at the API boundary, not deep in components.
- Prefer `type` for aliases and unions; use `interface` for object shapes that may be extended.

**React:**

- Keep components small and focused. If a component renders differently based on more than 2–3 conditions, split it.
- Avoid `useEffect` for data fetching — use TanStack Query. Reserve `useEffect` for true side-effects (DOM interaction, subscriptions, third-party integrations).
- Do not use `useEffect` to derive or initialize state from query or prop values. Compute derived values with `useMemo`, or pass the derived value as the initial `useState` argument.
- Colocate state as close as possible to where it is used. Lift only when multiple sibling components genuinely need it.
- Avoid prop drilling more than 2 levels. Use context or a hook for shared UI state.

**Python/FastAPI:**

- Use `async def` for all route handlers and any I/O-bound work (database, Redis, external APIs).
- Validate all external inputs with Pydantic models at the route handler boundary. Do not pass raw dicts into services.
- Keep route handler bodies short — delegate to service functions immediately. A handler should be readable in a few lines.
- Use dependency injection (`Depends`) for sessions, settings, and auth — never import globals into business logic.
- All configuration is read from `settings.py` (pydantic-settings). No hardcoded URLs, ports, or credentials.
- Never access `_`-prefixed (private) symbols from a module you don't own. If you need them, promote them to a public API in the owning module.
- Avoid module-level singleton state for infrastructure (database sessions, Redis clients). Initialise through dependency injection or explicit passing so they can be replaced in tests.

**Error handling:**

- Surface meaningful errors at the right layer. API handlers return appropriate HTTP status codes with structured error bodies. Services raise domain-specific exceptions; routers catch and translate them.
- Frontend: TanStack Query error states should be surfaced in the UI, not silently swallowed. Streaming errors should show a user-visible message.

**Testing (when tests are added):**

- Unit-test pure functions and service logic in isolation, mocking I/O boundaries.
- Integration-test route handlers against a real (in-memory/SQLite) database.
- Do not test implementation details of UI components — test behaviour from the user's perspective.

## Configuration

- **TypeScript paths**: `@/*` maps to `./src/*`
- **pydantic-settings**: Used for environment variable management in the backend

## Tech Stack

- React 19, TypeScript, Vite, Tailwind CSS 4
- Vercel AI SDK (`@ai-sdk/react`, `ai`)
- Vercel AI Elements and shadcn/ui
- Radix UI primitives
- FastAPI, Pydantic AI, SQLModel, Taskiq
- SQLite (development), PostgreSQL (production), Redis (development and production broker/stream transport)
- ESLint (neostandard), Prettier
