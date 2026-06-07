# Email Tool Definitions API — Register External Tools for LLM

Register HTTP tools the email AI agent can call. Each tool stores an endpoint, method, description, and input schema — the LLM uses `name` + `description` + `input_schema` to decide when and how to call it.

**Execution** (calling ticket APIs, etc.) lives under [email-tools-api.md](./email-tools-api.md).  
**This doc** covers **registering** tools in Mongo collection `email-tools`.

For agent setup, see [email-ai-agent-setup.md](./email-ai-agent-setup.md).

---

## Base URL

```
{SERVER_BASE_URL}/elysium-agents
```

**Example (local dev):**
```
http://localhost:7000/elysium-agents
```

---

## When to use these APIs

| Action | API |
|--------|-----|
| Register a tool | `POST /email-tool-definitions/v1/create` |
| List team tools | `POST /email-tool-definitions/v1/list-team-tools` |
| Delete a tool | `POST /email-tool-definitions/v1/delete` |

No `Authorization` header required (prototype).

**Typical flow:**

```
1. Create tool definition   →  save tool_id (Mongo _id)
2. (Later) Attach tool_ids to agent or load all team tools at runtime
3. LLM sees tool definitions → decides to call → executor hits endpoint_url
```

---

## ID model

Mongo `_id` is the only stored identifier. The API returns it as **`tool_id`** (24-char hex string) — same pattern as `department_id` and `agent_id`.

---

## Tool object (API response shape)

