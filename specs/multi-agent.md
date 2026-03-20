# Multi-Agent Collaboration Specification

## Goals

Extend the existing single-agent chat platform into a **multi-agent system** where:

1. Multiple agents (e.g. SQL agent, Arxiv agent) can collaborate by exchanging messages within a shared conversation.
2. Users interact with each agent through separate, dedicated chat columns in the UI.
3. Agent-to-agent communication is asynchronous and non-blocking — no agent ever blocks waiting for another's response.
4. The system preserves the existing single-agent architecture as a building block; a single agent column is still a valid standalone experience.

---

## Architecture Overview

### Core Primitive: Shared `conversation_id`

Every agent in a team shares the same `conversation_id`. This is the only coupling between agents. Each agent maintains its own conversation history, own Taskiq runs, and own Redis streams — all keyed by `(agent_key, conversation_id)`.

### How Agents Communicate

Agents are made aware of each other through **system prompts** and a shared **`tell` tool**. When agent A wants to communicate with agent B, it calls `tell(agent="B", message="...")`. This tool:

1. Delivers the message to agent B's **mailbox** (a Redis list).
2. Returns immediately with `"Message sent to B."` — it does **not** block for a response.
3. If agent B is currently active (mid-run), it will pick up the message during its next model invocation via its `history_processor`.
4. If agent B is idle, the mailbox delivery triggers a new run ("wake-up") for agent B via its chat endpoint.

There is intentionally no `ask` tool. If agent A needs information from B, it `tell`s B and either continues with other work or finishes with a message like "Waiting for B to respond." When B's response eventually arrives (via B calling `tell(agent="A", message="...")`), agent A is woken up or receives it in its mailbox.

---

## Backend Design

### 1. `tell` Tool

A single tool registered on every team-participating agent:

```python
@agent.tool
async def tell(ctx: RunContext[AgentDeps], agent: str, message: str) -> str:
    """Send a message to another agent in the team."""
```

**Implementation sketch:**

- Validate that `agent` is a known agent key (not the calling agent itself).
- Write `(sender_agent_key, message, timestamp)` to the target agent's mailbox in Redis.
- If the target agent has no active run (`ChatRun` in QUEUED/RUNNING status), start a new run by posting to its internal endpoint or directly enqueuing a Taskiq task with a synthetic request body that contains the mailbox message as a user prompt.
- Return `f"Message sent to {agent}."`.

**Deps type:**

```python
@dataclass
class AgentDeps:
    conversation_id: str
    agent_key: str          # this agent's own key
    team_agents: list[str]  # keys of all agents in the team
```

The `conversation_id` and `agent_key` are needed so the `tell` tool knows where to route and how to identify the sender. `team_agents` is the set of valid targets.

### 2. Mailbox

Each `(agent_key, conversation_id)` pair has a mailbox backed by a **Redis list**:

```
Key format:  mailbox:{agent_key}:{conversation_id}
Value type:  Redis List of JSON-encoded MailboxMessage objects
```

```python
@dataclass
class MailboxMessage:
    sender: str        # agent_key of the sender
    content: str       # the message text
    timestamp: float   # epoch seconds
```

**Operations:**

- `push_to_mailbox(redis, agent_key, conversation_id, message)` — RPUSH.
- `drain_mailbox(redis, agent_key, conversation_id) -> list[MailboxMessage]` — Atomically read and delete all entries. Use a Redis **pipeline** (`LRANGE 0 -1` then `DEL` in a single pipeline call) or the `GETDEL`-style pattern. A pipeline is sufficient because the drain is only ever called from the single Taskiq worker that owns the current run for this `(agent_key, conversation_id)` — there is no concurrent consumer. The only concurrent writer is RPUSH from other agents, and a message arriving between LRANGE and DEL in the pipeline will simply be picked up by the next drain or post-run check. No Lua script is needed.

### 3. `history_processor` for Mailbox Interleaving

Pydantic AI's `history_processor` is called before each model invocation in the agent's react loop. This is the hook for injecting mailbox messages.

