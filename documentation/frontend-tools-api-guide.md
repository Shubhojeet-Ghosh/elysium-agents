# Custom Tools APIs — frontend guide

Reference for building the **team custom tools** UI in Elysium Atlas. Tools are external HTTP integrations configured like OpenAI function calling. At chat runtime, attached tools are orchestrated via DeepSeek (multi-round when configured), then results are passed to the agent’s main LLM for the visitor-facing reply.

**Base path:** `/elysium-agents/elysium-atlas/tools`

All routes require `Authorization: Bearer <session_jwt>`. The JWT must include `user_id`, `team_id`, and `role` (see [backend-team-rbac-guide.md](./backend-team-rbac-guide.md)).

**Postman collection:** `postman/elysium_tools.postman_collection.json` (import as collection **elysium_tools**).

---

## Overview

| Concept | Detail |
|---------|--------|
| Scope | **Team-level** — tools belong to the active JWT `team_id`, not to a single agent |
| Tool ID | Mongo `_id`, returned as `tool_id` in API responses |
| Storage | `atlas_tools` collection |
| Name uniqueness | Unique per team (`team_id` + `name`) |
| Secrets | API keys/tokens are **never returned** after save; responses include `auth.token_configured: true` |
| Agent linking | Agents store attached tools in `tool_ids` (array of `atlas_tools._id` strings) |
| Runtime orchestration | Per-agent `tool_calling_config` controls multi-round tool execution during chat |
| Chat audit | Each tool HTTP call is stored as `role: "tool"` on `atlas_chat_mesages` and mirrored to monitors |

---

## Agent linking (`tool_ids`)

Agents reference team tools via **`tool_ids: string[]`** on the `atlas_agents` document. Each value is the Mongo `_id` of a tool in `atlas_tools` (same as `tool_id` in tool API responses).

| Rule | Detail |
|------|--------|
| Default | `[]` on new agents |
| Max | 50 tool IDs per agent |
| Validation | Every ID must exist and belong to the **same team** as the agent |
| Duplicates | Removed automatically (order preserved) |

### Agent APIs that accept `tool_ids`

| Endpoint | When |
|----------|------|
| `POST /elysium-atlas/agent/v1/pre-build-agent-operations` | Create agent shell |
| `POST /elysium-atlas/agent/v1/build-agent` | Build / index pipeline |
| `POST /elysium-atlas/agent/v1/update-agent` | Metadata update (with or without re-index) |

**Create example** (`pre-build-agent-operations` or `build-agent`):

```json
{
  "agent_name": "Support Bot",
  "tool_ids": [
    "674a1b2c3d4e5f6789012345",
    "674a1b2c3d4e5f6789012346"
  ]
}
```

**Update example** (`update-agent`):

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "tool_ids": ["674a1b2c3d4e5f6789012345"]
}
```

Send `"tool_ids": []` to detach all tools.

**Read:** `tool_ids` is returned on `get-agent-details` and other agent document responses (defaults to `[]` for older agents).

**Errors:** Invalid or cross-team tool IDs return `400` with a message such as `One or more tool_ids are invalid or do not belong to this team.`

For full create/update agent request parameters, see [frontend-agent-create-update-api-guide.md](./frontend-agent-create-update-api-guide.md).

**Demo tool APIs:** See [frontend-demo-customer-inquiry-api-guide.md](./frontend-demo-customer-inquiry-api-guide.md) for the customer lookup / lead / summary demo endpoints and tool registration copy-paste.

---

## Tool calling config (`tool_calling_config`)

Controls **how** attached tools run during visitor chat. Stored on each `atlas_agents` document alongside `tool_ids`.

| Field | Type | Default | UI | Description |
|-------|------|---------|-----|-------------|
| `enabled` | `boolean` | `true` | Optional | Master switch. When `false`, tools are attached but not executed at chat time |
| `max_rounds` | `integer` | `5` | **Yes** | Max plan → execute → replan cycles per visitor message (enables chained tools) |
| `max_executions_per_turn` | `integer` | `10` | **Yes** | Hard cap on total HTTP tool calls per visitor message |
| `parallel_calls_per_round` | `boolean` | `true` | **Yes** | When `true`, multiple independent tools may run in the same round; when `false`, only one tool runs per round |
| `stop_on_error` | `boolean` | `false` | Hidden | When `true`, stop further tool rounds after a tool returns an error payload |
| `include_tool_history_in_llm` | `boolean` | `false` | **Yes** | When `true`, past tool call request/response rows are injected into both the tool orchestration LLM and the final response LLM (chronological order). When `false`, only user/agent text history is sent (current default) |
| `max_tool_history_in_llm` | `integer` | `10` | **Yes** (when history enabled) | Max number of **past** persisted tool rows to include in LLM prompts. Only applies when `include_tool_history_in_llm === true`. Current-turn tool results are always included when tools run |

### Validation limits

| Field | Min | Max |
|-------|-----|-----|
| `max_rounds` | `1` | `10` |
| `max_executions_per_turn` | `1` | `20` |
| `max_tool_history_in_llm` | `1` | `20` |

Partial updates merge into the stored config (same pattern as `lead_collection_config`). Unknown keys return `400`.

### What the settings mean (for UI copy)

- **`max_rounds`** — How many times the agent can *think, call tools, see results, and think again* before answering. Use **3–5** when tools depend on each other (e.g. lookup customer → fetch orders).
- **`max_executions_per_turn`** — Total number of tool HTTP calls allowed in one visitor message (cost/latency guardrail).
- **`parallel_calls_per_round`** — When on, independent tools can run together in one step. Turn off if APIs are rate-limited or must run strictly one at a time.
- **`include_tool_history_in_llm`** — Turn on for multi-step flows where later turns depend on earlier tool outcomes (e.g. member verification before doctor lookup). Off by default to save tokens.
- **`max_tool_history_in_llm`** — Caps how many persisted `role: "tool"` rows are replayed into LLM prompts. User/agent text history is capped separately by `llm_context_config.max_chat_history_messages` (default `10`, max `100`).

---

## LLM context config (`llm_context_config`)

Controls how much **user/agent conversation history** is injected into the main agent LLM prompts (tool orchestration + final reply). Applies to **all agents**, with or without tools.

| Field | Type | Default | UI | Description |
|-------|------|---------|-----|-------------|
| `max_chat_history_messages` | `integer` | `10` | **Yes** | Max past user/agent text messages in LLM prompts (chronological). Does **not** affect lead collection, human handover, or visitor widget session restore |

### Validation limits

| Field | Min | Max |
|-------|-----|-----|
| `max_chat_history_messages` | `1` | `100` |

Partial updates merge into the stored config (same pattern as `tool_calling_config`). Unknown keys return `400`.

**Create / update endpoints:** same as `tool_ids` — `pre-build-agent-operations`, `build-agent`, `update-agent`.

**Create example:**

```json
{
  "agent_name": "Care Coordinator",
  "llm_context_config": {
    "max_chat_history_messages": 20
  }
}
```

**Partial update example:**

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "llm_context_config": {
    "max_chat_history_messages": 30
  }
}
```

