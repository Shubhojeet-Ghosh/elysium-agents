# Email Flow — Node Reference (Flow Builder & I/O)

Per-node guide for the **`@xyflow/react` flow builder** and backend **input/output contract**. Node handlers are built one at a time and share data through **`FlowContext`** so they can be joined into a single `run_flow` later.

**Status:** Living document — expanded as each node ships.

**Related:**
- [email-flow-plan.md](./email-flow-plan.md) — full architecture, Mongo models, phases
- [email-flow-reprocess-thread-api.md](./email-flow-reprocess-thread-api.md) — reprocess-thread test API
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — agents, sync
- [email-threads-api.md](./email-threads-api.md) — inbox list, get-thread, send draft

**Library:** [`@xyflow/react`](https://reactflow.dev) v12 (`^12.11.0`)

---

## 1. Flow builder overview

### 1.1 Nodes on the canvas

Register one React component per backend `type`. The `type` string must match exactly on both sides.

```javascript
import { ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

const nodeTypes = {
  start: StartNode,
  load_thread_context: LoadThreadContextNode,
  read_kb: ReadKbNode,
  read_tools: ReadToolsNode,
  ai_department_router: DepartmentRouterNode,
  ai_recipients_generator: RecipientsNode,
  generate_email: GenerateEmailNode,
  call_external_tool: ExternalToolNode,
  save_gmail_draft: SaveGmailDraftNode,
  send_email: SendEmailNode,
  stop: StopNode,
};
```

| `type` | Canvas label | Status |
| ------ | ------------ | ------ |
| `start` | Start | **Implemented** (backend) |
| `load_thread_context` | Load Thread Context | **Implemented** (backend) |
| `read_kb` | Read KB | **Implemented** (backend) |
| `read_tools` | Read Tools | **Implemented** (backend) |
| `ai_department_router` | AI Department Router | **Implemented** (backend) |
| `ai_recipients_generator` | AI Recipients Generator | **Implemented** (backend) |
| `generate_email` | Generate Email | **Implemented** (backend) |
| `call_external_tool` | Call External Tool | **Implemented** (backend) |
| `save_gmail_draft` | Save Gmail Draft | **Implemented** (backend, tail when `mode: draft`) |
| `send_email` | Send Email | **Implemented** (backend, tail when `mode: auto_send`) |
| `stop` | Stop | **Implemented** (backend) |

**Not on canvas:** `system_prompt` — edited in **agent settings** only; backend copies it into context at **Start**.

**Tail nodes:** only **one** of `save_gmail_draft` or `send_email` per agent, based on `agent.reply_action.mode`.

### 1.2 Default graph order

```
start → load_thread_context → read_kb → read_tools → ai_department_router
  → ai_recipients_generator → generate_email
  → save_gmail_draft | send_email → call_external_tool (optional) → stop
```

MVP subset: `start → load_thread_context → read_kb → generate_email → tail → stop`

### 1.3 JSON shape (saved flow ↔ React Flow)

**Mongo / execution shape:**

```json
{
  "node_id": "load_thread_context",
  "type": "load_thread_context",
  "label": "Load Thread Context",
  "position": { "x": 250, "y": 100 },
  "config": { "message_limit": 10 },
  "edges": [{ "to": "read_kb" }]
}
```

**React Flow shape** (after adapter):

```json
{
  "id": "load_thread_context",
  "type": "load_thread_context",
  "position": { "x": 250, "y": 100 },
  "data": {
    "label": "Load Thread Context",
    "config": { "message_limit": 10 },
    "binding": { "inbox_email": "support@company.com" }
  }
}
```

| Mongo field | React Flow field |
| ----------- | ---------------- |
| `node_id` | `id` |
| `type` | `type` |
| `label` | `data.label` |
| `config` | `data.config` |
| `binding` (hydrated on load) | `data.binding` |
| `position` | `position` |
| `edges[].to` | `edges[]` (`source` / `target`) |

### 1.4 Adapter helpers (frontend owns)

```javascript
function flowDocToReactFlow(flowNodes) {
  const nodes = flowNodes.map((n) => ({
    id: n.node_id,
    type: n.type,
    position: n.position ?? { x: 0, y: 0 },
    data: {
      label: n.label ?? n.type,
      config: n.config ?? {},
      binding: n.binding ?? {},
    },
  }));

  const edges = flowNodes.flatMap((n) =>
    (n.edges ?? []).map((e) => ({
      id: `${n.node_id}-${e.to}`,
      source: n.node_id,
      target: e.to,
      type: "smoothstep",
    })),
  );

  return { nodes, edges };
}

function reactFlowToFlowDoc(rfNodes, rfEdges) {
  const edgeMap = rfEdges.reduce((acc, e) => {
    (acc[e.source] ??= []).push({ to: e.target });
    return acc;
  }, {});

  return rfNodes.map((n) => ({
    node_id: n.id,
    type: n.type,
    label: n.data?.label ?? n.type,
    position: n.position,
    config: n.data?.config ?? {},
    edges: edgeMap[n.id] ?? [],
  }));
}
```

### 1.5 Canvas modes

| Mode | Who | React Flow props |
| ---- | --- | ---------------- |
| **Preview** | All users (default flow) | `nodesDraggable={false}` `nodesConnectable={false}` `edgesReconnectable={false}` |
| **Editor** | Power users (custom flow) | Default drag/connect; save `position` + `edges` + `config` on flow save |

System default flow (`is_deletable: false`) → preview only.

### 1.6 Full node checklist (flow builder)

| `type` | Component | `data.binding` (chips on node) | `data.config` (side panel) | Editable on custom flow? |
| ------ | --------- | ------------------------------ | -------------------------- | ------------------------ |
| `start` | `StartNode` | — | — | No |
| `load_thread_context` | `LoadThreadContextNode` | Inbox email | `message_limit` | `message_limit` only |
| `read_kb` | `ReadKbNode` | KB title + id | `knowledge_id`, `limit` | Yes — syncs `knowledge_id` to agent |
| `read_tools` | `ReadToolsNode` | Tool names | `tool_ids`, `max_tool_calls` | Yes — syncs `tool_ids` to agent |
| `ai_department_router` | `DepartmentRouterNode` | e.g. `3 active rules` | — | No — link to routing rules admin |
| `ai_recipients_generator` | `RecipientsNode` | e.g. `2 active rules` | — | No — link to recipient rules admin |
| `generate_email` | `GenerateEmailNode` | Model badge | `format_prompt`, `llm_model` | Yes — `llm_model` syncs to agent |
| `call_external_tool` | `ExternalToolNode` | Post-draft tool names | `external_tools[]` | Yes — flow-only |
| `save_gmail_draft` | `SaveGmailDraftNode` | `Draft only` | `reply_action` | Tail — when `mode: draft` |
| `send_email` | `SendEmailNode` | `Auto-send ≥ 0.8` | `reply_action` | Tail — when `mode: auto_send` |
| `stop` | `StopNode` | — | — | No |

**Agent settings (not on canvas):** `system_prompt`, `name`, `gmail_account_id`

---

## 2. Backend contract (for joining nodes)

Handlers share one signature so `run_flow` can chain them:

```python
async def execute_<type>_node(context, config, agent) -> tuple[context, node_log]
```

Nodes read/write **`FlowContext`** — never call each other directly. When adding a node, only **add** keys; do not rename existing ones.

```python
context = {
    "run_id", "agent_id", "team_id", "thread_id", "trigger_message_id",
    "system_prompt", "compressed_query", "thread",
    "kb_chunks", "registered_tools", "tools_planned", "tool_results",
    "routing", "recipients",
    "draft", "final_action", "errors",
}
```

---

## 3. Node: `start`

### Flow builder — `StartNode`

| Item | Detail |
| ---- | ------ |
| Position | Always first node in graph |
| `data.label` | `Start` |
| `data.config` | `{}` — no side panel |
| `data.binding` | None |
| User actions | None — fixed entry point |
| Visual | Simple start icon; no chips |

### Backend I/O

**Reads:** `agent_id`, `thread_id`, `trigger_message_id` (from run trigger); loads agent + trigger message.

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `run_id` | Run UUID |
| `agent_id`, `team_id`, `thread_id` | Identifiers |
| `trigger_message_id` | Resolved Mongo message `_id` |
| `system_prompt` | From `agent.system_prompt` |
| `trigger_message` | Minimal trigger metadata |

**Preconditions (sync trigger):** agent active; trigger inbound; `processing_status === "pending"`; no existing `flow_run_id`.

**Reprocess (manual / test):** `force_reprocess: true` skips pending-only checks — allows re-running on an already-processed thread.

**Status:** handler implemented (`nodes/start_node.py`).

---

## 4. Node: `load_thread_context`

### Flow builder — `LoadThreadContextNode`

| Item | Detail |
| ---- | ------ |
| Position | After `start`, before `read_kb` |
| `data.label` | `Load Thread Context` |
| `data.binding` | `inbox_email` — e.g. chip `Inbox: support@company.com` (from agent, read-only) |
| `data.config.message_limit` | Number input in side panel; default `10` |
| Preview mode | Show label + inbox chip only |
| Editor mode | Power user can change `message_limit` |
| On save | Persist `config.message_limit` in flow document |

**Do not show on this node:** thread content, messages, or `compressed_query` — runtime only.

### Backend I/O

**Reads from context:** `thread_id`, `team_id`, `trigger_message_id`

**Reads from agent:** `gmail_account_id`

**Reads from `config`:** `message_limit` (default `10`)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `thread` | Full conversation (see below) |
| `compressed_query` | LLM-generated dense summary of the thread for KB / tools / routing |
| `compressed_query_meta` | `{ source: "llm" \| "fallback", model, attempts }` |
| `trigger_message` | Trimmed trigger inbound |
| `trigger_message_id` | Resolved id |

### `compressed_query` — LLM compression (gpt-4.1-mini)

After loading up to **10 messages**, **Load Thread Context** calls `compress_thread_query_with_llm()` (`email_thread_compress_llm_services.py`):

- Passes **thread subject** + each message **`body_text`** (full body, not snippet; quote-trim **not** applied here)
- **Per-email cap:** 12,000 characters (only truncates extremely long single emails)
- Flags on each email in the LLM payload:
  - `IS_LATEST_ARRIVAL=true` — chronologically last message in the batch
  - `IS_TRIGGER_MESSAGE=true` — message that triggered this run
  - `IS_NEW_SYNC=true` — inbound with `processing_status=pending`
- **Model:** `gpt-4.1-mini` via `openai_chat_completion_non_reasoning`
- **Retries:** up to 3 attempts; falls back to rule-based `build_compressed_query()` if all fail

Downstream nodes (**Read KB**, **Read Tools**, routers) use `context.compressed_query` only — not the raw thread bodies.

**Example — what the LLM receives (2-message thread):**

```text
THREAD_SUBJECT: Refund request — Order #ORD-8821
MESSAGE_COUNT: 2

--- Email 1 of 2 ---
Direction: outbound
From: support@company.com
Received: 2026-06-06T09:00:00+00:00
IS_LATEST_ARRIVAL=false | IS_TRIGGER_MESSAGE=false
Body:
Hi Jane,

Thanks for contacting us. To process a refund we need your order number and a photo of the damaged item.

Best,
Support Team

--- Email 2 of 2 ---
Direction: inbound
From: jane@customer.com
Received: 2026-06-07T10:15:00+00:00
IS_LATEST_ARRIVAL=true | IS_TRIGGER_MESSAGE=true | IS_NEW_SYNC=true
Body:
Hi,

Order #ORD-8821 placed on June 1st. The ceramic vase arrived shattered. I need a full refund to my Visa ending 4242. Please confirm within 48 hours.

Thanks,
Jane

Write the single compressed retrieval query for this thread now. Include all important facts from every email above.
```

**Example — LLM output (`compressed_query`):**

```text
Customer Jane requests a full refund for order ORD-8821 placed June 1. Ceramic vase arrived shattered. Refund to Visa ending 4242. Support previously asked for order number and damage photo; customer provided order ID and damage details. Customer wants confirmation within 48 hours. Thread subject: refund request order ORD-8821.
```

`node_log.output.llm_input_preview` on a flow run contains the exact payload sent for debugging.

**`context.thread` (runtime):**

```json
{
  "thread_id": "...",
  "subject": "Refund request",
  "participants": ["customer@example.com", "support@company.com"],
  "message_count": 5,
  "messages_loaded": 5,
  "new_message_count": 1,
  "department_id": "",
  "assigned_user_id": "",
  "messages": [
    {
      "message_id": "...",
      "direction": "inbound",
      "body_text": "...",
      "is_new": true,
      "is_trigger": true
    }
  ],
  "latest_inbound": {}
}
```

| Message flag | Meaning |
| ------------ | ------- |
| `is_new` | Inbound + `processing_status === "pending"` (just synced) |
| `is_trigger` | Message that triggered this run |

**Downstream:** `read_kb` uses `compressed_query`; `generate_email` uses `thread` + `kb_chunks`.

**Status:** handler implemented (`nodes/load_thread_context_node.py`).

---

## 5. Node: `read_kb`

### Flow builder — `ReadKbNode`

| Item | Detail |
| ---- | ------ |
| Position | After `load_thread_context`, before `read_tools` |
| `data.label` | `Read KB` |
| `data.binding` | KB title + `knowledge_id` chip (from agent, hydrated on load) |
| `data.config` | `knowledge_id`, `limit` (default `5`) |
| Preview mode | Show label + KB binding chip |
| Editor mode | Power user can change KB picker + limit |
| On save | `knowledge_id` syncs to agent |

### Backend I/O

**Reads from context:** `compressed_query` (from Load Thread Context — required)

**Reads from agent:** `knowledge_id` (or `config.knowledge_id` on custom flow)

**Reads from `config`:** `limit` (default `5`)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `kb_chunks` | Top matching Qdrant chunks (max 5) |
| `kb_title` | Knowledge base title from Mongo |
| `kb_knowledge_id` | Resolved knowledge id used for search |

**`context.kb_chunks[]` shape:**

```json
[
  {
    "text_index": 0,
    "text_content": "Refunds are processed within 5–7 business days...",
    "score": 0.89
  }
]
```

**How retrieval works:**

1. Embed `compressed_query` with `text-embedding-3-small` (same model used when KB was indexed)
2. Vector search Qdrant collection `email-knowledge`, filtered by `knowledge_id`
3. Return top **5** chunks via `retrieve_relevant_knowledge_chunks()`

**Skip (not fail):** if `knowledge_id` is empty → `kb_chunks = []`, node status `skipped`, pipeline continues.

**Fail:** if `compressed_query` is empty, knowledge not found, embedding fails, or Qdrant errors.

**Downstream:** `read_tools` and `generate_email` use `kb_chunks`.

**Status:** handler implemented (`nodes/read_kb_node.py`).

---

## 6. Node: `read_tools`

### Flow builder — `ReadToolsNode`

| Item | Detail |
| ---- | ------ |
| Position | After `read_kb`, before `ai_department_router` |
| `data.label` | `Read Tools` |
| `data.binding` | Comma-separated tool display names (from `agent.tool_ids`) |
| `data.config` | `tool_ids`, `max_tool_calls` (default `3`) |
| Preview mode | Show label + tool name chips |
| Editor mode | Tool multi-select + max calls |
| On save | `tool_ids` syncs to agent |

### Backend I/O

**Reads from context:** `compressed_query` (required), `kb_chunks`, `kb_title`, `thread`

**Reads from agent:** `tool_ids`, `llm_model` (must be `gpt-5.4` or `gpt-5.5` for this prototype)

**Reads from `config`:** `tool_ids` (override), `max_tool_calls` (default `3`)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `registered_tools` | Active tools available this run (`tool_id`, `tool_name`, `display_name`) |
| `tools_planned` | LLM-selected tool calls before execution |
| `tool_results` | Full HTTP/API results per executed tool — used by `generate_email` like `kb_chunks` |

**`context.registered_tools[]` shape** (tools available to the LLM this run):

```json
[
  {
    "tool_id": "6a250f67d4d86ab7f86bb635",
    "tool_name": "get_ticket_status",
    "display_name": "Get Ticket Status",
    "status": "active"
  }
]
```

**`context.tools_planned[]` shape** (LLM decision — may be empty):

```json
[
  {
    "tool_call_id": "call_abc",
    "tool_id": "6a250f67d4d86ab7f86bb635",
    "tool_name": "get_ticket_status",
    "display_name": "Get Ticket Status",
    "arguments": { "ticket_number": "TKT-1001" }
  }
]
```

**`context.tool_results[]` shape:**

```json
[
  {
    "tool_id": "6a250f67d4d86ab7f86bb635",
    "tool_name": "get_ticket_status",
    "display_name": "Get Ticket Status",
    "arguments": { "ticket_number": "TKT-1001" },
    "called": true,
    "success": true,
    "http_success": true,
    "status_code": 200,
    "message": "Ticket status fetched successfully.",
    "response": {
      "success": true,
      "message": "Ticket status fetched successfully.",
      "ticket": {
        "ticket_number": "TKT-1001",
        "status": "in_progress",
        "remarks": "Our support team is reviewing your refund request...",
        "expected_resolution_due_date": "2026-06-15",
        "created_at": "2026-06-01T10:00:00+00:00"
      }
    }
  }
]
```

Failed lookup example (`response` still stored for downstream LLM):

```json
{
  "tool_id": "6a250f67d4d86ab7f86bb635",
  "tool_name": "get_ticket_status",
  "success": false,
  "status_code": 404,
  "message": "No ticket found for this ticket number.",
  "response": {
    "success": false,
    "message": "No ticket found for this ticket number."
  }
}
```

**Run log audit fields (`node_logs[].output`):**

| Field | Meaning |
| ----- | ------- |
| `tools_registered` | Whether any tools were configured/resolved |
| `configured_tool_ids` | Raw `tool_ids` from agent / node config |
| `registered_tools` | Active tools loaded from Mongo this run |
| `tools_registered_count` | Count of active resolved tools |
| `llm_decision` | `skipped` \| `no_call` \| `called` |
| `tool_calls_requested` | Tool calls returned by LLM |
| `tool_calls_executed` | HTTP calls actually made |
| `tools_planned` | Same as `context.tools_planned` |
| `tool_results` | Same as `context.tool_results` (full API bodies) |
| `tool_executions` | Compact audit per call: `tool_id`, `tool_name`, `success`, `message`, `response` |

**Outcome matrix:**

| Situation | Node `status` | `llm_decision` | `tool_results` |
| --------- | ------------- | -------------- | -------------- |
| No `tool_ids` on agent | `skipped` | `skipped` | `[]` |
| `tool_ids` set but none active/found | `skipped` | `skipped` | `[]` |
| Tools loaded, LLM calls none | `ok` | `no_call` | `[]` |
| Tools loaded, LLM calls tool(s) | `ok` | `called` | full API responses |
| Bad `llm_model` / LLM error | `failed` | — | prior keys unchanged |

**LLM messages (planning call):**

| Role | Content |
| ---- | ------- |
| **System** | `EMAIL_TOOLS_PLANNING_SYSTEM_PROMPT` — fixed tool-routing instructions only (not agent reply `system_prompt`) |
| **User** | Subject + `compressed_query` + KB title/snippets |
| **Tools** | Each registered tool's `name`, `description`, `input_schema` |

**Example — user message sent to LLM:**

```text
Email subject: Ticket status update for TKT-1001

Compressed thread context:
Customer John asks for status of support ticket TKT-1001 submitted June 1 regarding refund for order ORD-8821. Prior outbound email asked for ticket number; customer provided TKT-1001 in latest inbound message.

Knowledge base: Return Policy
Knowledge snippets:
[1] Refunds are processed within 5–7 business days after approval...

Decide whether any registered tool should be called now to gather facts for the reply.
```

**Example — `node_log.output` when LLM calls a tool (`status: ok`, `llm_decision: called`):**

```json
{
  "tools_registered": true,
  "configured_tool_ids": ["6a250f67d4d86ab7f86bb635"],
  "registered_tools": [
    {
      "tool_id": "6a250f67d4d86ab7f86bb635",
      "tool_name": "get_ticket_status",
      "display_name": "Get Ticket Status",
      "status": "active"
    }
  ],
  "llm_decision": "called",
  "llm_model": "gpt-5.4",
  "tool_calls_requested": 1,
  "tool_calls_executed": 1,
  "tool_executions": [
    {
      "tool_id": "6a250f67d4d86ab7f86bb635",
      "tool_name": "get_ticket_status",
      "display_name": "Get Ticket Status",
      "arguments": { "ticket_number": "TKT-1001" },
      "success": true,
      "message": "Ticket status fetched successfully.",
      "response": {
        "success": true,
        "message": "Ticket status fetched successfully.",
        "ticket": {
          "ticket_number": "TKT-1001",
          "status": "in_progress",
          "remarks": "Our support team is reviewing your refund request...",
          "expected_resolution_due_date": "2026-06-15",
          "created_at": "2026-06-01T10:00:00+00:00"
        }
      }
    }
  ]
}
```

**Example — `node_log.output` when tools registered but LLM calls none (`status: ok`, `llm_decision: no_call`):**

```json
{
  "tools_registered": true,
  "registered_tools": [{ "tool_id": "...", "tool_name": "get_ticket_status", "display_name": "Get Ticket Status" }],
  "llm_decision": "no_call",
  "tool_calls_requested": 0,
  "tool_calls_executed": 0,
  "tools_planned": [],
  "tool_results": [],
  "tool_executions": []
}
```

**Example — `node_log.output` when agent has no tools (`status: skipped`):**

```json
{
  "tools_registered": false,
  "configured_tool_ids": [],
  "registered_tools": [],
  "llm_decision": "skipped",
  "skip_reason": "No tool_ids on agent or node config.",
  "tool_calls_requested": 0,
  "tool_calls_executed": 0
}
```

**Terminal logs** (grep `read_tools` / `Read Tools` in server output):

```text
read_tools_node started thread_id=... tool_ids=['6a250f67...'] llm_model=gpt-5.4
Read Tools registered tool: id=6a250f67... name=get_ticket_status display=Get Ticket Status
Read Tools LLM planning succeeded ... tool_calls=1 tools=['get_ticket_status']
Tool HTTP request: method=POST url=http://localhost:7000/.../get-ticket-status arguments={'ticket_number': 'TKT-1001'}
Tool HTTP response: status_code=200 success=True message=Ticket status fetched successfully.
read_tools_node tool execution: id=6a250f67... name=get_ticket_status success=True ...
```

**How it works:**

1. Load active tool definitions from Mongo (`email-tools`) for `tool_ids`
2. Build OpenAI tool schemas from each tool's `name`, `description`, `input_schema`
3. **LLM planning call** using `agent.llm_model` (`gpt-5.4` / `gpt-5.5` reasoning) with:
   - **System:** fixed tool-planning prompt (`EMAIL_TOOLS_PLANNING_SYSTEM_PROMPT`) — not the agent reply `system_prompt`
   - **User:** `compressed_query` + KB snippets + subject
4. LLM decides zero or more tool calls (`tool_choice: auto`)
5. Execute each planned call via HTTP to the tool's `endpoint_url` / `http_method`
6. Store results in `context.tool_results` (individual HTTP failures do not fail the node)

**Skip (not fail):**

- No `tool_ids` on agent → empty `tools_planned` / `tool_results`, status `skipped`
- `tool_ids` configured but none resolve as active team tools → skipped

**Fail:**

- `compressed_query` empty
- `llm_model` missing or not `gpt-5.4` / `gpt-5.5`
- LLM planning fails after retries

**LLM zero-tool case:** status `ok`, `llm_decision: no_call`, empty `tools_planned` / `tool_results` — LLM decided no tool was needed (e.g. customer asked about refund policy but did not provide a ticket number).

**Downstream usage:**

| Node | Reads from `read_tools` |
| ---- | ----------------------- |
| `generate_email` | `tool_results[].response` — inject ticket data, API errors, etc. into reply LLM prompt (alongside `thread`, `kb_chunks`, agent `system_prompt`) |
| `ai_department_router` | `thread.messages` (last 5 emails) + agent `routing_rule_ids` |

**Source files:**

| File | Role |
| ---- | ---- |
| `nodes/read_tools_node.py` | Node handler — skip/load/plan/execute, writes context + `node_log` |
| `email_read_tools_llm_services.py` | LLM planning (`EMAIL_TOOLS_PLANNING_SYSTEM_PROMPT`), orchestrates execution |
| `email_external_tools/email_tool_http_executor_services.py` | HTTP calls to tool `endpoint_url` |
| `email_tool_definitions/email_tool_schema_builder.py` | `build_llm_tool_definition()` for OpenAI tool schemas |

**Status:** handler implemented (`nodes/read_tools_node.py`), LLM service in `email_read_tools_llm_services.py`.

---

## 7. Node: `ai_department_router`

### Flow builder — `DepartmentRouterNode`

| Item | Detail |
| ---- | ------ |
| Position | After `read_tools`, before `ai_recipients_generator` |
| `data.label` | `AI Department Router` |
| `data.binding` | `N routing rules` chip (from `agent.routing_rule_ids`) |
| `data.config` | `routing_rule_ids` (optional override) |
| Preview mode | Show label + rule count |
| Editor mode | Read-only link to routing-rules admin |
| On save | `routing_rule_ids` syncs to agent |

### Backend I/O

**Reads from context:** `thread.messages` (last 5 emails), `thread.subject`

**Reads from agent:** `routing_rule_ids`, `llm_model` (`gpt-5.4` / `gpt-5.5`), `gmail_account_id`

**Reads from `config`:** `routing_rule_ids` (override)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `routing.department_id` | Selected department Mongo id, or `""` when no route |
| `routing.routing_rule_id` | Matched rule id (when known) |
| `routing.rule_name` | Matched rule name |
| `routing.decision_source` | How the department was chosen (see matrix below) |
| `routing.reason` | Human-readable routing note |
| `thread.department_id` | Mirrored when a department is resolved |

Also updates `email-threads.department_id` in Mongo when `routing.department_id` is non-empty.

**`context.routing` shape:**

```json
{
  "department_id": "6a2358e3ab87d80a66e0e6cc",
  "routing_rule_id": "6a25274367600dee9c13158c",
  "rule_name": "Claim Requests",
  "decision_source": "llm_matched",
  "reason": "LLM matched department."
}
```

**LLM output contract:**

```json
{ "department_id": "6a2358e3ab87d80a66e0e6cc" }
```

or explicit no-match:

```json
{ "department_id": null }
```

**Decision matrix (`routing.decision_source`):**

| `decision_source` | Meaning | `department_id` |
| ----------------- | ------- | --------------- |
| `skipped` | No `routing_rule_ids` or no active rules resolved | `""` |
| `llm_matched` | LLM returned a valid `department_id` from the rule set | set |
| `llm_no_match` | LLM successfully returned `null` — no rule clearly applies | `""` |
| `fallback_rule` | LLM/parsing failed after 3 retries; used `is_fallback=true` rule | fallback dept |
| `safety_empty` | LLM/parsing failed and no fallback rule available | `""` |

**Priority rule (explained to LLM):** when multiple rules appear to match, the rule with the **lowest `priority` number** wins (priority `10` beats `50`).

**How it works:**

1. Load active routing rules from Mongo for `agent.routing_rule_ids`
2. Send **all** active agent routing rules to the LLM (`llm_rules_sent_to_model`). `is_fallback` does **not** exclude a rule from LLM matching.
3. Keep one **programmatic fallback** rule (`is_fallback=true`, lowest priority) — used only when LLM/parsing fails after retries, not when LLM returns `null`.
4. **LLM call** (`gpt-5.4` / `gpt-5.5`) with:
   - **System:** `EMAIL_DEPARTMENT_ROUTER_SYSTEM_PROMPT`
   - **User:** last 5 thread emails (emphasis on latest inbound) + rule fields for LLM (`department_id`, `rule_name`, `priority`, `routing_prompt`) — not `routing_rule_id` or `is_fallback` (resolved server-side)
5. Parse JSON with Pydantic + JSON fallback parser (max **3 retries**)
6. Validate `department_id` is in the allowed rule set (or `null`)
7. On valid `null` → leave department empty (`llm_no_match`) — **not** an error
8. On retry exhaustion → use programmatic `fallback_rule` if configured, else `safety_empty`

**Skip (not fail):**

- No `routing_rule_ids` on agent
- `routing_rule_ids` configured but none resolve as active team rules

**Fail:**

- `llm_model` missing or not `gpt-5.4` / `gpt-5.5`
- Unexpected exception in node handler

**Run log audit (`node_logs[].output`):**

| Field | Meaning |
| ----- | ------- |
| `routing_rules_registered` | Whether rules were configured |
| `configured_routing_rule_ids` | Raw ids from agent |
| `registered_routing_rules` | All active resolved rules |
| `llm_rules_sent_to_model` | All active agent rules sent to LLM (includes `is_fallback` rules) |
| `fallback_rule` | Programmatic safety-net rule — only when LLM/parsing fails, not on `null` |
| `llm_decision` | Same as `routing.decision_source` when not skipped |
| `routing` | Final `context.routing` |
| `thread_department_updated` | Whether Mongo thread doc was updated |

**Downstream:** `ai_recipients_generator`, `generate_email` may read `context.routing`.

**Source files:**

| File | Role |
| ---- | ---- |
| `nodes/ai_department_router_node.py` | Node handler |
| `email_department_router_llm_services.py` | LLM routing + parsing + fallback safety nets |
| `email_routing_rules/email_routing_rules_mongo_services.py` | `get_routing_rules_by_ids()` |
| `email_flow_thread_data_services.py` | `update_thread_department_id()` |

**Status:** implemented.

---

## 8. Node: `ai_recipients_generator`

### Flow builder — `RecipientsNode`

| Item | Detail |
| ---- | ------ |
| Position | After `ai_department_router`, before `generate_email` |
| `data.label` | `AI Recipients Generator` |
| `data.binding` | `N recipient rules` chip (from `agent.recipient_rule_ids`) |
| `data.config` | `recipient_rule_ids` (optional override) |
| Preview mode | Show label + rule count |
| Editor mode | Read-only link to recipient-rules admin |
| On save | `recipient_rule_ids` syncs to agent |

### Backend I/O

**Reads from context:** `thread.messages` (last 5 emails), `thread.subject`, `trigger_message`

**Reads from agent:** `recipient_rule_ids`, `llm_model` (`gpt-5.4` / `gpt-5.5`)

**Reads from `config`:** `recipient_rule_ids` (override)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `recipients.to` | Reply target (latest inbound sender, respecting `Reply-To`) |
| `recipients.cc` | Inbound CC on the trigger message **plus** CC from matched rules (deduped) |
| `recipients.bcc` | Inbound BCC on the trigger message **plus** BCC from matched rules (deduped) |
| `recipients.cc_user_ids` | Merged `cc_user_ids` from matched rules |
| `recipients.bcc_user_ids` | Merged `bcc_user_ids` from matched rules |
| `recipients.cc_users` | CC users resolved from `email-users` (`user_id`, `email`, `name`) |
| `recipients.bcc_users` | BCC users resolved from `email-users` (`user_id`, `email`, `name`) |
| `recipients.matched_rule_ids` | Rule `_id`s the LLM flagged as matching |
| `recipients.matched_recipient_rules` | Per matched rule: ids, mapped users, and emails |
| `recipients.decision_source` | How matches were resolved (see matrix below) |
| `recipients.reason` | Human-readable note |

**`context.recipients` shape:**

```json
{
  "to": ["customer@example.com"],
  "cc": ["manager@company.com", "founder@company.com"],
  "bcc": ["legal@company.com"],
  "cc_user_ids": ["6a23597fc25333c86ca81440"],
  "bcc_user_ids": ["6a2417869c2eb522db6c4818"],
  "cc_users": [
    {
      "user_id": "6a23597fc25333c86ca81440",
      "email": "founder@company.com",
      "name": "Jane Founder"
    }
  ],
  "bcc_users": [
    {
      "user_id": "6a2417869c2eb522db6c4818",
      "email": "legal@company.com",
      "name": "Legal Team"
    }
  ],
  "matched_rule_ids": ["6a2531c6e7ef84ed641c0766"],
  "matched_recipient_rules": [
    {
      "_id": "6a2531c6e7ef84ed641c0766",
      "rule_name": "Enterprise deal CC leadership",
      "cc_user_ids": ["6a23597fc25333c86ca81440"],
      "bcc_user_ids": ["6a2417869c2eb522db6c4818"],
      "cc_users": [
        {
          "user_id": "6a23597fc25333c86ca81440",
          "email": "founder@company.com",
          "name": "Jane Founder"
        }
      ],
      "bcc_users": [
        {
          "user_id": "6a2417869c2eb522db6c4818",
          "email": "legal@company.com",
          "name": "Legal Team"
        }
      ],
      "cc": ["founder@company.com"],
      "bcc": ["legal@company.com"]
    }
  ],
  "decision_source": "llm_matched",
  "reason": "LLM matched 1 recipient rule(s)."
}
```

**LLM output contract** (only matching rules — omit non-matches):

```json
[
  { "_id": "6a2531c6e7ef84ed641c0766", "meets_requirements": true }
]
```

Empty array when nothing matches:

```json
[]
```

**Decision matrix (`recipients.decision_source`):**

| `decision_source` | Meaning |
| ----------------- | ------- |
| `skipped` | No `recipient_rule_ids` or no active rules resolved |
| `llm_matched` | LLM returned one or more valid matching rule `_id`s |
| `llm_no_match` | LLM successfully returned `[]` — no rule clearly applies |
| `safety_empty` | LLM/parsing failed after 3 retries — no CC/BCC from rules (inbound CC/BCC still preserved) |

**How it works:**

1. Load recipient rules from Mongo for `agent.recipient_rule_ids`
2. **LLM call** (`gpt-5.4` / `gpt-5.5`) with:
   - **System:** `EMAIL_RECIPIENT_RULES_SYSTEM_PROMPT`
   - **User:** last 5 thread emails (emphasis on latest inbound + trigger) + rule fields for LLM (`_id`, `rule_name`, `recipient_prompt`) only
3. Parse JSON array with Pydantic + robust fence/bracket parser (max **3 retries**)
4. Validate each `_id` is in the allowed rule set; ignore `meets_requirements: false` entries
5. Merge `cc_user_ids` / `bcc_user_ids` from matched rules → resolve emails from `email-users` (only when LLM matched at least one rule)
6. Default **To:** trigger/latest inbound sender (`Reply-To` when present)
7. **Preserve inbound CC/BCC** from the trigger message, then merge with rule CC/BCC:
   - Dedupe case-insensitively (`person-a@example.com` = `Person-A <person-a@example.com>`)
   - Drop the **To** address from CC
   - Drop CC addresses from BCC when the same person appears in both lists

**Recipient merge example:** inbound CC = `manager@company.com`, rule CC = `person-a@example.com` + `manager@company.com` → final CC = `manager@company.com`, `person-a@example.com` (one copy of manager).

**Skip (not fail):**

- No `recipient_rule_ids` on agent
- `recipient_rule_ids` configured but none resolve for the team

**Fail:**

- `llm_model` missing or not `gpt-5.4` / `gpt-5.5`
- Unexpected exception in node handler

**Run log audit (`node_logs[].output`):**

| Field | Meaning |
| ----- | ------- |
| `recipient_rules_registered` | Whether rules were configured |
| `configured_recipient_rule_ids` | Raw ids from agent |
| `registered_recipient_rules` | All resolved rules (LLM fields only in summary) |
| `llm_rules_sent_to_model` | Rules sent to LLM (`_id`, `rule_name`, `recipient_prompt`) |
| `llm_matched_rules` | Parsed LLM matches |
| `matched_recipient_rules` | Matched rules with `cc_user_ids` / `bcc_user_ids` mapped to `email-users` emails |
| `llm_decision` | Same as `recipients.decision_source` when not skipped |
| `recipients` | Final `context.recipients` |

**Downstream:** `generate_email`, tail nodes use `context.recipients` for reply headers.

**Source files:**

| File | Role |
| ---- | ---- |
| `nodes/ai_recipients_generator_node.py` | Node handler — load rules, call LLM, merge inbound + rule CC/BCC |
| `email_gmail_reply_services.py` | Shared recipient merge + MIME build (`extract_inbound_cc_bcc`, `merge_reply_cc_bcc`) |
| `email_recipient_rules_llm_services.py` | LLM evaluation + JSON array parsing + retries |
| `email_recipient_rules/email_recipient_rules_mongo_services.py` | `get_recipient_rules_by_ids()` |
| `email_user_auth_services.py` | `get_email_users_by_ids()` |

**Status:** implemented.

---

## 9. Node: `generate_email`

### Flow builder — `GenerateEmailNode`

| Item | Detail |
| ---- | ------ |
| Position | After `ai_recipients_generator`, before `call_external_tool` |
| `data.label` | `Generate Email` |
| `data.binding` | LLM model badge (from `agent.llm_model`) |
| `data.config` | None on node (uses agent `system_prompt`, `email_format_template`) |
| Preview mode | Show label + model badge |
| On save | `llm_model` syncs to agent |

### Backend I/O

**Reads from context:**

| Key | Usage |
| --- | ----- |
| `thread.messages` | Last 5 emails (`IS_LATEST_INBOUND`, `IS_TRIGGER_MESSAGE`) |
| `thread.subject` | Reply subject (`Re: …`) |
| `compressed_query` | Thread summary block |
| `system_prompt` | Agent behaviour instructions |
| `email_format_template` | Optional reply layout / placeholders |
| `kb_chunks`, `kb_title` | RAG snippets |
| `tool_results` | Successful tool API payloads; failed calls listed separately |
| `recipients.to` | Reply target + customer name hint |

**Reads from agent:** `llm_model`, `system_prompt`, `email_format_template`

**Writes to context:**

```json
{
  "subject": "Re: Enterprise pricing",
  "body_text": "Hi John,\n\nThank you for reaching out...",
  "body_html": "",
  "confidence": 0.72,
  "decision_source": "llm_generated",
  "reason": "LLM generated email draft."
}
```

**LLM output contract:**

```json
{
  "email_draft": "Full plain-text reply body...",
  "confidence": 0.72
}
```

**Decision matrix (`draft.decision_source`):**

| `decision_source` | Meaning |
| ----------------- | ------- |
| `llm_generated` | Parsed `email_draft` + `confidence` from LLM |
| `fallback_template` | LLM/parsing failed after 3 retries — generic safe draft, `confidence: 0.1` |

**Fallback draft (after retry exhaustion):**

```json
{
  "email_draft": "Hello there,\n\nThank you for your message. A member of our team will review your request and follow up with you shortly.\n\nBest regards",
  "confidence": 0.1
}
```

Node status remains **`ok`** on fallback so the run can continue to draft/send tail nodes.

**How it works:**

1. Build system message: fixed generation rules + confidence rubric + agent `system_prompt`
2. Build user message: subject, `REPLY_TO`, `CUSTOMER_NAME_HINT`, compressed summary, last 5 emails, KB, tool results, optional `email_format_template`
3. **LLM call** using `agent.llm_model` (must exist in model registry)
4. Parse JSON with Pydantic + fence/bracket parser (max **3 retries**)
5. Clamp `confidence` to **0.1–1.0**
6. On retry exhaustion → programmatic fallback template + `confidence: 0.1`

**Run log audit (`node_logs[].output`):**

| Field | Meaning |
| ----- | ------- |
| `llm_prompt_text` | **Full stringified prompt** sent to the LLM (system + user) — stored in Mongo |
| `llm_raw_response_preview` | First 500 chars of raw LLM JSON |
| `draft_preview` | First 500 chars of final body |
| `draft` | Final `context.draft` |
| `decision_source` | `llm_generated` or `fallback_template` |
| `llm_attempts` | Retry count |

**Fail (node `failed`, no fallback):**

- Missing `system_prompt` or `llm_model`
- Empty `thread.messages`
- Unsupported model name

**Downstream:** `send_email` compares `draft.confidence` to `reply_action.auto_send_min_confidence`; tail nodes use `draft` + `recipients`.

**Source files:**

| File | Role |
| ---- | ---- |
| `nodes/generate_email_node.py` | Node handler |
| `email_generate_llm_services.py` | Prompt assembly, LLM call, parser, fallback |

**Status:** implemented.

---

## 10. Node: `save_gmail_draft`

### Flow builder — `SaveGmailDraftNode`

| Item | Value |
| ---- | ----- |
| Position | After `generate_email`, before `stop` |
| `data.label` | `Save Gmail Draft` |
| `data.binding` | `Draft only` (from `agent.reply_action`) |
| Shown when | `agent.reply_action.mode === "draft"` |

### Purpose

Create a **Gmail draft** on the linked inbox thread using:

- `context.draft.body_text` (plain text) and `context.draft.subject`
- **To** from `context.recipients.to` (fallback: trigger inbound `from` / `reply_to`)
- **Cc** / **Bcc** from `context.recipients` — inbound CC/BCC on the trigger message **plus** any CC/BCC from matched recipient rules (merged and deduped in `ai_recipients_generator`; re-applied in `resolve_reply_recipients` at draft/send time)

The draft appears in the user's **Gmail** inbox on that thread (open the conversation → draft reply is ready to review and send). Requires OAuth scope `gmail.compose` — reconnect the inbox if draft creation returns 403.

### Writes

| Target | Field(s) |
| ------ | -------- |
| Gmail API | Thread-scoped draft (`gmail_draft_id`) |
| `context` | `final_action` — `{ type: "draft", gmail_draft_id, gmail_draft_message_id, recipients }` |
| `email-threads` | `ai_action` — denormalized actionable state for inbox list |
| `email-thread-messages` (trigger inbound) | `ai_outcome` — links draft to the message that triggered the run |

**`email-threads.ai_action` shape:**

```json
{
  "status": "draft_ready",
  "type": "draft",
  "flow_run_id": "...",
  "trigger_message_id": "...",
  "gmail_draft_id": "...",
  "gmail_draft_message_id": "...",
  "confidence": 0.72,
  "subject": "Re: Refund request",
  "body_text": "Hi John,\n\nThank you for reaching out...",
  "recipients": {
    "to": ["customer@example.com"],
    "cc": ["shubhojeet.official@gmail.com"],
    "bcc": ["shubho.01062016@gmail.com"],
    "cc_users": [{ "user_id": "...", "email": "...", "name": "..." }],
    "bcc_users": [{ "user_id": "...", "email": "...", "name": "..." }],
    "matched_recipient_rules": [{ "_id": "...", "rule_name": "...", "cc": [], "bcc": [] }]
  },
  "created_at": "...",
  "resolved_at": null
}
```

**Trigger message `ai_outcome` shape:**

```json
{
  "type": "draft_created",
  "flow_run_id": "...",
  "gmail_draft_id": "...",
  "gmail_draft_message_id": "...",
  "confidence": 0.72,
  "recipients": { "to": [], "cc": [], "bcc": [], "matched_recipient_rules": [] }
}
```

### Frontend (inbox APIs)

- **`list-team-threads`:** each thread includes `action_required: true` when `ai_action.status === "draft_ready"`, plus full `ai_action`.
- **`get-thread`:** thread summary includes `ai_action`; messages include `processing_status`, `ai_outcome` on the trigger inbound.

See [email-threads-api.md](./email-threads-api.md) and [email-draft-review-ui.md](./email-draft-review-ui.md).

### Source files

| File | Role |
| ---- | ---- |
| `nodes/save_gmail_draft_node.py` | Node handler |
| `gmail_api_services.py` | MIME build + `drafts.create` |
| `gmail_token_services.py` | Refresh access token for agent inbox |
| `email_flow_thread_data_services.py` | `ai_action` / `ai_outcome` Mongo updates |

**Status:** implemented.

---

## 11. Node: `send_email`

### Flow builder — `SendEmailNode`

| Item | Value |
| ---- | ----- |
| Position | After `generate_email`, before `stop` |
| `data.label` | `Send Email` |
| `data.binding` | `Auto-send ≥ {auto_send_min_confidence}` (from `agent.reply_action`) |
| Shown when | `agent.reply_action.mode === "auto_send"` |

### Purpose

Tail node for **auto-send** agents. Compares `context.draft.confidence` to `agent.reply_action.auto_send_min_confidence`:

| Condition | Action |
| --------- | ------ |
| `confidence >= auto_send_min_confidence` | Send reply directly via Gmail `users.messages.send` (requires `gmail.send`) |
| `confidence < auto_send_min_confidence` | **Draft fallback** — same Gmail draft + Mongo writes as `save_gmail_draft`, with `type: "draft_fallback"` |

Send failures **fail the run** — no draft fallback on API errors (MVP).

Reply headers (**To** / **Cc** / **Bcc**) use the same merged recipient list as `save_gmail_draft` via `resolve_reply_recipients` in `email_gmail_reply_services.py`.

### Writes

| Target | Field(s) |
| ------ | -------- |
| Gmail API | Direct send (`gmail_message_id`) or fallback draft (`gmail_draft_id`) |
| `context` | `final_action` — `{ type: "sent", ... }` or `{ type: "draft", fallback_reason, ... }` |
| `email-threads` | `ai_action` — see shapes below |
| `email-thread-messages` (trigger inbound) | `ai_outcome` — `auto_sent` or `draft_created` |
| `email-thread-messages` (outbound, auto-send path) | `ai_reply.mode: "auto"` stub |

**Auto-sent — `email-threads.ai_action`:**

```json
{
  "status": "sent",
  "type": "auto_send",
  "flow_run_id": "...",
  "trigger_message_id": "...",
  "gmail_message_id": "18f3sent789",
  "confidence": 0.92,
  "auto_send_min_confidence": 0.8,
  "threshold_met": true,
  "subject": "Re: Refund request",
  "body_text": "Hi John,...",
  "recipients": { "to": [], "cc": [], "bcc": [] },
  "created_at": "...",
  "resolved_at": "..."
}
```

Frontend: `action_required: false` — informational “AI replied” banner only.

**Draft fallback — `email-threads.ai_action`:**

```json
{
  "status": "draft_ready",
  "type": "draft_fallback",
  "fallback_reason": "confidence_below_threshold",
  "confidence": 0.65,
  "auto_send_min_confidence": 0.8,
  "threshold_met": false,
  "gmail_draft_id": "...",
  "gmail_draft_message_id": "...",
  "subject": "Re: ...",
  "body_text": "...",
  "recipients": { "to": [], "cc": [], "bcc": [] },
  "created_at": "...",
  "resolved_at": null
}
```

Frontend: `action_required: true` — same draft panel + **Send** as draft-only mode; copy **“Auto-send skipped — review draft”**.

**Trigger message `ai_outcome` (auto-sent):**

```json
{
  "type": "auto_sent",
  "flow_run_id": "...",
  "gmail_message_id": "18f3sent789",
  "confidence": 0.92,
  "auto_send_min_confidence": 0.8,
  "threshold_met": true,
  "recipients": { "to": [], "cc": [], "bcc": [] }
}
```

### Frontend (inbox APIs)

- **`list-team-threads`:** `action_required: true` only for `draft_ready` (includes `draft_fallback`). `status: "sent"` → optional “AI replied” badge, not actionable.
- **`get-thread`:** full `ai_action` including `body_text`; outbound auto-send rows have `ai_reply.mode: "auto"`.

See [email-draft-review-ui.md](./email-draft-review-ui.md).

### Source files

| File | Role |
| ---- | ---- |
| `nodes/send_email_node.py` | Node handler — confidence gate + send / fallback |
| `email_gmail_reply_services.py` | Shared MIME, recipients, draft persist |
| `gmail_api_services.py` | `send_gmail_message` + `create_gmail_draft` |
| `email_flow_thread_data_services.py` | `build_auto_sent_*` / draft builders |

**Status:** implemented.

---

## 12. Node: `stop`

Terminal node — no config. Marks pipeline end; `final_action` already set by tail node.

| File | Role |
| ---- | ---- |
| `nodes/stop_node.py` | Node handler |

**Status:** implemented.

---

## 13. Node: `call_external_tool`

Post-draft external tool node — LLM decides whether to call flow-configured tools for side effects (CRM, tickets, etc.) after the reply is drafted/sent.

### Flow builder — `ExternalToolNode`

| Item | Detail |
| ---- | ------ |
| Position | After tail (`save_gmail_draft` / `send_email`), immediately before `stop` |
| `data.label` | `Call External Tool` |
| `data.binding` | Tool display names (from `config.external_tools`) |
| `data.config` | `external_tools[]` (canonical; backend also accepts `tool_ids[]` and normalizes on flow save) |
| Preview mode | Label + tool name chips |
| Editor mode | Tool multi-select (team tools) |
| On save | **Flow-only** — does **not** sync to `agent.tool_ids` |

**Not accepted on agent create/update API.** Configure only via the workflow canvas.

### Backend I/O

**Reads from context:** `compressed_query`, `thread` (last 5 messages, trigger emphasized), `draft`

**Reads from `config`:** `external_tools[]` — if empty/missing, backend falls back to `tool_ids[]` (legacy / Read Tools picker key). On **`POST /email-flows/v1/update`**, stored config is rewritten to `external_tools[]` only.

**Reads from agent:** `llm_model` only (must be reasoning model — same as Read Tools)

**Writes to context:**

| Key | Description |
| --- | ----------- |
| `external_tools_registered` | Active tools available this run |
| `external_tools_planned` | LLM-selected tool calls before execution |
| `external_tool_results` | Full HTTP/API results per executed tool |

Separate from Read Tools (`tool_results`) — post-draft side effects only.

**Skip (not fail):** if `external_tools` is empty → node status `skipped`, pipeline continues.

**Fail:** if `compressed_query` is empty, LLM planning fails after retries, or unexpected errors.

### Source files

| File | Role |
| ---- | ---- |
| `nodes/call_external_tool_node.py` | Node handler |
| `email_flow_validation_services.py` | `resolve_external_tool_ids_from_config`, `normalize_call_external_tool_nodes` |
| `email_external_tools_llm_services.py` | Post-draft LLM planning prompt + orchestration |
| `email_read_tools_llm_services.py` | Shared HTTP execution (`execute_planned_email_tools`) |

**Status:** implemented.

---

## 14. Reprocess thread (test API)

Full API reference: **[email-flow-reprocess-thread-api.md](./email-flow-reprocess-thread-api.md)** (request/response, `force_reprocess`, polling, examples).

Re-run the flow on an **existing** thread without sending a new email. Calls `run_agent_thread_flow()` in `email_flow_engine.py` — the same orchestrator sync will use later.

**Current pipeline:** `start` → `load_thread_context` → `read_kb` → `read_tools` → `ai_department_router` → `ai_recipients_generator` → `generate_email` → **`save_gmail_draft`** → **`call_external_tool`** (when on saved workflow) → `stop` when `reply_action.mode === "draft"`, or → **`send_email`** → **`call_external_tool`** → `stop` when `mode === "auto_send"`.

```
POST /elysium-agents/email-flows/v1/reprocess-thread
```

Public — no JWT. **Fire-and-forget:** validates input, creates a queued run on `email-flow-runs`, starts the pipeline in a background task, and returns immediately. Poll `get-run` for completion.

**Request:**

```json
{
  "agent_id": "674abc123def456789012345",
  "thread_id": "6a253934725d1aa8ca28452c",
  "trigger_message_id": "",
  "force_reprocess": true,
  "message_limit": 10
}
```

| Field | Default | Description |
| ----- | ------- | ----------- |
| `agent_id` | required | Email AI agent Mongo `_id` |
| `thread_id` | required | Gmail thread id |
| `trigger_message_id` | `""` | Optional — Mongo `_id` or `gmail_message_id` |
| `force_reprocess` | `true` | Re-run even if already processed (use for testing) |
| `message_limit` | `10` | Passed to Load Thread Context |

**Immediate response — `202 Accepted`:**

```json
{
  "success": true,
  "message": "Thread reprocess in progress.",
  "data": {
    "run_id": "uuid",
    "status": "queued",
    "agent_id": "674abc123def456789012345",
    "thread_id": "6a253934725d1aa8ca28452c",
    "trigger_message_id": "",
    "force_reprocess": true,
    "message_limit": 10,
    "poll_run_endpoint": "/elysium-agents/email-flows/v1/get-run"
  }
}
```

Poll until `status` is `completed`, `failed`, or `skipped`:

```
POST /elysium-agents/email-flows/v1/get-run
{ "run_id": "<uuid from above>" }
```

**Completed run (`get-run`) — example shape:**

```json
{
  "success": true,
  "message": "Flow run fetched successfully.",
  "data": {
    "run_id": "uuid",
    "status": "completed",
    "node_logs": [
      { "node_id": "start", "status": "ok" },
      { "node_id": "generate_email", "status": "ok", "output": { "llm_prompt_text": "..." } }
    ],
    "context": {
      "draft": {
        "subject": "Re: Refund request",
        "body_text": "Hi John,...",
        "confidence": 0.72,
        "decision_source": "llm_generated"
      }
    }
  }
}
```

Run `status` values while polling: `queued` → `running` → `completed` | `failed` | `skipped`.

**Legacy note:** The HTTP route no longer waits for the full pipeline. Use `get-run` for final `node_logs` and `flow_context`.

**vs `preview-load-thread-context`:** preview runs **only** Load Thread Context (no Start). Reprocess runs the **full pipeline** so far with one `run_id` and **two** `node_logs` entries.

**Production:** UI “Regenerate reply” will call `run_agent_thread_flow()` directly — not necessarily this HTTP route.

---

## 15. Screens using the flow builder

| Screen | Canvas mode | What to show |
| ------ | ----------- | ------------ |
| Agent detail | Preview (read-only) | Default workflow + binding chips |
| Power user — flow editor | Full editor | Clone default, edit config, save graph |
| Agent settings | No canvas | `system_prompt`, inbox, KB, tools (synced from flow nodes) |

On flow save, backend runs **flow → agent** sync for `knowledge_id`, `tool_ids`, `llm_model`, `reply_action`. On agent save, **agent → flow** sync updates matching node `config` + `binding`.

---

## 16. Adding a new node (checklist)

**Backend**

1. `nodes/<type>_node.py` — `execute_*_node(context, config, agent)`
2. Register in `NODE_HANDLERS` + `MVP_FLOW_PIPELINE` in `email_flow_engine.py`
3. Document I/O in this file

**Flow builder**

1. `<Type>Node` React component registered in `nodeTypes`
2. Render `data.label` + `data.binding` chips
3. Side panel fields for editable `data.config`
4. Include in default seed graph with `position` + `edges`

---

## 17. Changelog

| Date | Node | Notes |
| ---- | ---- | ----- |
| 2026-06-08 | `call_external_tool` | Post-draft LLM tool planning + HTTP execution; flow-only `external_tools[]`; runs after tail |
| 2026-06-07 | `send_email` | Auto-send tail: confidence gate, direct Gmail send, draft fallback, Mongo `ai_action` / `ai_outcome` |
| 2026-06-07 | `ai_department_router` | All registered rules sent to LLM; `is_fallback` only for parse-failure safety net |
| 2026-06-07 | `ai_department_router` | LLM routing from `routing_rule_ids`; priority ties; fallback + safety nets |
| 2026-06-07 | `read_tools` | Full node doc: context shapes, run-log audit, terminal logs, downstream usage |
| 2026-06-07 | `read_tools` | LLM tool planning (`gpt-5.4`/`gpt-5.5`) + HTTP execution; stores full API `response` in `tool_results` |
| 2026-06-07 | `read_kb` | Qdrant RAG top-5 via `compressed_query`; wired into reprocess pipeline |
| 2026-06-07 | `load_thread_context` | LLM `compressed_query` via gpt-4.1-mini (3 retries) |
| 2026-06-07 | `start` | Backend handler + `reprocess-thread` test API |

---

*Expand as each node ships. Pipeline architecture: [email-flow-plan.md](./email-flow-plan.md).*
