# Custom Tools APIs — frontend guide

Reference for building the **team custom tools** UI in Elysium Atlas. Tools are external HTTP integrations configured like OpenAI function calling — the LLM uses `name`, `description`, and `parameters` at runtime (execution wiring comes later).

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
4. **Parameters** — repeatable rows: name, type (`string` \| `number` \| `integer` \| `boolean` \| `enum` \| `array` \| `object`), description, required checkbox
   - **enum** → show multi-value input for `enum_values`
   - **array** → show `items_type` dropdown
   - **object** → nested sub-rows for `properties` (one level only; no nested objects)

### Edit form — token field UX

- Do **not** pre-fill the token input on edit.
- Show helper text: “Leave blank to keep existing key” when `auth.token_configured === true`.
- If user clears auth type to `none`, confirm before removing stored credentials.

### Name field UX

- **`display_name`** — free text for UI labels; any readable string up to 128 chars.
- **`name`** — validate client-side: lowercase, underscores only, must start with a letter.
- Show that `name` is the function identifier the LLM will call; `display_name` is what users see in the dashboard.

### Parameters form ↔ API

**Submit (create/update)** — convert form rows to array (handle type-specific fields):

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