**Read:** `llm_context_config` is returned on `get-agent-details`. Older agents without the field receive defaults when read.

**UI copy:** Higher values improve long multi-turn conversations but increase token usage, cost, and latency.

**Not affected:** Lead collection and human handover keep their own internal history limits and never receive tool rows.

### Agent APIs that accept `tool_calling_config`

Same endpoints as `tool_ids`:

| Endpoint | When |
|----------|------|
| `POST /elysium-atlas/agent/v1/pre-build-agent-operations` | Create agent shell |
| `POST /elysium-atlas/agent/v1/build-agent` | Build / index pipeline |
| `POST /elysium-atlas/agent/v1/update-agent` | Metadata update |

**Create example** (with tools):

```json
{
  "agent_name": "Support Bot",
  "tool_ids": ["674a1b2c3d4e5f6789012345"],
  "tool_calling_config": {
    "enabled": true,
    "max_rounds": 5,
    "max_executions_per_turn": 10,
    "parallel_calls_per_round": true,
    "include_tool_history_in_llm": false,
    "max_tool_history_in_llm": 10
  }
}
```

**Partial update example** (`update-agent`):

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "tool_calling_config": {
    "max_rounds": 3,
    "parallel_calls_per_round": false
  }
}
```

**Read:** `tool_calling_config` is returned on `get-agent-details` and other agent document responses. Older agents without the field receive defaults when read.

**Errors:** Invalid values return `400`, e.g. `max_rounds must be between 1 and 10.` or `Invalid tool_calling_config field(s): ...`

### Runtime behavior (chat)

When a visitor sends a message and the agent has non-empty `tool_ids` with `tool_calling_config.enabled === true`:

1. Knowledge retrieval and prompt assembly run as today.
2. **Tool orchestration** (DeepSeek `deepseek-v4-pro`):
   - Up to `max_rounds` cycles.
   - Each cycle: model may call zero or more tools → HTTP execution → results fed back to the orchestrator.
   - Stops when the model calls no tools, limits are hit, or `stop_on_error` triggers.
3. Tool results are injected into the final prompt as plain-text assistant messages.
4. The agent’s configured **`llm_model`** generates the streamed/non-streamed reply.

**Chained tools:** Round 1 might call `find_customer`; round 2 sees that result and calls `get_order_status`. No explicit dependency graph is required — the orchestrator infers order from tool descriptions and prior results.

**Past tool history in LLM (`include_tool_history_in_llm`):**

| Setting | Tool orchestration LLM | Final response LLM | Lead collection / human handover |
|---------|------------------------|--------------------|--------------------------------|
| `false` (default) | User/agent text only (+ current-turn tools) | User/agent text only (+ current-turn tools) | User/agent text only (unchanged) |
| `true` | User/agent + up to `max_tool_history_in_llm` past tool rows, chronologically merged | Same | **Still user/agent text only** — these subsystems never receive tool history |

When enabled, persisted tool rows are formatted as plain text (tool name, request payload, response payload) and interleaved by `created_at` with user/agent messages. The server fetches a slightly larger Mongo window so user/agent rows are not dropped when many tools ran recently.

**UI recommendation:** Show `max_rounds`, `max_executions_per_turn`, and `parallel_calls_per_round` only when at least one tool is selected. Show `include_tool_history_in_llm` and `max_tool_history_in_llm` when tools or plugins are selected (history applies to plugins too). Hide `stop_on_error` (server default `false`).

---

## Tool calls in chat (monitors + history)

Each HTTP tool execution is stored as its **own** `atlas_chat_mesages` row (`role: "tool"`) and mirrored live to session monitors. Persist and socket emit run in the background and do **not** delay the visitor reply.

### Who sees them

| Surface | Sees tool calls? |
|---------|------------------|
| Atlas live monitor | Yes — socket event `tool_call_from_agent` after each tool HTTP returns (success or error) |
| Atlas session history | Yes — `get-agent-fields` with `include_tool_calls: true` |
| Visitor widget | **Never** — not on the visitor socket; `get-agent-fields` omits `role: "tool"` unless `include_tool_calls` is true |
| Agent LLM (orchestration + reply) | Only when `tool_calling_config.include_tool_history_in_llm === true` (past rows). Current-turn tools are always visible to both LLMs when tools run |
| Lead collection / human handover LLMs | **Never** — always user/agent text only |

Human takeover does not run tools. `tool_call_from_agent` is AI-monitor only.

### Message shape (`role: "tool"`)

Tool rows sit **between** the visitor message that triggered them and the agent reply, sorted by `created_at`.

```json
{
  "_id": "67a1b2c3d4e5f6789012345d",
  "message_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "role": "tool",
  "content": "lookup_demo_customer",
  "tool_name": "lookup_demo_customer",
  "request_payload": { "email": "ada@example.com" },
  "response_payload": { "customer_id": "demo_cust_001", "status": "returning" },
  "request_payload_truncated": false,
  "response_payload_truncated": false,
  "status": "success",
  "parent_user_message_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "created_at": "2026-09-11T00:25:12.340Z"
}
```

| Field | Type | Notes |
|-------|------|--------|
| `role` | `"tool"` | Filter/toggle technical rows with `role === "tool"` |
| `content` | `string` | Same as `tool_name` (fallback for generic message renderers) |
| `tool_name` | `string` | Atlas tool `name` (LLM function name) |
| `request_payload` | `object` or truncated `string` | LLM function arguments (not auth tokens) |
| `response_payload` | `object`, `string`, or truncated `string` | Parsed JSON body when possible; `{ "error": true, ... }` on timeout/4xx |
| `request_payload_truncated` | `boolean` | True when request JSON exceeded 16 000 characters |
| `response_payload_truncated` | `boolean` | True when response JSON exceeded 16 000 characters |
| `status` | `"success"` \| `"error"` | Error includes HTTP failures and timeouts |
| `parent_user_message_id` | `string` | Visitor `message_id` for this turn |
| `created_at` | `string` | When the HTTP call finished — use this for ordering |

**Inbox / last message:** `role: "tool"` is excluded from `last_message` and does **not** bump `last_message_at`.

**LLM history:** stored tool rows are **not** replayed into later prompts. Only this turn’s live results are injected for the answering model.

### Loading history (Atlas)

`POST /elysium-atlas/agent/v1/get-agent-fields` is used by the visitor widget and **omits tool rows by default**.

Atlas dashboard / session transcript must send:

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "chat_session_id": "web-c0430c6c-0d3f-40ef-be30-864c7b9222b7",
  "fields": ["agent_name"],
  "include_tool_calls": true,
  "limit": 50
}
```