```python
def create_mailbox_history_processor(
    redis_client: redis.Redis,
    agent_key: str,
    conversation_id: str,
):
    async def process_history(messages: list[ModelMessage]) -> list[ModelMessage]:
        mailbox_messages = await drain_mailbox(redis_client, agent_key, conversation_id)
        if not mailbox_messages:
            return messages

        # Convert mailbox messages into ModelRequest parts
        injected = [
            ModelRequest(parts=[
                UserPromptPart(content=f"[Message from {msg.sender}]: {msg.content}")
            ])
            for msg in mailbox_messages
        ]
        return messages + injected

    return process_history
```

**Key detail:** The `history_processor` receives the full message history and returns a (possibly modified) version. By appending mailbox messages as `UserPromptPart`s at the end, the model sees them as new inputs in the conversation.

### 4. Agent Active Detection and Wake-Up

When a message arrives for an agent (via `tell` or a direct user message to the endpoint):

```
1. Push message to the agent's mailbox in Redis.
2. Check if the agent has an active run (ChatRun with QUEUED or RUNNING status).
   - YES → Do nothing further. The active run's history_processor will pick up
     the mailbox message before the next model invocation.
   - NO  → Start a new run for the agent (the existing wake-up path: create
     ChatRun, enqueue Taskiq task). The new run's first model invocation will
     drain the mailbox.
```

**Race condition mitigation:** When the agent finishes a run, it checks the mailbox one final time. If new messages arrived during the last model invocation (after the final `history_processor` call), the agent kicks off a new run for itself. This eliminates dropped messages.

```python
# In run_agent_task, after the agent stream completes:
remaining = await drain_mailbox(redis_client, agent_key, conversation_id)
if remaining:
    # Re-enqueue self with the remaining messages
    await _start_follow_up_run(agent_key, conversation_id, remaining)
```

### 5. `tell` Delivery: Direct Redis + Taskiq (No HTTP Loopback)

The `tell` tool runs inside a Taskiq worker which already has access to Redis. It writes directly to the target agent's mailbox and optionally enqueues a wake-up Taskiq task — no HTTP round-trip required.

```python
# Inside the tell tool implementation:
await push_to_mailbox(redis_client, target_agent_key, conversation_id, message)
if not await has_active_run(db_session, target_agent_key, conversation_id):
    await enqueue_wake_up_run(target_agent_key, conversation_id)
```

HTTP endpoints are reserved for external callers (user frontend, external services).

**User messages while agent is active:** The `POST /chat/{conversation_id}` endpoint always routes incoming messages through the mailbox. If the agent has an active run, the message is added to the mailbox and the running agent's `history_processor` picks it up at the next model invocation. If the agent is idle, the message is added to the mailbox and a new run is enqueued. There is no "supersede" path — the supersede logic from the single-agent design is removed entirely in favor of mailbox interleaving.

### 6. Modifications to `run_agent_task`

The current `run_agent_task` needs the following changes:

1. **Accept `deps`**: Pass `AgentDeps` to the agent run so tools can access `conversation_id`, `agent_key`, and `team_agents`.
2. **Attach `history_processor`**: Create and attach the mailbox history processor before starting the agent stream.
3. **Post-run mailbox check**: After the stream completes, drain the mailbox. If non-empty, enqueue a follow-up run.
4. **Two run paths**: The task supports two entry modes:
   - **User-initiated run**: Triggered by `POST /chat/{conversation_id}`. The request body is a Vercel AI SDK payload processed through `VercelAIAdapter` as today.
   - **Mailbox-initiated run (wake-up)**: Triggered when an idle agent receives a mailbox message. No user request body exists. The task loads the latest `AgentRunSnapshot` from the DB (already in Pydantic AI `ModelMessage` format), drains the mailbox, appends mailbox messages as `ModelRequest` parts, and calls `agent.run_stream()` directly — **bypassing `VercelAIAdapter`** entirely. The streaming output is still published to Redis as SSE-encoded chunks so the existing frontend consumption path works unchanged.
5. **Remove supersede logic**: The `supersede_stale_runs` call is removed. All incoming messages (user or agent) go through the mailbox. If the agent is idle, a new run is started. If active, the mailbox is drained by the `history_processor`.

