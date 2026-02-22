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
```

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
  - In development: InMemoryBroker for queueing semantics with minimal setup.
  - In production: Redis for broker + stream transport and resumable event consumption.
- **Database (SQLModel-backed)**
  - Owns durable chat state, message parts, run metadata, and processing status.
  - SQLite is the local development default; PostgreSQL is the production default.

### Cross-Boundary Contracts

- Frontend communicates with backend only through `/api/configure`, `POST /api/chat/{id}`, and `GET /api/chat/{id}/stream`.
- API-to-worker handoff is asynchronous through Taskiq; API should treat worker processing as external to request lifetime.
- Worker-to-API event handoff uses ordered stream events adapted to AI SDK-compatible payloads.
- API remains the only HTTP surface; workers and broker are internal infrastructure components.
- Persistence writes are backend-owned; frontend never mutates canonical history directly.

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
- Taskiq broker uses InMemoryBroker in development.
- Taskiq broker uses Redis in production.
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

## Configuration

- **TypeScript paths**: `@/*` maps to `./src/*`
- **pydantic-settings**: Used for environment variable management in the backend

## Tech Stack

- React 19, TypeScript, Vite, Tailwind CSS 4
- Vercel AI SDK (`@ai-sdk/react`, `ai`)
- Vercel AI Elements and shadcn/ui
- Radix UI primitives
- FastAPI, Pydantic AI, SQLModel, Taskiq
- SQLite (development), PostgreSQL (production), Redis (production broker and stream transport)
- ESLint (neostandard), Prettier