`chat_session_data.messages` then includes `role: "tool"` rows in chronological order. Tool rows count toward `limit`.

The widget must **not** send `include_tool_calls`.

### Frontend rendering

1. Keep a toggle (e.g. “Show tool calls”) — default hidden or collapsed so non-technical agents can ignore them.
2. When shown, render each `role: "tool"` row **between** the parent visitor message and the agent reply (sort all messages by `created_at`).
3. Use a collapsible JSON block for `request_payload` and `response_payload`.
4. If `request_payload_truncated` or `response_payload_truncated` is true, the matching payload is a **string preview**, not valid JSON — show a “truncated” badge.
5. Style `status: "error"` distinctly.
6. Do **not** treat tool rows as chat bubbles meant for the visitor.

Live socket payload and history row share the same fields. See [live-visitor-chat.md](./live-visitor-chat.md) for `tool_call_from_agent`.

---

## Roles

Same pattern as [agent RBAC](./frontend-agents-rbac-guide.md):

| Role | Tool access |
|------|-------------|
| `owner` | Create, update, delete, list, get |
| `admin` | Create, update, delete, list, get |
| `member` | **List and get only** — read-only |

Use JWT `role` to show/hide create, edit, and delete UI. The backend re-checks role in MongoDB on every request.

When JWT has **no `team_id`**, do not call tool APIs — redirect to team selection first.

---

## Endpoints

| Method | Path | Who | Description |
|--------|------|-----|-------------|
| `POST` | `/v1/create-tool` | owner, admin | Create a new tool |
| `POST` | `/v1/list-tools` | all members | Paginated list for active team |
| `POST` | `/v1/get-tool` | all members | Get one tool by `tool_id` |
| `POST` | `/v1/update-tool` | owner, admin | Partial update |
| `POST` | `/v1/delete-tool` | owner, admin | Hard delete |

All endpoints use **POST** with a JSON body (consistent with other Elysium Agents routes).

---

## Tool model (fields)

### Core fields