### 7. Database Changes

No schema changes are strictly required. The existing `ChatRun` and `AgentRunSnapshot` tables already support multiple agents via `agent_key` and shared `conversation_id`.

Optional additions for observability:

- **`AgentMessage` log table**: Record every inter-agent message for debugging. Fields: `id`, `conversation_id`, `sender_agent_key`, `receiver_agent_key`, `content`, `created_at`. This is write-only telemetry, not on the critical path.

### 8. Shared Task Pool (Optional / Phase 2)

A shared task board that all agents can read/write:

```python
class TeamTask(SQLModel, table=True):
    id: str                    # UUID
    conversation_id: str       # ties to the team
    title: str
    description: str | None
    status: str                # "open", "in_progress", "done"
    owner_agent_key: str | None
    created_by_agent_key: str
    created_at: datetime
    updated_at: datetime
```

Tools:

- `create_task(title, description, assign_to)` — Create a task, optionally assign to an agent.
- `list_tasks()` — List all tasks for the current conversation.
- `update_task(task_id, status, assign_to)` — Update status or reassign.
- `get_my_tasks()` — List tasks assigned to the calling agent.

This gives agents a structured way to coordinate work beyond free-text messages.

---

## Frontend Design

### 1. Multi-Column Layout

Replace the single `Chat` column with a **multi-column layout** where each agent gets its own independently scrolling chat column:

```
┌─────────────┬──────────────────────┬──────────────────────┐
│             │    SQL Agent          │    Arxiv Agent        │
│  Sidebar    │  ┌────────────────┐  │  ┌────────────────┐  │
│             │  │  messages...   │  │  │  messages...   │  │
│  (shared    │  │                │  │  │                │  │
│   across    │  │                │  │  │                │  │
│   team)     │  ├────────────────┤  │  ├────────────────┤  │
│             │  │  prompt input  │  │  │  prompt input  │  │
│             │  └────────────────┘  │  └────────────────┘  │
└─────────────┴──────────────────────┴──────────────────────┘
```

Each column is a self-contained chat instance:

- Has its own `useConversationChatState` hook (own `useChat`, own stream transport).
- Has its own `useChatSubmit` hook (own input state, own submit handler).
- Has its own `PromptInput` and message list.
- All columns share the same `conversationId`.

### 2. Routing

Add a team route that shows all agents side by side:

```
/team                         → empty state, no conversation
/team/chat/$conversationId    → multi-column view with shared conversationId
```

Individual agent routes (`/sql`, `/arxiv`) remain unchanged for standalone use.

### 3. Team Configuration

A new API endpoint or extension of the existing `/configure` endpoint:

```
GET /api/v1/team/configure
→ {
    agents: [
      { key: "sql", title: "SQL Agent", apiBasePath: "/api/v1/sql" },
      { key: "arxiv", title: "Arxiv Agent", apiBasePath: "/api/v1/arxiv" },
    ]
  }
```

The frontend fetches this to know which agent columns to render.

### 4. Sidebar in Team Mode

In team mode the sidebar shows **team conversations** (shared `conversationId`s). Since conversations are shared, the sidebar needs a combined listing:

- Fetch each agent's `/chats` and merge/deduplicate by `conversationId`.
- Or: add a dedicated `GET /api/v1/team/chats` endpoint that returns conversations across all agents.

The latter is cleaner and avoids N+1 calls.

### 5. New Conversation Flow

When a user creates a new conversation in team mode:

1. A single `conversationId` is generated (UUID).
2. The URL navigates to `/team/chat/{conversationId}`.
3. Each agent column initializes with empty history for that `conversationId`.
4. The user sends a message to any one agent — that agent's column starts streaming.
5. If that agent `tell`s another agent, the other column picks it up (via its stream/reconnect mechanism or polling).

### 6. Detecting Inter-Agent Activity

When agent A `tell`s agent B and triggers a new run for B, agent B's column needs to show the incoming stream.

