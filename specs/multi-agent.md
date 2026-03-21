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

### Core Coordination Primitive: Redis Run Lease

For each `(agent_key, conversation_id)` pair there is exactly one Redis lease key that determines whether the agent is currently active:

```
Key format:  active-run:{agent_key}:{conversation_id}
Value type:  JSON payload containing at least run_id, state, and timestamps
```

This lease is the **single source of truth** for activity.

- If the lease exists and is valid, the agent is active.
- If the lease does not exist, the agent is idle.
- `ChatRun` records are retained for observability and history, but they are not used to decide whether an agent is active.

The lease must be acquired atomically with `SET key value NX EX <ttl>` and refreshed by the owning worker while it is running. Release must be compare-and-delete so one run cannot accidentally clear another run's lease.

### How Agents Communicate

Agents are made aware of each other through **system prompts** and a shared **`tell` tool**. When agent A wants to communicate with agent B, it calls `tell(agent="B", message="...")`. This tool:

1. Delivers the message to agent B's **mailbox** (a Redis list).
2. Returns immediately with `"Message sent to B."` — it does **not** block for a response.
3. Calls a shared `ensure_agent_run(agent_key, conversation_id)` helper.
4. If agent B is currently active (lease already held), nothing else happens; the running worker will pick up the message during its next model invocation via its `history_processor`.
5. If agent B is idle (no lease exists), `ensure_agent_run(...)` acquires the lease and starts exactly one new worker task for agent B.

There is intentionally no `ask` tool. If agent A needs information from B, it `tell`s B and either continues with other work or finishes with a message like "Waiting for B to respond." When B's response eventually arrives (via B calling `tell(agent="A", message="...")`), agent A is woken up or receives it in its mailbox.

---

## Backend Design

### 1. Mailbox-First Ingress

All incoming work for an agent goes through the mailbox first.

This includes:

- user messages from `POST /chat/{conversation_id}`
- agent-to-agent messages from `tell(...)`

There is no separate "normal request" path and no separate "wake-up" payload shape. The mailbox is the only ingress queue for conversational work.

Canonical flow:

```text
sender -> push_to_mailbox(...) -> ensure_agent_run(...) -> worker drains mailbox
```

This removes the current split between direct request handling and wake-up handling.

### 2. `tell` Tool

A single tool registered on every team-participating agent:

```python
@agent.tool
async def tell(ctx: RunContext[AgentDeps], agent: str, message: str) -> str:
    """Send a message to another agent in the team."""
```

**Implementation sketch:**

- Validate that `agent` is a known agent key (not the calling agent itself).
- Write `(sender_agent_key, message, timestamp)` to the target agent's mailbox in Redis.
- Call `ensure_agent_run(target_agent_key, conversation_id)`.
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

### 3. Mailbox

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
- `mailbox_is_empty(redis, agent_key, conversation_id)` — LLEN-based peek used only by the active worker to decide whether another loop iteration is needed.

### 4. Redis Run Lease / Mutex

Each `(agent_key, conversation_id)` pair has exactly one Redis lease key representing the active worker.

```python
@dataclass
class ActiveRunLease:
    run_id: str
    agent_key: str
    conversation_id: str
    state: Literal['starting', 'running']
    acquired_at: float
    heartbeat_at: float
```

**Required behavior:**

- Acquire with `SET key value NX EX <startup_ttl>`.
- Transition from `starting` to `running` when the worker begins execution.
- Refresh TTL periodically while the worker is alive.
- Release only if the stored `run_id` matches the caller's `run_id`.

This lease becomes the single source of truth for:

- `GET /chat/{conversation_id}/run`
- deciding whether a new worker should be started
- determining which stream key is currently active

`ChatRun` remains useful for durable audit state, but it is no longer the authority for active/inactive checks.

### 5. `ensure_agent_run(...)`

All senders call the same helper after writing to the mailbox:

```python
async def ensure_agent_run(agent_key: str, conversation_id: str) -> str | None:
    """Ensure a single worker is running for this agent conversation pair.

    Returns the new run_id if this call started a worker, else None.
    """
```

Semantics:

1. Try to acquire the Redis run lease.
2. If lease acquisition fails, return `None`.
3. If lease acquisition succeeds:
   - generate `run_id`
   - create a `ChatRun` record for observability
   - enqueue the single mailbox-driven worker task
   - return `run_id`

This helper is the only place allowed to start agent execution.

### 6. `history_processor` for Mailbox Interleaving

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

### 7. Single Mailbox-Driven Worker Task

There should be exactly one worker task entry point for conversational execution:

```python
@broker.task(task_name='chatbot.tasks.run_agent_mailbox')
async def run_agent_mailbox_task(
     run_id: str,
     conversation_id: str,
     agent_key: str,
) -> None:
     ...
```