| Field | Type | Required (create) | Notes |
|-------|------|-------------------|-------|
| `name` | `string` | Yes | OpenAI function name. Lowercase snake_case: `[a-z][a-z0-9_]*`, max 64 chars |
| `display_name` | `string` | Yes | Human-readable label for the UI (e.g. `"Get Order Status"`). Max 128 chars |
| `description` | `string` | Yes | **LLM-facing** — when/how to call this tool. Max 2048 chars |
| `api_url` | `string` | Yes | Must start with `http://` or `https://` |
| `http_method` | `string` | Yes | One of: `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `auth` | `object` | No | Defaults to `{ "type": "none" }` |
| `parameters` | `array` | No | Defaults to `[]`. Max 50 items |

### Auth object (create)

| Field | Type | When required | Notes |
|-------|------|---------------|-------|
| `type` | `"none"` \| `"api_key"` | — | Default `"none"` |
| `location` | `"header"` \| `"query"` | If `type` is `api_key` | Where to send the token |
| `param_name` | `string` | If `type` is `api_key` | Header or query param name (e.g. `Authorization`, `api_key`) |
| `token` | `string` | If `type` is `api_key` | Raw secret value. **Write-only** — not returned on read |
| `token_prefix` | `"Bearer"` \| `"none"` | Optional | Default `"Bearer"`. Must be `"none"` when `location` is `"query"` |

**Header auth example:** `param_name: "Authorization"`, `token_prefix: "Bearer"`, `token: "sk-abc123"` → sent as `Authorization: Bearer sk-abc123`.

**Query auth example:** `location: "query"`, `param_name: "api_key"`, `token_prefix: "none"`, `token: "sk-abc123"` → sent as `?api_key=sk-abc123`.

### Parameter items (create / update)

Send as an **array** in the request. The API stores them as OpenAI JSON Schema.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | `string` | Yes | Same naming rules as tool `name` |
| `type` | see below | Yes | OpenAI-compatible parameter type |
| `description` | `string` | Yes | Max 1024 chars — shown to the LLM |
| `required` | `boolean` | No | Default `false` |
| `enum_values` | `string[]` | If `type` is `"enum"` | Unique, non-empty allowed values (max 50) |
| `items_type` | `string` | If `type` is `"array"` | Element type: `"string"`, `"number"`, `"integer"`, or `"boolean"` |
| `properties` | `array` | If `type` is `"object"` | Nested parameters (max 20). No nested `object` types |

> **Schema vs values (important for the UI)**  
> The create/edit form defines the **parameter schema** — the shape of arguments the LLM may send when it calls the tool. You are **not** collecting sample array items or a filled-in object instance.  
> - **enum** → user enters the list of **allowed values** (`enum_values`)  
> - **array** → user picks the **element type** (`items_type`); the LLM supplies the actual array at chat time  
> - **object** → user defines **nested field rows** (`properties`); the LLM supplies the object payload at chat time  
>
> See [Parameter builder UI (enum, array, object)](#parameter-builder-ui-enum-array-object) for wireframes and form state.

#### Supported `type` values

| `type` | Extra fields | Stored OpenAI schema |
|--------|--------------|------------------------|
| `"string"` | — | `{ "type": "string", "description": "..." }` |
| `"number"` | — | `{ "type": "number", ... }` |
| `"integer"` | — | `{ "type": "integer", ... }` |
| `"boolean"` | — | `{ "type": "boolean", ... }` |
| `"enum"` | `enum_values` | `{ "type": "string", "enum": [...], ... }` |
| `"array"` | `items_type` | `{ "type": "array", "items": { "type": "..." }, ... }` |
| `"object"` | `properties` | `{ "type": "object", "properties": { ... }, "required": [...] }` |

Parameter names must be **unique within a tool** (and within each `object` parameter's `properties`).

#### Required (`true` / `false`) — same as OpenAI tool calls

Each parameter accepts **`required: boolean`** (default `false`). This matches how OpenAI function calling works:

| API request (per parameter) | Stored OpenAI JSON Schema |
|-----------------------------|---------------------------|
| `"required": true` | Parameter name added to the parent `required` array |
| `"required": false` or omitted | Parameter name **not** in `required` (optional for the LLM) |

**Top-level example — API input:**

```json
"parameters": [
  { "name": "order_id", "type": "string", "description": "...", "required": true },
  { "name": "notes", "type": "string", "description": "...", "required": false }
]
```

**Stored / returned schema (what the LLM sees):**

```json
{
  "type": "object",
  "properties": {
    "order_id": { "type": "string", "description": "..." },
    "notes": { "type": "string", "description": "..." }
  },
  "required": ["order_id"]
}
```

For **`object`** parameters, each nested field in `properties` also supports `required: true | false`. Required nested names go into that object's own `required` array (not the root).

**Example — API input:**

```json
{
  "name": "address",
  "type": "object",
  "description": "Delivery address",
  "required": true,
  "properties": [
    { "name": "city", "type": "string", "description": "City", "required": true },
    { "name": "zip_code", "type": "string", "description": "ZIP", "required": false }
  ]
}
```

**Stored nested schema:**

```json
{
  "type": "object",
  "description": "Delivery address",
  "properties": {
    "city": { "type": "string", "description": "City" },
    "zip_code": { "type": "string", "description": "ZIP" }
  },
  "required": ["city"]
}
```

The root tool schema will list `"address"` in its top-level `required` array because the object param itself has `"required": true`.

**Frontend:** use a checkbox per parameter row. On load from API, set checked if the param name appears in `parameters.required` (top-level) or in `properties.<name>.required` (nested object fields).

**Example — enum parameter:**

```json
{
  "name": "unit",
  "type": "enum",
  "description": "Temperature unit",
  "required": true,
  "enum_values": ["celsius", "fahrenheit"]
}
```

**Example — array parameter:**

```json
{
  "name": "tags",
  "type": "array",
  "description": "Product tags to filter by",
  "required": false,
  "items_type": "string"
}
```

**Example — object parameter:**

```json
{
  "name": "address",
  "type": "object",
  "description": "Delivery address",
  "required": true,
  "properties": [
    {
      "name": "city",
      "type": "string",
      "description": "City name",
      "required": true
    },
    {
      "name": "zip_code",
      "type": "string",
      "description": "Postal code",
      "required": false
    }
  ]
}
```

### Response-only fields

| Field | Notes |
|-------|-------|
| `tool_id` | Mongo `_id` as string |
| `team_id` | Team the tool belongs to |
| `created_by_user_id` | User who created the tool |
| `is_active` | `true` by default; can be toggled via update |
| `created_at` / `updated_at` | ISO 8601 UTC strings |
| `auth.token_configured` | `true` if an API key was saved (token itself is never returned) |

### Parameters in responses

Stored and returned as OpenAI-style JSON Schema:

```json
{
  "type": "object",
  "properties": {
    "order_id": {
      "type": "string",
      "description": "The order ID to look up"
    },
    "unit": {
      "type": "string",
      "enum": ["celsius", "fahrenheit"],
      "description": "Temperature unit"
    }
  },
  "required": ["order_id"]
}
```

When **building the create/edit form**, use the array format. When **displaying** a saved tool, read from `parameters.properties` and `parameters.required`.

---

## API reference

### Create tool

`POST /elysium-agents/elysium-atlas/tools/v1/create-tool`

**Request — API key (header):**

```json
{
  "name": "get_order_status",
  "display_name": "Get Order Status",
  "description": "Use when the user asks about order status or tracking.",
  "api_url": "https://api.example.com/orders",
  "http_method": "POST",
  "auth": {
    "type": "api_key",
    "location": "header",
    "param_name": "Authorization",
    "token_prefix": "Bearer",
    "token": "your-service-token"
  },
  "parameters": [
    {
      "name": "order_id",
      "type": "string",
      "description": "The order ID to look up",
      "required": true
    }
  ]
}
```

**Request — no auth:**

```json
{
  "name": "get_weather",
  "display_name": "Get Weather",
  "description": "Use when the user asks about weather for a city.",
  "api_url": "https://api.example.com/weather",
  "http_method": "GET",
  "auth": { "type": "none" },
  "parameters": [
    {
      "name": "city",
      "type": "string",
      "description": "City name",
      "required": true
    }
  ]
}
```

**Success `200`:**

```json
{
  "success": true,
  "tool": {
    "tool_id": "674a1b2c3d4e5f6789012345",
    "team_id": "699e9bf195fcec2ed8ef6763",
    "created_by_user_id": "69568df774db787c7f93b86b",
    "name": "get_order_status",
    "display_name": "Get Order Status",
    "description": "Use when the user asks about order status or tracking.",
    "api_url": "https://api.example.com/orders",
    "http_method": "POST",
    "auth": {
      "type": "api_key",
      "location": "header",
      "param_name": "Authorization",
      "token_prefix": "Bearer",
      "token_configured": true
    },
    "parameters": {
      "type": "object",
      "properties": {
        "order_id": {
          "type": "string",
          "description": "The order ID to look up"
        }
      },
      "required": ["order_id"]
    },
    "is_active": true,
    "created_at": "2026-06-15T10:30:00+00:00",
    "updated_at": "2026-06-15T10:30:00+00:00"
  }
}
```

**Conflict `409`:** duplicate tool name within the team.

---

### List tools

`POST /elysium-agents/elysium-atlas/tools/v1/list-tools`

**Request:**

```json
{
  "page": 1,
  "limit": 50,
  "include_inactive": false
}
```

| Field | Default | Notes |
|-------|---------|-------|
| `page` | `1` | Min 1 |
| `limit` | `50` | Min 1, max 100 |
| `include_inactive` | `false` | Set `true` to include tools with `is_active: false` |

**Success `200`:**

```json
{
  "success": true,
  "tools": [ "...tool objects..." ],
  "total": 12,
  "page": 1,
  "limit": 50,
  "total_pages": 1,
  "has_next": false,
  "has_prev": false
}
```

Sorted by `updated_at` descending.

---

### Get tool

`POST /elysium-agents/elysium-atlas/tools/v1/get-tool`

**Request:**

```json
{
  "tool_id": "674a1b2c3d4e5f6789012345"
}
```

**Success `200`:** `{ "success": true, "tool": { ... } }`

**Not found `404`:** tool does not exist or invalid ID.

Access is allowed if the user is a member of the **tool's team** (resolved from the tool document).

---

### Update tool

`POST /elysium-agents/elysium-atlas/tools/v1/update-tool`

Partial update — only send fields that change. **`tool_id` is required.**

**Request example:**

```json
{
  "tool_id": "674a1b2c3d4e5f6789012345",
  "display_name": "Get Order Status",
  "description": "Use when the user asks about order status, tracking, or delivery.",
  "is_active": true,
  "parameters": [
    {
      "name": "order_id",
      "type": "string",
      "description": "The order ID to look up",
      "required": true
    }
  ]
}
```

**Auth update rules:**

| Scenario | Frontend behavior |
|----------|-------------------|
| Keep existing token | Omit `auth.token` (or omit entire `auth` block) |
| Replace token | Send `auth.token` with new value |
| Change auth type to none | Send `auth: { "type": "none" }` |
| Switch to api_key | Send full `location`, `param_name`, and `token` |

Updating `parameters` **replaces the full parameter list** — send the complete array, not a diff.

**Success `200`:** `{ "success": true, "tool": { ... } }`

**Not found `404`:** invalid or missing tool.

**Conflict `409`:** renamed tool conflicts with existing name in team.

---

### Delete tool

`POST /elysium-agents/elysium-atlas/tools/v1/delete-tool`

**Request:**

```json
{
  "tool_id": "674a1b2c3d4e5f6789012345"
}
```

**Success `200`:**

```json
{
  "success": true,
  "message": "Tool deleted successfully."
}
```

This is a **hard delete** — no soft-delete endpoint yet (use `is_active: false` via update to disable without deleting).

---

## Validation errors

FastAPI returns **`400`** with Pydantic validation messages for invalid bodies, for example:

- Tool/parameter name not snake_case
- `api_url` missing `http://` or `https://`
- `api_key` auth missing `location`, `param_name`, or `token`
- `token_prefix` not `"none"` when `location` is `"query"`
- Duplicate parameter names in one tool
- `enum` without `enum_values`, or duplicate/empty enum values
- `array` without `items_type`
- `object` without `properties`, or duplicate nested property names
- `enum_values`, `items_type`, or `properties` on scalar types (`string`, `number`, `integer`, `boolean`)

