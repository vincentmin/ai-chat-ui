# Fullstack Production Architecture Migration Plan

## Objective

Move the chatbot application to a backend-persistent, task-queue-based architecture that supports long-running Pydantic AI agents, resumable streaming, and environment-specific infrastructure (SQLite/Redis in development, PostgreSQL/Redis in production).

## Agreed Decisions (2026-02-23)

1. Canonical chat endpoint shape is `/chat/{id}`.
2. Canonical persisted conversation state is `AgentRunResult` snapshots, not stored `UIMessage[]` arrays.
3. The backend generates conversation IDs for new chats and the frontend navigates to `/chat/{id}` before sending messages.
4. Taskiq broker backend is Redis in both development and production.
5. Development Redis defaults to in-process `redislite` (or `REDIS_URL` override), while production requires managed `REDIS_URL`.

### Persistence Implication

- `AgentRunResult` remains the source of truth.
- `UIMessage[]` is derived on demand from persisted run snapshots using `ModelMessage` extraction and `VercelAIAdapter.dump_messages(...)`.
- This keeps storage schema agent-agnostic while preserving complete run internals (including `_state`) for replay and future migration logic.

## Step-by-Step Plan

1. Define the target architecture and runtime boundaries

   Clarify system responsibilities across frontend, API service, worker service, broker, and database so every subsystem has a single ownership area. This creates a shared blueprint for implementation and testing.

2. Establish environment configuration strategy

   Introduce explicit environment profiles for development and production, including database URLs, broker backend selection, and stream transport settings. Ensure local development works with minimal setup while production uses managed infrastructure.

3. Implement persistent chat domain model with SQLModel

   Start with a minimal, flexible schema centered on persisted `AgentRunResult` snapshots keyed by conversation ID and run metadata. Keep this as the canonical source and defer normalization of messages/parts/events until required by query patterns or operational constraints.

4. Add database session and lifecycle management in FastAPI

   Build a database layer with dependency-based session injection, schema initialization/migrations, and environment-aware engine configuration (SQLite for local, PostgreSQL for production). This centralizes persistence concerns and keeps endpoint logic focused.

5. Refactor API endpoints around backend-owned conversation state

   Shift chat history ownership from frontend local state to backend persistence. Use `POST /chat/{id}` for run execution and `GET /chat/{id}` for history load, where response messages are derived from the latest persisted `AgentRunResult` snapshot.

6. Integrate Taskiq application topology

   Introduce a dedicated Taskiq setup with separate API and worker roles. Configure Redis broker for both local development and production so long-running agent execution is decoupled from request lifetimes and behavior is consistent across environments.

7. Implement background task for agent execution

   Move agent runs into Taskiq tasks that load conversation context, invoke Pydantic AI, and process stream events. Persist significant events and run metadata to the database for observability and restart safety.

8. Capture agent output stream and publish to Redis stream

   Inside the Taskiq task, translate agent stream output into a stream protocol suitable for client delivery and resumption. Publish ordered events to a Redis stream keyed by chat/session identifier and track completion states.

9. Implement `POST /chat/{id}` as trigger-plus-stream endpoint

   Make this endpoint start or resume a task execution, then immediately attach to the corresponding Redis stream to relay output to the client over SSE. The endpoint should enforce idempotency, authorization, and clear lifecycle semantics.

10. Implement `GET /chat/{id}/stream` for resume/reconnect

    Provide a stream-only endpoint that attaches clients to an existing in-flight or recently completed stream. Support reconnection offsets and replay behavior so interrupted clients can continue without losing events.

11. Keep AI SDK protocol compatibility via VercelAIAdapter

    Ensure stream/event payloads remain compatible with the frontend `useChat` expectations by using the Pydantic AI VercelAIAdapter format consistently across task execution and API streaming.

12. Update frontend data flow to backend-persisted chat lifecycle

Keep `useChat`, Vercel AI Elements, and shadcn components for rendering and interaction, but remove localStorage as the source of truth for messages. Frontend should rely on backend chat IDs (`/chat/{id}`), server history loading (`GET /chat/{id}`), and stream reconnect support.

## Near-Term Execution Plan (Step 3 to Step 5 bridge)

1. Add `POST /chat` create endpoint returning backend-generated conversation ID.
2. Move run endpoint to `POST /chat/{id}` and remove conversation ID inference from run results.
3. Persist full `AgentRunResult` snapshot in `on_complete` for each run.
4. Add `GET /chat/{id}` to derive `UIMessage[]` from persisted snapshot and return it to the frontend.
5. Update frontend routing/transport to always use `/chat/{id}` and load history from backend.
6. Remove frontend localStorage message persistence (conversation list migration can follow separately).

7. Implement reliability controls for long-running tasks

   Add timeout policy, retry strategy, cancellation behavior, deduplication safeguards, and status tracking for queued/running/completed/failed states. Start with strict idempotency and retries disabled by default, then enable bounded retries after deduplication proves stable in tests. This prevents duplicate runs and improves operational predictability.

8. Add local developer workflow and tooling

   Provide a frictionless local setup path using SQLite + Redis by default (backed by `redislite` unless `REDIS_URL` is set), and an optional Docker Compose profile for external Redis and PostgreSQL integration testing. Document startup order for API, worker, and frontend services.

9. Expand observability and diagnostics

   Add structured logs, correlation IDs, stream/task identifiers, and health checks for API, broker, worker, and database integrations. This enables debugging of queueing, persistence, and streaming issues.

10. Validate end-to-end behavior with tests

    Create test coverage for domain persistence, task enqueue/execute flow, stream publication, stream resumption, and API compatibility with `useChat`. Include both unit and integration tests to protect against regressions.

11. Harden production deployment and operations

    Finalize deployment topology, worker scaling model, secure configuration handling, migration process, and runbooks for incident response. This ensures the architecture is maintainable beyond local development.

## Definition of Done

- Frontend remains based on `useChat`, Vercel AI Elements, and shadcn UI.
- Message history is persisted and sourced from backend storage (derived from persisted `AgentRunResult`).
- SQLModel is the ORM with SQLite in development and PostgreSQL in production.
- Taskiq executes long-running agent work outside request threads.
- Development and production both use Redis broker (development defaults to `redislite`).
- Agent stream events are captured in workers and published to Redis streams.
- `POST /chat/{id}` triggers processing and streams output to the client.
- `GET /chat/{id}` returns conversation history derived from backend persistence.
- `GET /chat/{id}/stream` allows reconnecting/resuming running streams.
- Pydantic AI and VercelAIAdapter remain the protocol bridge to AI SDK.