This task always follows the same flow:

1. Validate that it still owns the Redis lease.
2. Load persisted conversation history from the latest snapshot.
3. Drain the mailbox.
4. If the mailbox is empty:
   - release the lease
   - mark the run completed without model execution
   - exit
5. Construct the adapter with an empty `SubmitMessage(id=conversation_id, messages=[])`.
6. Pass the explicit `message_history` (`persisted + drained mailbox`) into `adapter.run_stream(...)`.
7. Let the `history_processor` interleave any additional mailbox messages that arrive during the run.
8. After the model finishes a cycle, check the mailbox again:
   - if non-empty, continue another cycle in the **same worker task**
   - if empty, release the lease and finish

This removes the distinction between "request" runs and "wake-up" runs entirely.

### 8. Agent Active Detection

When a message arrives for an agent (via `tell` or a direct user message to the endpoint):

```
1. Push message to the agent's mailbox in Redis.
2. Call `ensure_agent_run(agent_key, conversation_id)`.
    - lease already exists → do nothing further
    - lease acquired now   → create one run and enqueue one worker
```

**Race condition mitigation:** No follow-up wake-up task is needed. The worker that already holds the lease remains active and loops until the mailbox is empty at the end of a cycle.

### 9. `tell` Delivery: Direct Redis + Taskiq (No HTTP Loopback)

The `tell` tool runs inside a Taskiq worker which already has access to Redis. It writes directly to the target agent's mailbox and then calls `ensure_agent_run(...)` — no HTTP round-trip required.

```python
# Inside the tell tool implementation:
await push_to_mailbox(redis_client, target_agent_key, conversation_id, message)
if not await has_active_run(db_session, target_agent_key, conversation_id):
    await enqueue_wake_up_run(target_agent_key, conversation_id)
```

HTTP endpoints are reserved for external callers (user frontend, external services).

**User messages while agent is active:** The `POST /chat/{conversation_id}` endpoint always routes incoming messages through the mailbox. If the agent has an active lease, the message is added to the mailbox and the running agent's `history_processor` picks it up at the next model invocation. If the agent is idle, the message is added to the mailbox and `ensure_agent_run(...)` starts one worker. There is no supersede path.

### 10. Request Path and Streaming Semantics

The HTTP route no longer decides between a "normal" run task and a separate wake-up task.

For `POST /chat/{conversation_id}`:

1. Normalize and validate the incoming Vercel AI request body.
2. Extract the final user message and append it to the mailbox.
3. Call `ensure_agent_run(agent_key, conversation_id)`.
4. If this call started a worker, return a streaming response for that `run_id`.
5. If a worker was already active, return `202 Accepted`.

The route does not pass the request body into the worker. The request body is used only to extract the new mailbox payload and any conversation-scoped runtime options that need to be captured at start time.

### 11. Model / Prompt Selection

Because mailbox processing is unified, model selection and system prompt override become run-scoped values chosen when a worker is started from idle.

- If the agent is idle, the request that acquires the lease defines the model and system prompt for that run.
- If the agent is already active, later mailbox messages do not change the currently running model or system prompt.

This behavior should be documented explicitly in the API contract.

### 12. Modifications to `run_agent_task`

The current `run_agent_task` should be replaced by a single mailbox-driven worker implementation:

1. **Accept `deps`**: Pass `AgentDeps` so tools can access `conversation_id`, `agent_key`, and `team_agents`.
2. **Use an empty adapter input**: Always construct `VercelAIAdapter` with `SubmitMessage(id=conversation_id, messages=[])`.
3. **Always pass explicit history**: Load persisted `ModelMessage` history and append drained mailbox messages.
4. **Attach `history_processor`**: Continue draining mailbox before each model invocation.
5. **Loop until idle**: When a cycle completes, keep the same worker alive if the mailbox has filled again.
6. **Own the lease**: Refresh and release the Redis run lease in this task.
7. **Remove request/wake-up split**: There should be one worker task path only.

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
3. **Implement Redis run lease** keyed by `(agent_key, conversation_id)` with acquire, refresh, inspect, and compare-and-release helpers.
4. **Implement `ensure_agent_run(...)`** so every sender uses one code path to start work if and only if no lease exists.
5. **Implement `tell` tool** as a shared tool registered on all team agents. Writes directly to mailbox, then calls `ensure_agent_run(...)`.
6. **Replace direct request execution** with mailbox-only routing in `POST /chat/{conversation_id}`. The route pushes the user message to the mailbox, calls `ensure_agent_run(...)`, then either streams the new run or returns 202.
7. **Replace request/wake-up split** with one mailbox-driven worker task that always builds history from snapshot + drained mailbox messages.
8. **Add `history_processor`** that drains mailbox before each model invocation.
9. **Update run-status and stream attachment logic** to use the Redis lease as the single source of truth.
10. **Update system prompts** to inform agents about team members and the `tell` tool.

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

