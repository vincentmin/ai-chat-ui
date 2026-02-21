# Fullstack Production Architecture Migration Plan

## Objective

Move the chatbot application to a backend-persistent, task-queue-based architecture that supports long-running Pydantic AI agents, resumable streaming, and environment-specific infrastructure (SQLite/InMemoryBroker in development, PostgreSQL/Redis in production).

## Step-by-Step Plan

1. Define the target architecture and runtime boundaries

   Clarify system responsibilities across frontend, API service, worker service, broker, and database so every subsystem has a single ownership area. This creates a shared blueprint for implementation and testing.

2. Establish environment configuration strategy

   Introduce explicit environment profiles for development and production, including database URLs, broker backend selection, and stream transport settings. Ensure local development works with minimal setup while production uses managed infrastructure.

3. Implement persistent chat domain model with SQLModel

   Design SQLModel entities for conversations, messages, message parts, and processing state. Model fields should support ordered replay, resumable streams, metadata, and traceability between API requests and background runs.

4. Add database session and lifecycle management in FastAPI

   Build a database layer with dependency-based session injection, schema initialization/migrations, and environment-aware engine configuration (SQLite for local, PostgreSQL for production). This centralizes persistence concerns and keeps endpoint logic focused.

5. Refactor API endpoints around backend-owned conversation state

   Shift chat history ownership from frontend local state to backend persistence. Endpoints should read and write conversation state from the database and return canonical message history to clients.

6. Integrate Taskiq application topology

   Introduce a dedicated Taskiq setup with separate API and worker roles. Configure InMemoryBroker for local development and Redis broker for production so long-running agent execution is decoupled from request lifetimes.

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

    Keep `useChat`, Vercel AI Elements, and shadcn components for rendering and interaction, but remove localStorage as the source of truth for messages. Frontend should rely on backend chat IDs, server history loading, and stream reconnect support.

13. Implement reliability controls for long-running tasks

    Add timeout policy, retry strategy, cancellation behavior, deduplication safeguards, and status tracking for queued/running/completed/failed states. This prevents duplicate runs and improves operational predictability.

14. Add local developer workflow and tooling

    Provide a frictionless local setup path using SQLite + InMemoryBroker by default, and an optional Docker Compose profile for Redis and PostgreSQL integration testing. Document startup order for API, worker, and frontend services.

15. Expand observability and diagnostics

    Add structured logs, correlation IDs, stream/task identifiers, and health checks for API, broker, worker, and database integrations. This enables debugging of queueing, persistence, and streaming issues.

16. Validate end-to-end behavior with tests

    Create test coverage for domain persistence, task enqueue/execute flow, stream publication, stream resumption, and API compatibility with `useChat`. Include both unit and integration tests to protect against regressions.

17. Harden production deployment and operations

    Finalize deployment topology, worker scaling model, secure configuration handling, migration process, and runbooks for incident response. This ensures the architecture is maintainable beyond local development.

## Definition of Done

- Frontend remains based on `useChat`, Vercel AI Elements, and shadcn UI.
- Message history is persisted and sourced from backend storage.
- SQLModel is the ORM with SQLite in development and PostgreSQL in production.
- Taskiq executes long-running agent work outside request threads.
- Development uses InMemoryBroker; production uses Redis broker.
- Agent stream events are captured in workers and published to Redis streams.
- `POST /chat/{id}` triggers processing and streams output to the client.
- `GET /chat/{id}/stream` allows reconnecting/resuming running streams.
- Pydantic AI and VercelAIAdapter remain the protocol bridge to AI SDK.
