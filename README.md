# Pydantic AI Chat UI

A React-based chat interface for [Pydantic AI](https://ai.pydantic.dev/). This package powers the documentation assistant at [ai.pydantic.dev/web/](https://ai.pydantic.dev/web/).

Built with [Vercel AI SDK](https://sdk.vercel.ai/) and designed to work with Pydantic AI's streaming chat API.

## Features

- Streaming message responses with reasoning display
- Tool call visualization with collapsible input/output
- Conversation persistence via localStorage
- Dynamic model and tool selection
- Dark/light theme support
- Mobile-responsive sidebar

## Architecture

```mermaid
flowchart LR
	FE[Frontend\nReact + Vercel AI SDK useChat]
	API[Backend API\nFastAPI]
	RQ[(Redis\nTaskiq queue)]
	RS[(Redis Streams\nSSE events)]
	WK[Worker\nTaskiq]
	AG[Pydantic AI Agent]
	DB[(SQLite/PostgreSQL\nconversation snapshots)]

	FE -->|POST /api/.../chat/:conversationId| API
	FE -->|GET /api/.../chat/:conversationId/stream| API
	API -->|enqueue run_agent_task| RQ
	RQ -->|dequeue task| WK
	WK -->|execute| AG
	AG -->|event chunks| WK
	WK -->|publish stream events| RS
	API -->|read stream events| RS
	API -->|send sse events| FE
	WK -->|save run snapshot| DB
	API -->|read chat history/runs| DB
```

Redis has two distinct roles:

- Task broker for Taskiq (`ListQueueBroker`, queue-based task dispatch)
- Streaming transport for AI output (`Redis Streams`, chunk/terminal events)

## Request Lifetime

```mermaid
sequenceDiagram
	autonumber
	participant FE as Frontend (useChat)
	participant API as FastAPI
	participant RQ as Redis (Task Queue)
	participant WK as Taskiq Worker
	participant AG as Pydantic AI Agent
	participant RS as Redis Streams

	FE->>API: 1) Send message (POST /chat/{id})
	API->>RQ: 2) Enqueue run task
	API->>RS: 5) Start stream relay immediately (xread)
	RQ-->>WK: 3) Worker picks up task
	WK->>AG: Execute agent run
	AG-->>WK: 4) Stream result chunks
	WK->>RS: 4) Publish chunks + terminal event
	RS-->>API: Stream events available
	API-->>FE: 5) Forward SSE chunks to useChat transport
```

## Development

Requires [Docker](https://docs.docker.com/get-started/get-docker/) for Redis.

```sh
pnpm install
pnpm run dev:full    # start Redis (Docker) + frontend + backend + Taskiq worker

# or run each service separately:
docker compose up -d redis  # start Redis
pnpm run dev:server          # start the Python backend (requires agent/ setup)
pnpm run dev:worker          # start the Taskiq worker
pnpm run dev                 # start the Vite dev server
```

## License

MIT