```json
{
  "tool_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "name": "get_ticket_status",
  "display_name": "Get Ticket Status",
  "description": "Call when the customer provides a ticket number and asks for status or resolution date.",
  "endpoint_url": "http://localhost:7000/elysium-agents/email-tools/v1/get-ticket-status",
  "http_method": "POST",
  "inputs": [
    {
      "name": "ticket_number",
      "type": "string",
      "description": "Ticket number, e.g. TKT-1001",
      "required": true
    }
  ],
  "input_schema": {
    "type": "object",
    "properties": {
      "ticket_number": {
        "type": "string",
        "description": "Ticket number, e.g. TKT-1001"
      }
    },
    "required": ["ticket_number"]
  },
  "status": "active",
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

| Field | Description |
|-------|-------------|
| `tool_id` | Mongo `_id` as string |
| `name` | LLM tool name — `snake_case`, unique per team |
| `display_name` | Human-readable label for UI |
| `description` | **When** the LLM should call this tool |
| `endpoint_url` | Full URL to HTTP endpoint |
| `http_method` | `GET` or `POST` |
| `inputs` | Friendly input definitions (what you pass at create) |
| `input_schema` | Auto-built JSON Schema for LLM `parameters` |
| `status` | `active` |

---

## MongoDB: `email-tools`

```json
{
  "_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "name": "get_ticket_status",
  "display_name": "Get Ticket Status",
  "description": "Call when the customer provides a ticket number...",
  "endpoint_url": "http://localhost:7000/elysium-agents/email-tools/v1/get-ticket-status",
  "http_method": "POST",
  "inputs": [ ... ],
  "input_schema": { ... },
  "status": "active",
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

**Indexes:** `team_id`, unique `(team_id, name)`.

---

## LLM tool definition (built from stored doc)

At agent runtime, convert a stored tool to:

```json
{
  "type": "function",
  "function": {
    "name": "get_ticket_status",
    "description": "Call when the customer provides a ticket number...",
    "parameters": {
      "type": "object",
      "properties": {
        "ticket_number": {
          "type": "string",
          "description": "Ticket number, e.g. TKT-1001"
        }
      },
      "required": ["ticket_number"]
    }
  }
}
```

**HTTP mapping at execution (future):**

| Method | LLM args → request |
|--------|-------------------|
| `POST` | JSON body |
| `GET` | Query string parameters |

---

## 1. Create Tool

### Route

```
POST /elysium-agents/email-tool-definitions/v1/create
```

### Request body

```json
{
  "team_id": "team_123",
  "name": "get_ticket_status",
  "display_name": "Get Ticket Status",
  "description": "Call when the customer provides a ticket number and asks for status, remarks, or expected resolution date. Do not call if no ticket number is given.",
  "endpoint_url": "http://localhost:7000/elysium-agents/email-tools/v1/get-ticket-status",
  "http_method": "POST",
  "inputs": [
    {
      "name": "ticket_number",
      "type": "string",
      "description": "Ticket number provided by the customer, e.g. TKT-1001",
      "required": true
    }
  ]
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `team_id` | string | Yes | Team scope |
| `name` | string | Yes | `snake_case`, unique per team, max 64 chars |
| `display_name` | string | Yes | UI label |
| `description` | string | Yes | When the LLM should use this tool |
| `endpoint_url` | string | Yes | Full HTTP URL |
| `http_method` | string | Yes | `GET` or `POST` |
| `inputs` | array | No | Default `[]` — use for tools with no parameters |

### Input item fields

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | Yes | Parameter name sent to the endpoint |
| `type` | string | Yes | `string`, `number`, `integer`, or `boolean` |
| `description` | string | Yes | Tells the LLM what value to extract |
| `required` | boolean | No | Default `false` |

### Example: GET tool with no inputs

```json
{
  "team_id": "team_123",
  "name": "create_ticket",
  "display_name": "Create Support Ticket",
  "description": "Call when the customer wants to raise a new support ticket and no ticket number exists yet.",
  "endpoint_url": "http://localhost:7000/elysium-agents/email-tools/v1/create-ticket",
  "http_method": "GET",
  "inputs": []
}
```

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Tool created successfully.",
  "tool": {
    "tool_id": "674a1b2c3d4e5f6789012345",
    "team_id": "team_123",
    "name": "get_ticket_status",
    "display_name": "Get Ticket Status",
    "description": "Call when the customer provides a ticket number...",
    "endpoint_url": "http://localhost:7000/elysium-agents/email-tools/v1/get-ticket-status",
    "http_method": "POST",
    "inputs": [ ... ],
    "input_schema": { ... },
    "status": "active",
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:00:00Z"
  }
}
```

### Error — `400`

| Message | Cause |
|---------|-------|
| `name must be snake_case...` | Invalid tool name format |
| `A tool named 'x' already exists for this team.` | Duplicate name |
| `http_method must be one of: GET, POST` | Invalid method |
| `Invalid input type...` | Bad input `type` |

### Frontend example

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function createToolDefinition(payload) {
  const res = await fetch(`${BASE}/email-tool-definitions/v1/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to create tool");
  }

  return data.tool;
}
```

---

## 2. List Team Tools

### Route

```
POST /elysium-agents/email-tool-definitions/v1/list-team-tools
```

### Request body

```json
{
  "team_id": "team_123"
}
```

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Team tools fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "tools": [
    {
      "tool_id": "674a1b2c3d4e5f6789012345",
      "name": "get_ticket_status",
      "display_name": "Get Ticket Status",
      "description": "...",
      "endpoint_url": "...",
      "http_method": "POST",
      "inputs": [ ... ],
      "input_schema": { ... },
      "status": "active",
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

---

## 3. Delete Tool

### Route

```
POST /elysium-agents/email-tool-definitions/v1/delete
```

### Request body

```json
{
  "tool_id": "674a1b2c3d4e5f6789012345"
}
```

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Tool deleted successfully.",
  "tool_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "name": "get_ticket_status"
}
```

### Error — `404`

```json
{
  "success": false,
  "message": "Tool not found."
}
```

---

## Full setup example (register built-in ticket tools)

```javascript
const BASE = "http://localhost:7000/elysium-agents";
const teamId = "team_123";

// Register get ticket status
await createToolDefinition({
  team_id: teamId,
  name: "get_ticket_status",
  display_name: "Get Ticket Status",
  description:
    "Look up an existing support ticket when the customer provides a ticket number and asks about status, remarks, or resolution date.",
  endpoint_url: `${BASE}/email-tools/v1/get-ticket-status`,
  http_method: "POST",
  inputs: [
    {
      name: "ticket_number",
      type: "string",
      description: "Ticket number, e.g. TKT-1001",
      required: true,
    },
  ],
});

// Register create ticket
await createToolDefinition({
  team_id: teamId,
  name: "create_ticket",
  display_name: "Create Support Ticket",
  description:
    "Create a new support ticket when the customer wants to raise one and has not provided an existing ticket number.",
  endpoint_url: `${BASE}/email-tools/v1/create-ticket`,
  http_method: "GET",
  inputs: [],
});
```

---

## Code layout (for developers)

```
services/email_agent_services/email_tool_definitions/
├── email_tool_definitions_constants.py
├── email_tool_schema_builder.py       # inputs[] → input_schema, LLM tool shape
├── email_tool_definitions_mongo_services.py
└── email_tool_definitions_services.py

routes/email_agent/email_tool_definition_routes.py
config/email_tool_definition_models.py
controllers/email_agent_controller_files/email_tool_definition_controllers.py
```

---

## Quick reference

| API | Method | Path | Auth | Body |
|-----|--------|------|------|------|
| Create tool | `POST` | `/email-tool-definitions/v1/create` | No | `{ team_id, name, display_name, description, endpoint_url, http_method, inputs? }` |
| List team tools | `POST` | `/email-tool-definitions/v1/list-team-tools` | No | `{ team_id }` |
| Delete tool | `POST` | `/email-tool-definitions/v1/delete` | No | `{ tool_id }` |

| Collection | Purpose |
|------------|---------|
| `email-tools` | Registered external tool definitions (not ticket JSON data) |

---

## What's next

- Tool executor service (call `endpoint_url` with LLM-generated args)
- Attach `tool_ids[]` on `email-ai-agents`
- Agent reply loop: LLM → tool call → executor → final reply

---

## Related docs

- [email-tools-api.md](./email-tools-api.md) — built-in ticket tool **execution** APIs
- [email-knowledge-api.md](./email-knowledge-api.md) — team knowledge for RAG
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — agent create + Gmail sync