Example:

```json
{
  "detail": [
    {
      "type": "value_error",
      "loc": ["body", "name"],
      "msg": "Value error, Tool name must start with a lowercase letter...",
      "input": "Get-Order"
    }
  ]
}
```

Surface the first `detail[].msg` (or a friendly mapped message) in the form.

---

## Error responses (auth / business)

| Status | Message | When |
|--------|---------|------|
| `401` | Token invalid/expired | Missing or bad JWT |
| `403` | `No team context. Select a team to continue.` | JWT missing `team_id` |
| `403` | `You are not a member of this team.` | List — user not on team |
| `403` | `You are not authorized to access this tool.` | Get — not on tool's team |
| `403` | `You are not authorized to create or modify tools for this team.` | Create/update/delete — member role |
| `404` | `Tool not found.` | Invalid `tool_id` or deleted tool |
| `409` | `A tool with this name already exists for this team.` | Duplicate name |
| `500` | Generic internal error | Unexpected server failure |

Always handle `403` gracefully; membership and role can change after login.

---

## Frontend UI checklist

### Tools list page

- Call `list-tools` on mount (and on pagination change).
- Show: `display_name`, `name` (optional subtitle), `description` (truncated), `http_method`, `api_url`, `is_active`, `updated_at`.
- Show auth badge: `No auth` vs `API key (header)` vs `API key (query)` using `auth.type` and `auth.location`.
- **owner/admin:** show Create, Edit, Delete actions.
- **member:** read-only list + detail view.