Each idle agent column periodically polls `GET /chat/{conversationId}/stream`. If a run exists, it attaches. The current reconnect mechanism (`resumeStream`) already does this once on mount — we extend it with a lightweight polling interval (every 3–5 seconds) when the column's `useChat` status is `ready`.

Implementation: a `useAgentActivityPoller` hook that calls the stream endpoint on an interval. When it gets a non-204 response, it triggers `resumeStream()` and stops polling until the run finishes. On run finish, polling resumes.

### 7. Component Hierarchy

```
TeamPage
├── AppSidebar (team mode — shared conversation list)
└── TeamLayout (flex row of agent columns)
    ├── AgentColumn (agent_key="sql")
    │   └── Chat (apiBasePath="/api/v1/sql", conversationId=shared)
    └── AgentColumn (agent_key="arxiv")
        └── Chat (apiBasePath="/api/v1/arxiv", conversationId=shared)
```

The existing `Chat` component is reused as-is. `AgentColumn` is a thin wrapper that provides the agent-specific `apiBasePath` and column header. `TeamLayout` arranges columns horizontally.

---

## Implementation Plan

### Phase 1: Backend Multi-Agent Foundation

1. **Define `AgentDeps` dataclass** with `conversation_id`, `agent_key`, `team_agents`, and a reference to the Redis client.
2. **Implement mailbox** in Redis (push, drain, check-empty operations). Drain uses a Redis pipeline (LRANGE + DEL).
3. **Implement `tell` tool** as a shared tool registered on all team agents. Writes directly to Redis mailbox, enqueues wake-up task if target is idle.
4. **Add `history_processor`** that drains mailbox before each model invocation.
5. **Modify `run_agent_task`** to support two entry modes:
   - **User-initiated**: Vercel AI SDK request body through `VercelAIAdapter` (existing path).
   - **Mailbox-initiated (wake-up)**: Load persisted `ModelMessage` history from DB, drain mailbox, call `agent.run_stream()` directly (bypass adapter).
   - Both paths: attach `history_processor`, check mailbox after run completes, re-enqueue if non-empty.
6. **Replace supersede logic** with mailbox-only routing in `POST /chat/{conversation_id}`. If agent is active, push to mailbox and return 202. If idle, push to mailbox, enqueue run, return streaming response.
7. **Update system prompts** to inform agents about team members and the `tell` tool.

### Phase 2: Frontend Multi-Column + Safety

1. **Add team routes** (`/team`, `/team/chat/$conversationId`).
2. **Create `TeamLayout` component** that renders `Chat` per agent in a horizontal flex layout.
3. **Add team configure endpoint** (or extend existing) to return agent list.
4. **Modify `AppSidebar`** to support team mode with shared conversation list.
5. **Implement `useAgentActivityPoller`** hook — polls `GET /stream` every 3–5s when column is idle, triggers `resumeStream()` on non-204.
6. **Handle 202 responses** from `POST /chat/{conversation_id}` in the frontend (agent was active, message went to mailbox).
7. **Implement ping-pong safety cap** — hard limit on inter-agent messages per conversation per run cycle (e.g. 20). Track in `AgentDeps`.

### Phase 3: Shared Task Pool

1. **Add `TeamTask` table** and DB service functions.
2. **Implement task tools** (`create_task`, `list_tasks`, `update_task`, `get_my_tasks`).
3. **Frontend task panel** — a shared view showing the team's task board (optional).

---

## Risks and Concerns

### 1. Wake-Up Runs Bypass `VercelAIAdapter`

Mailbox-initiated runs (wake-ups) bypass `VercelAIAdapter` entirely. The persisted history is already in Pydantic AI `ModelMessage` format (from `AgentRunSnapshot.model_messages_json`), and mailbox messages are trivially converted to `ModelRequest` parts. The task calls `agent.run_stream()` directly with this history.

The streaming output must still be published to Redis as SSE-encoded chunks so the frontend can consume it through the existing `GET /stream` path. This means the wake-up path needs its own chunk encoding that produces the same SSE format as `VercelAIAdapter`'s event stream. Pydantic AI's `VercelAIAdapter` exposes `build_event_stream()` and `encode_event()` — these can potentially be used standalone without a full adapter instance, or we can replicate the minimal SSE encoding. This is an implementation detail to resolve during development.

