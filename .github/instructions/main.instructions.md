---
applyTo: '**/*'
---

## Project Overview

A React-based chat interface for Pydantic AI that uses Vercel AI SDK and Elements. The project consists of a frontend (Vite + React + TypeScript) and a Python backend (FastAPI + Pydantic AI).

## Development Commands

```bash
pnpm install
pnpm run dev              # Start dev server
pnpm run dev:server       # Start backend server
pnpm run build            # Build for production (CDN deployment via jsdelivr)
pnpm run typecheck        # Type check without emitting
pnpm run lint             # Run ESLint
pnpm run lint-fix         # Fix ESLint issues
pnpm run format           # Format with Prettier
```

## Architecture

### Frontend Structure

- **src/Chat.tsx**: Main chat component handling conversation state, message sending, and local storage persistence
- **src/Part.tsx**: Renders individual message parts (text, reasoning, tools, etc.)
- **src/App.tsx**: Root component with theme provider, sidebar, and React Query setup
- **src/components/ai-elements/**: Vercel AI Elements wrappers (conversation, prompt-input, message, tool, reasoning, sources, etc.)
- **src/components/ui/**: Radix UI and shadcn/ui components

### Key Frontend Concepts

**Conversation Management:**

- Conversations stored in localStorage by ID (nanoid)
- URL-based routing: `/` for new chat, `/{nanoid}` for existing
- Messages persisted via `useChat` hook and localStorage sync (throttled 500ms)
- Conversation list stored in localStorage key `conversationIds`

**Model & Tool Selection:**

- Dynamic model/tool configuration fetched from `/api/configure`
- Models and available builtin tools configured per-model
- Tools toggled via checkboxes in prompt toolbar

**Message Parts:**

- Messages contain multiple parts: text, reasoning, tool calls, sources
- Part rendering delegated to `Part.tsx` component
- Tool calls show input/output with collapsible UI

### Backend Structure

- **agent/chatbot/server.py**: FastAPI app with Vercel AI adapter, model/tool configuration
- **agent/chatbot/agent.py**: Pydantic AI agent with simple mock weather tool

### Backend Integration

**Endpoints:**

- `GET /api/configure`: Returns available models and builtin tools (camelCase)
- `POST /api/chat`: Handles chat messages via `VercelAIAdapter`
  - Accepts `model` and `builtinTools` in request body extra data
  - Streams responses using SSE

## Configuration

- **TypeScript paths**: `@/*` maps to `./src/*`

## Tech Stack

- React 19, TypeScript, Vite, Tailwind CSS 4
- Vercel AI SDK (`@ai-sdk/react`, `ai`)
- Radix UI primitives
- FastAPI, Pydantic AI
- ESLint (neostandard), Prettier