### Create / edit form (suggested sections)

1. **Basic info** — `display_name`, `name` (function identifier), `description` (label as “When should the AI call this tool?”)
2. **API** — `api_url`, `http_method`
3. **Authorization** — radio: None / API Key → if API Key: Header vs Query, param name, token input (password field), Bearer toggle for header
4. **Parameters** — repeatable rows (see [Parameter builder UI](#parameter-builder-ui-enum-array-object) below)

### Parameter builder UI (enum, array, object)

Each **top-level parameter** is one card/row with:

| Control | Always shown | Notes |
|---------|--------------|-------|
| Name | Yes | snake_case, e.g. `order_id`, `tags`, `address` |
| Type | Yes | Dropdown — see per-type extras below |
| Description | Yes | Shown to the LLM; label as “What is this argument?” |
| Required | Yes | Checkbox — maps to API `required: true` |

When the user changes **Type**, show or hide the extra controls below. Do **not** send `enum_values`, `items_type`, or `properties` for scalar types (`string`, `number`, `integer`, `boolean`).

#### Scalar types (`string`, `number`, `integer`, `boolean`)

No extra fields. One row → one API object:

```json
{ "name": "order_id", "type": "string", "description": "The order ID", "required": true }
```

#### Enum (reference — already working)

| Extra control | Maps to API |
|---------------|-------------|
| Multi-value chips / “Add value” input | `enum_values: string[]` |

```
┌─ Parameter ─────────────────────────────────────────────┐
│ Name: unit          Type: [enum ▼]     [✓] Required     │
│ Description: Temperature unit for the reading             │
│ Allowed values: [celsius ×] [fahrenheit ×]  [+ Add]     │
└───────────────────────────────────────────────────────────┘
```

Submit:

```json
{
  "name": "unit",
  "type": "enum",
  "description": "Temperature unit for the reading",
  "required": true,
  "enum_values": ["celsius", "fahrenheit"]
}
```

#### Array — what to show and what to send

**What the user configures:** only the **type of each element** (`items_type`). They do **not** enter example tags, IDs, or list items.

| Extra control | Options | Maps to API |
|---------------|---------|-------------|
| “Element type” dropdown | `string`, `number`, `integer`, `boolean` | `items_type` |

Helper copy: *“When the AI calls this tool, it will pass a JSON array whose items are all of this type.”*

```
┌─ Parameter ─────────────────────────────────────────────┐
│ Name: tags          Type: [array ▼]    [ ] Required       │
│ Description: Product tags to filter by                    │
│ Element type: [string ▼]   ← items_type                   │
└───────────────────────────────────────────────────────────┘
```

**Form state (TypeScript):**

```typescript
interface ArrayParameterRow {
  name: string;
  type: "array";
  description: string;
  required: boolean;
  items_type: "string" | "number" | "integer" | "boolean";
}
```

**Submit to `create-tool` / `update-tool`:**

```json
{
  "name": "tags",
  "type": "array",
  "description": "Product tags to filter by",
  "required": false,
  "items_type": "string"
}
```

**After save — read from `tool.parameters` (OpenAI schema):**

```json
"tags": {
  "type": "array",
  "items": { "type": "string" },
  "description": "Product tags to filter by"
}
```

**Load into edit form:** if `def.type === "array"`, set `type: "array"` and `items_type` from `def.items.type` (see `schemaPropertyToRow` below).

**Detail / read-only view:** show e.g. `tags — array of string (optional)`.

**Defaults when user picks type `array`:** set `items_type: "string"` so submit is valid without an extra click.

**Not supported:** array of enum, array of object, or nested arrays. Only scalar `items_type`.

#### Object — what to show and what to send

**What the user configures:** the **fields inside the object** (`properties`). Each nested field is a mini parameter row (same types as top-level **except** `object` — one level only).

| Extra UI | Maps to API |
|----------|-------------|
| Indented “Object fields” section with **Add field** | `properties: ToolNestedParameterInput[]` |

Each **nested row** has: name, type (`string` \| `number` \| `integer` \| `boolean` \| `enum` \| `array`), description, required checkbox — plus enum/array extras on that nested row when applicable.

```
┌─ Parameter ─────────────────────────────────────────────┐
│ Name: address       Type: [object ▼]   [✓] Required     │
│ Description: Delivery address for the shipment            │
│                                                           │
│   Object fields                          [+ Add field]    │
│   ┌─ Field ───────────────────────────────────────────┐  │
│   │ city      [string ▼]  [✓] Req  City name          │  │
│   └───────────────────────────────────────────────────┘  │
│   ┌─ Field ───────────────────────────────────────────┐  │
│   │ zip_code  [string ▼]  [ ] Req  Postal code        │  │
│   └───────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

**Form state:**

```typescript
interface NestedParameterRow {
  name: string;
  type: "string" | "number" | "integer" | "boolean" | "enum" | "array";
  description: string;
  required: boolean;
  enum_values?: string[];
  items_type?: "string" | "number" | "integer" | "boolean";
}

interface ObjectParameterRow {
  name: string;
  type: "object";
  description: string;
  required: boolean;
  properties: NestedParameterRow[];
}
```

**Submit:**

```json
{
  "name": "address",
  "type": "object",
  "description": "Delivery address for the shipment",
  "required": true,
  "properties": [
    {
      "name": "city",
      "type": "string",
      "description": "City name",
      "required": true
    },
    {
      "name": "zip_code",
      "type": "string",
      "description": "Postal code",
      "required": false
    }
  ]
}
```

**Nested enum inside object** — same chip UI as top-level enum, on the nested row:

```json
{
  "name": "status",
  "type": "enum",
  "description": "Shipment status filter",
  "required": false,
  "enum_values": ["pending", "shipped", "delivered"]
}
```

**Nested array inside object** — element type dropdown on the nested row:

```json
{
  "name": "sku_list",
  "type": "array",
  "description": "SKUs to include",
  "required": true,
  "items_type": "string"
}
```

**After save — stored schema:**

```json
"address": {
  "type": "object",
  "description": "Delivery address for the shipment",
  "properties": {
    "city": { "type": "string", "description": "City name" },
    "zip_code": { "type": "string", "description": "Postal code" }
  },
  "required": ["city"]
}
```

**Load into edit form:** if `def.type === "object"`, map each entry in `def.properties` with `schemaPropertyToRow` and nested `def.required` (see below).

**Detail / read-only view:** indent nested fields, e.g.:

```
address (object, required) — Delivery address for the shipment
  • city — string, required
  • zip_code — string, optional
```

**Validation before submit:**

- `object` must have **at least one** nested field (`properties.length >= 1`)
- Nested names unique within that object
- Switching a row from `object` → `array` clears `properties`; switching to scalar clears `properties`, `items_type`, and `enum_values`

#### Full create-tool example (mixed types)

Request body fragment for `POST .../create-tool`:

```json
{
  "name": "search_products",
  "display_name": "Search products",
  "description": "Search the product catalog by filters",
  "api_url": "https://api.example.com/products/search",
  "http_method": "POST",
  "auth": { "type": "none" },
  "parameters": [
    {
      "name": "query",
      "type": "string",
      "description": "Free-text search query",
      "required": true
    },
    {
      "name": "tags",
      "type": "array",
      "description": "Product tags to filter by",
      "required": false,
      "items_type": "string"
    },
    {
      "name": "unit",
      "type": "enum",
      "description": "Weight unit for min_weight",
      "required": false,
      "enum_values": ["kg", "lb"]
    },
    {
      "name": "filters",
      "type": "object",
      "description": "Structured filters",
      "required": false,
      "properties": [
        {
          "name": "min_weight",
          "type": "number",
          "description": "Minimum product weight",
          "required": false
        },
        {
          "name": "in_stock_only",
          "type": "boolean",
          "description": "Only return in-stock items",
          "required": false
        }
      ]
    }
  ]
}
```

At chat time the LLM might call this tool with runtime arguments like:

```json
{
  "query": "running shoes",
  "tags": ["sports", "footwear"],
  "unit": "kg",
  "filters": { "min_weight": 0.5, "in_stock_only": true }
}
```

Those runtime values are **not** entered in the tool builder — only the schema above is.

### Edit form — token field UX

- Do **not** pre-fill the token input on edit.
- Show helper text: “Leave blank to keep existing key” when `auth.token_configured === true`.
- If user clears auth type to `none`, confirm before removing stored credentials.

### Name field UX

- **`display_name`** — free text for UI labels; any readable string up to 128 chars.
- **`name`** — validate client-side: lowercase, underscores only, must start with a letter.
- Show that `name` is the function identifier the LLM will call; `display_name` is what users see in the dashboard.

### Parameters form ↔ API

**Suggested `ParameterRow` union (form state):**

```typescript
type ParameterRow =
  | { name: string; type: ToolScalarType; description: string; required: boolean }
  | { name: string; type: "enum"; description: string; required: boolean; enum_values: string[] }
  | { name: string; type: "array"; description: string; required: boolean; items_type: ToolArrayItemType }
  | { name: string; type: "object"; description: string; required: boolean; properties: NestedParameterRow[] };
```

**Submit (create/update)** — convert form rows to the API `parameters` array (handle type-specific fields):

```typescript
function rowToParameter(row: ParameterRow): ToolParameterInput {
  const base = {
    name: row.name,
    type: row.type,
    description: row.description,
    required: row.required,
  };
  if (row.type === "enum") {
    return { ...base, enum_values: row.enum_values };
  }
  if (row.type === "array") {
    return { ...base, items_type: row.items_type };
  }
  if (row.type === "object") {
    return {
      ...base,
      properties: row.properties.map((nested) => ({
        name: nested.name,
        type: nested.type,
        description: nested.description,
        required: nested.required,
        ...(nested.type === "enum" ? { enum_values: nested.enum_values } : {}),
        ...(nested.type === "array" ? { items_type: nested.items_type } : {}),
      })),
    };
  }
  return base;
}

parameters: rows.map(rowToParameter);
```

**Load (edit)** — convert response schema back to form rows:

```typescript
function schemaPropertyToRow(
  name: string,
  def: Record<string, unknown>,
  required: Set<string>,
): ParameterRow {
  if (def.type === "array") {
    const items = def.items as { type: string };
    return {
      name,
      type: "array",
      description: String(def.description ?? ""),
      required: required.has(name),
      items_type: items.type as ToolArrayItemType,
    };
  }
  if (def.type === "object") {
    const nestedProps = (def.properties ?? {}) as Record<string, Record<string, unknown>>;
    const nestedRequired = new Set((def.required as string[]) ?? []);
    return {
      name,
      type: "object",
      description: String(def.description ?? ""),
      required: required.has(name),
      properties: Object.entries(nestedProps).map(([nestedName, nestedDef]) =>
        schemaPropertyToRow(nestedName, nestedDef, nestedRequired),
      ),
    };
  }
  if (Array.isArray(def.enum)) {
    return {
      name,
      type: "enum",
      description: String(def.description ?? ""),
      required: required.has(name),
      enum_values: def.enum as string[],
    };
  }
  return {
    name,
    type: def.type as ToolScalarType,
    description: String(def.description ?? ""),
    required: required.has(name),
  };
}

const props = tool.parameters.properties ?? {};
const required = new Set(tool.parameters.required ?? []);
const rows = Object.entries(props).map(([name, def]) =>
  schemaPropertyToRow(name, def as Record<string, unknown>, required),
);
```

---

## TypeScript types (optional)

```typescript
type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
type ToolScalarType = "string" | "number" | "integer" | "boolean";
type ToolArrayItemType = "string" | "number" | "integer" | "boolean";
type ToolLeafParameterType =
  | ToolScalarType
  | "enum"
  | "array";
type ToolParameterType = ToolLeafParameterType | "object";
type AuthType = "none" | "api_key";
type AuthLocation = "header" | "query";
type TokenPrefix = "Bearer" | "none";

interface ToolNestedParameterInput {
  name: string;
  type: ToolLeafParameterType;
  description: string;
  required?: boolean;
  enum_values?: string[];
  items_type?: ToolArrayItemType;
}

interface ToolParameterInput {
  name: string;
  type: ToolParameterType;
  description: string;
  required?: boolean;
  enum_values?: string[];
  items_type?: ToolArrayItemType;
  properties?: ToolNestedParameterInput[];
}

interface ToolAuthInput {
  type: AuthType;
  location?: AuthLocation;
  param_name?: string;
  token?: string;
  token_prefix?: TokenPrefix;
}
interface ToolCallingConfig {
  enabled?: boolean;
  max_rounds?: number;
  max_executions_per_turn?: number;
  parallel_calls_per_round?: boolean;
  stop_on_error?: boolean;
  include_tool_history_in_llm?: boolean;
  max_tool_history_in_llm?: number;
}

interface LlmContextConfig {
  max_chat_history_messages?: number;
}

interface AgentToolSettings {
  tool_ids?: string[];
  tool_calling_config?: ToolCallingConfig;
  llm_context_config?: LlmContextConfig;
}

interface CreateToolRequest {
  name: string;
  display_name: string;
  description: string;
  api_url: string;
  http_method: HttpMethod;
  auth?: ToolAuthInput;
  parameters?: ToolParameterInput[];
}

interface ToolAuthResponse {
  type: AuthType;
  location?: AuthLocation;
  param_name?: string;
  token_prefix?: TokenPrefix;
  token_configured?: boolean;
}

interface ToolParametersSchema {
  type: "object";
  properties: Record<string, Record<string, unknown>>;
  required?: string[];
}

interface Tool {
  tool_id: string;
  team_id: string;
  created_by_user_id: string;
  name: string;
  display_name: string;
  description: string;
  api_url: string;
  http_method: HttpMethod;
  auth: ToolAuthResponse;
  parameters: ToolParametersSchema;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface UpdateToolRequest {
  tool_id: string;
  name?: string;
  display_name?: string;
  description?: string;
  api_url?: string;
  http_method?: HttpMethod;
  auth?: Partial<ToolAuthInput>;
  parameters?: ToolParameterInput[];
  is_active?: boolean;
}
```

---

## Example fetch (create)

```typescript
const res = await fetch(
  `${API_BASE}/elysium-agents/elysium-atlas/tools/v1/create-tool`,
  {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${sessionToken}`,
    },
    body: JSON.stringify({
      name: "get_order_status",
      display_name: "Get Order Status",
      description: "Use when the user asks about order status or tracking.",
      api_url: "https://api.example.com/orders",
      http_method: "POST",
      auth: {
        type: "api_key",
        location: "header",
        param_name: "Authorization",
        token_prefix: "Bearer",
        token: apiKeyFromForm,
      },
      parameters: [
        {
          name: "order_id",
          type: "string",
          description: "The order ID to look up",
          required: true,
        },
      ],
    }),
  }
);

const data = await res.json();
if (!data.success) {
  // handle data.message + res.status
}
const toolId = data.tool.tool_id;
```

---

## Quick reference

```
member  → list-tools, get-tool
member  → cannot create, update, or delete

owner   → full CRUD
admin   → full CRUD
```

**Remember:** `display_name` is for the UI; `name` is the LLM function identifier; `description` is the LLM instruction field. `tool_id` in requests/responses maps to Mongo `_id`.

For team/session JWT details, see [backend-team-rbac-guide.md](./backend-team-rbac-guide.md). For agent RBAC patterns, see [frontend-agents-rbac-guide.md](./frontend-agents-rbac-guide.md).