### 1. Redis Lease Robustness

The lease needs a heartbeat/TTL strategy so a crashed worker does not leave the agent permanently active.

- `starting` state should use a short TTL.
- `running` state should use a renewable TTL refreshed periodically by the worker.
- Release must be compare-and-delete to avoid clearing another worker's lease.

### 2. `VercelAIAdapter` and Explicit History

The unified design always constructs `VercelAIAdapter` with an empty `SubmitMessage` and supplies the full effective history via `message_history`. This avoids duplicated message feeds and removes the need to infer whether a run was user-initiated or mailbox-initiated.

### 3. Message Ordering and Duplication

The mailbox `drain` operation uses a Redis pipeline (LRANGE + DEL). Since drain is only called by the single worker that owns the run for this `(agent_key, conversation_id)`, there is no concurrent reader. A message arriving between LRANGE and DEL in the pipeline is not lost — it will be picked up by the next drain call within the same run (via `history_processor`) or by the post-run mailbox check.

### 4. Agent Referring to Itself

The `tell` tool must prevent an agent from sending a message to itself, which would create an infinite loop. Validate `agent != ctx.deps.agent_key`.

### 5. Infinite Ping-Pong Between Agents

Two agents could endlessly `tell` each other. Mitigations:

- System prompt guidance: instruct agents not to reply unless they have new information.
- Hard limit: cap the number of agent-to-agent messages per conversation (e.g. 20 per run, tracked in deps or mailbox).
- Token/cost budgets: existing model token limits naturally bound runs, but won't prevent many short runs.

This is primarily a prompt engineering concern but should have a safety valve at the infrastructure level. **Deferred to Phase 2** — implement the hard cap and monitoring after the core loop is working.

### 6. Frontend Polling Latency

Polling introduces a 3–5 second delay before a column becomes aware of an agent-to-agent run. This is acceptable for v1. Users will see the column "come alive" shortly after the other agent sends a message. If latency becomes a UX issue, upgrade to a shared SSE notification channel in a future phase.

### 7. Concurrent Mailbox Writes

Multiple agents may simultaneously `tell` the same target. Redis list operations (RPUSH) are atomic so individual pushes won't collide. The drain side has a single consumer (the owning worker), so no concurrent-reader issue exists.

### 8. Frontend /stream Endpoint Behavior

The current `GET /chat/{conversationId}/stream` should consult the Redis run lease for the current `run_id`. The polling hook relies on the endpoint returning 204 when no lease exists.

### 9. User Message While Agent Is Active

The supersede logic is removed entirely. `POST /chat/{conversation_id}` always routes through the mailbox:

- **Agent active (lease exists):** Message is pushed to the mailbox. The running agent's `history_processor` picks it up at the next model invocation. The endpoint returns immediately with 202.
- **Agent idle (no lease):** Message is pushed to the mailbox, the route acquires the lease via `ensure_agent_run(...)`, and returns a streaming response for the newly started run.

The frontend must detect which case applies. If the agent is active, the POST returns a short non-streaming response (e.g. 202 Accepted). If the agent is idle, it returns the usual `StreamingResponse`. The frontend handles both: on 202, it knows the existing stream will carry the response; on streaming, it attaches as usual.

---

## Open Questions

1. **Team definition**: Where is the team composition defined? Hardcoded in `server.py` (like the current router mounting), a config file, or a DB table? For now, hardcoded is fine; a config file or DB table is a future improvement.

2. **Agent identity in messages**: When agent A receives a message from agent B, how is it rendered in A's message history? Currently modeled as `[Message from B]: ...` in a `UserPromptPart`. An alternative is to use a dedicated part type or metadata annotation so the frontend can render it distinctly (e.g. with a badge showing the sender agent).

3. **Data panel in team mode**: Each agent column currently supports its own data panel (SQL results, Arxiv papers). In team mode, do data panels stack? Do they share a single panel area? For now, we will not support data panels for teams. This can be added in a future phase once the core messaging loop is stable.

4. **Conversation deletion in team mode**: Deleting a team conversation should delete all agents' snapshots for that `conversationId`. This requires a cross-agent delete operation (loop over all agent keys or add a DELETE endpoint that ignores `agent_key`).

5. **Run options while active**: If a second user request arrives while the agent is active, the message is mailboxed, but model selection / system prompt override should not change the in-flight run. This needs to be explicit in the request contract and UI behavior.