### 2. Message Ordering and Duplication

The mailbox `drain` operation uses a Redis pipeline (LRANGE + DEL). Since drain is only called by the single worker that owns the run for this `(agent_key, conversation_id)`, there is no concurrent reader. A message arriving between LRANGE and DEL in the pipeline is not lost — it will be picked up by the next drain call within the same run (via `history_processor`) or by the post-run mailbox check.

### 3. Agent Referring to Itself

The `tell` tool must prevent an agent from sending a message to itself, which would create an infinite loop. Validate `agent != ctx.deps.agent_key`.

### 4. Infinite Ping-Pong Between Agents

Two agents could endlessly `tell` each other. Mitigations:

- System prompt guidance: instruct agents not to reply unless they have new information.
- Hard limit: cap the number of agent-to-agent messages per conversation (e.g. 20 per run, tracked in deps or mailbox).
- Token/cost budgets: existing model token limits naturally bound runs, but won't prevent many short runs.

This is primarily a prompt engineering concern but should have a safety valve at the infrastructure level. **Deferred to Phase 2** — implement the hard cap and monitoring after the core loop is working.

### 5. Frontend Polling Latency

Polling introduces a 3–5 second delay before a column becomes aware of an agent-to-agent run. This is acceptable for v1. Users will see the column "come alive" shortly after the other agent sends a message. If latency becomes a UX issue, upgrade to a shared SSE notification channel in a future phase.

### 6. Concurrent Mailbox Writes

Multiple agents may simultaneously `tell` the same target. Redis list operations (RPUSH) are atomic so individual pushes won't collide. The drain side has a single consumer (the owning worker), so no concurrent-reader issue exists.

### 7. Frontend /stream Endpoint Behavior

The current `GET /chat/{conversationId}/stream` returns 204 if no active run. The polling hook relies on this. If the endpoint behavior changes (e.g. returning a different status for "run completed but not yet snapshotted"), the polling logic would break. Keep the contract stable.

### 8. User Message While Agent Is Active

The supersede logic is removed entirely. `POST /chat/{conversation_id}` always routes through the mailbox:

- **Agent active:** Message is pushed to the mailbox. The running agent's `history_processor` picks it up at the next model invocation. The endpoint returns immediately (no streaming response needed since the existing run's stream is already open).
- **Agent idle:** Message is pushed to the mailbox and a new run is enqueued. The endpoint returns a streaming response for the new run as before.

The frontend must detect which case applies. If the agent is active, the POST returns a short non-streaming response (e.g. 202 Accepted). If the agent is idle, it returns the usual `StreamingResponse`. The frontend handles both: on 202, it knows the existing stream will carry the response; on streaming, it attaches as usual.

---

## Open Questions

1. **Team definition**: Where is the team composition defined? Hardcoded in `server.py` (like the current router mounting), a config file, or a DB table? For now, hardcoded is fine; a config file or DB table is a future improvement.

2. **Agent identity in messages**: When agent A receives a message from agent B, how is it rendered in A's message history? Currently modeled as `[Message from B]: ...` in a `UserPromptPart`. An alternative is to use a dedicated part type or metadata annotation so the frontend can render it distinctly (e.g. with a badge showing the sender agent).

3. **Data panel in team mode**: Each agent column currently supports its own data panel (SQL results, Arxiv papers). In team mode, do data panels stack? Do they share a single panel area? For now, we will not support data panels for teams. This can be added in a future phase once the core messaging loop is stable.

4. **Conversation deletion in team mode**: Deleting a team conversation should delete all agents' snapshots for that `conversationId`. This requires a cross-agent delete operation (loop over all agent keys or add a DELETE endpoint that ignores `agent_key`).

5. **SSE encoding for wake-up runs**: Wake-up runs bypass `VercelAIAdapter` and call `agent.run_stream()` directly. We need to produce the same SSE chunk format that the frontend expects. Determine whether `VercelAIAdapter.build_event_stream()` / `encode_event()` can be used standalone, or if we need a minimal encoding utility.
