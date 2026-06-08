# Email Routing Rules API — Department Router Guide

Define **when** inbound email threads should be routed to a **department**, using natural-language conditions evaluated by the LLM in the **AI Department Router** flow node.

Rules are scoped to **`team_id`**. Each rule points at a **`department_id`** and includes a **`routing_prompt`** — the condition the LLM uses at runtime.

For creating departments, see [departments-api.md](./departments-api.md).  
For the flow node that consumes these rules, see [email-flow-plan.md](./email-flow-plan.md) §5.3 **AI Department Router**.

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
| Create a rule | `POST /email-routing-rules/v1/create` |
| Update a rule | `POST /email-routing-rules/v1/update` |
| List team rules | `POST /email-routing-rules/v1/list-team-rules` |
| Delete a rule | `POST /email-routing-rules/v1/delete` |

No `Authorization` header required (prototype).

**Typical setup:**

```
1. Create departments     →  POST /email-departments/v1/create
2. Create routing rules   →  one rule per routing condition (same or different departments)
3. Flow runs on inbound   →  AI Department Router loads active rules for team_id → LLM picks department
4. Thread updated         →  email-threads.department_id set → members see thread in their dept inbox
```

**Independent from recipient rules:** Routing only picks a department for the thread. It does **not** limit who can appear on CC/BCC — see [email-recipient-rules-api.md](./email-recipient-rules-api.md).

---

## Recommended fields (beyond department + prompt)

Your core idea (`team_id` + `department_id` + natural-language condition) is the right shape. We also store:

| Field | Why |
| ----- | --- |
| **`rule_name`** | Short label for admin UI (“Route refund emails”) |
| **`routing_prompt`** | Natural-language **when** to route to this department (LLM condition) |
| **`priority`** | Lower number = listed first for the LLM (default `100`). Helps when several rules could match |
| **`is_fallback`** | One rule per team can be the catch-all when nothing else matches |
| **`status`** | `active` \| `inactive` — disable without deleting |

**Not stored on the rule (resolved at runtime):** department **name** / **description** — loaded from `email-departments` when building the LLM prompt.

**Future (not in MVP API):** `example_snippets[]` for few-shot routing, `agent_id` scope for per-agent overrides.

---

## Data model

### Collection: `email-routing-rules`

```json
{
  "_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "department_id": "674b2c3d4e5f6789012346",
  "rule_name": "Refund requests",
  "routing_prompt": "Route here when the customer asks for a refund, return, chargeback, or mentions dissatisfaction with a purchase and wants money back.",
  "priority": 10,
  "is_fallback": false,
  "status": "active",
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

| Field | Description |
| ----- | ----------- |
| `routing_rule_id` | API alias for Mongo `_id` (24-char hex) |
| `team_id` | Team scope — rules only apply to this team's threads |
| `department_id` | Target department when this rule matches |
| `rule_name` | Human-readable label |
| `routing_prompt` | NL condition for the LLM router |
| `priority` | Sort order (ascending) when building the rule list for the LLM |
| `is_fallback` | If `true`, used when no other rule matches (max one active fallback per team) |
| `status` | `active` or `inactive` |

**Indexes:** `team_id`, `team_id + status + priority`, `department_id`

---

## Rule object (API response)

```json
{
  "routing_rule_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "department_id": "674b2c3d4e5f6789012346",
  "rule_name": "Refund requests",
  "routing_prompt": "Route here when the customer asks for a refund...",
  "priority": 10,
  "is_fallback": false,
  "status": "active",
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

---

## 1. Create Routing Rule

```
POST /elysium-agents/email-routing-rules/v1/create
```

**Body:**

```json
{
  "team_id": "team_123",
  "department_id": "674b2c3d4e5f6789012346",
  "rule_name": "Refund requests",
  "routing_prompt": "Route here when the customer asks for a refund, return, or chargeback.",
  "priority": 10,
  "is_fallback": false
}
```

| Field | Required | Description |
| ----- | -------- | ----------- |
| `team_id` | Yes | Team that owns this rule |
| `department_id` | Yes | Mongo `_id` from `email-departments` (must belong to same team) |
| `rule_name` | Yes | Admin label |
| `routing_prompt` | Yes | Natural-language routing condition for the LLM |
| `priority` | No | Default `100`; lower = higher precedence in rule list |
| `is_fallback` | No | Default `false`; if `true`, clears fallback on other team rules |

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Routing rule created successfully.",
  "rule": { "...rule object..." }
}
```

### Error — `400`

| Message | Cause |
| ------- | ----- |
| `Invalid department_id. Department does not exist.` | Bad id |
| `Department does not belong to this team.` | Department team mismatch |

---

## 2. Update Routing Rule

```
POST /elysium-agents/email-routing-rules/v1/update
```

**Body:** same fields as create plus `routing_rule_id` and optional `status`:

```json
{
  "routing_rule_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "department_id": "674b2c3d4e5f6789012346",
  "rule_name": "Refund & returns",
  "routing_prompt": "Route here when the email mentions refund, return, exchange, or damaged product.",
  "priority": 5,
  "is_fallback": false,
  "status": "active"
}
```

---

## 3. List Team Rules

```
POST /elysium-agents/email-routing-rules/v1/list-team-rules
```

**Body:**

```json
{
  "team_id": "team_123",
  "include_inactive": false
}
```

Returns rules sorted by `priority` ascending, then `created_at`.

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Team routing rules fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "rules": [ "...rule objects..." ]
}
```

---

## 4. Delete Routing Rule

```
POST /elysium-agents/email-routing-rules/v1/delete
```

**Body:**

```json
{
  "routing_rule_id": "674a1b2c3d4e5f6789012345"
}
```

---

## How the LLM router uses rules (runtime — flow engine)

When the **AI Department Router** node runs:

1. Load all **`status: active`** rules for `team_id` via internal service (same data as list API).
2. Join **`department_name`** + **`department_description`** from `email-departments`.
3. Build LLM prompt:
   - Thread summary + latest inbound message
   - Numbered list of rules: `{ rule_name, department_name, routing_prompt, priority }`
   - Instruction: pick **one** `department_id`, return JSON `{ department_id, reason, confidence }`
4. If no rule matches and a rule has **`is_fallback: true`**, use that department.
5. Set **`email-threads.department_id`** on the thread.

**Example rules for one team:**

| priority | department | routing_prompt (short) |
| -------- | ---------- | ------------------------ |
| 10 | Sales | Customer asks about pricing, demo, or enterprise plan |
| 20 | Support | Technical issue, bug, or how-to question |
| 100 | General | `is_fallback: true` — “When no other rule clearly applies” |

---

## Frontend UX

| Screen | Action |
| ------ | ------ |
| **Routing rules list** | `list-team-rules` — table of rule_name, department, priority, active |
| **Add rule** | Pick department dropdown + textarea for `routing_prompt` |
| **Fallback toggle** | One rule marked “Default / fallback department” → `is_fallback: true` |
| **Workflow node** | **AI Department Router** shows count of active rules for team (read-only); rules edited here, not duplicated on agent |

---

## Example: create Sales + Support rules

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function createRoutingRule(teamId, departmentId, ruleName, routingPrompt, priority = 100) {
  const res = await fetch(`${BASE}/email-routing-rules/v1/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: teamId,
      department_id: departmentId,
      rule_name: ruleName,
      routing_prompt: routingPrompt,
      priority,
      is_fallback: false,
    }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);
  return data.rule;
}

// Sales — priority 10
await createRoutingRule(
  "team_123",
  "674a1b2c3d4e5f6789012345",
  "Sales inquiries",
  "Route when the customer asks about pricing, quotes, demos, or purchasing.",
  10,
);

// Support — priority 20
await createRoutingRule(
  "team_123",
  "674b2c3d4e5f6789012346",
  "Technical support",
  "Route when the customer reports a bug, error, login issue, or needs technical help.",
  20,
);

// Fallback — priority 100
await createRoutingRule(
  "team_123",
  "674c3d4e5f6789012347",
  "General inbox",
  "Use when no other routing rule clearly applies.",
  100,
  // set is_fallback: true in body for the last call
);
```

---

## Quick reference

| API | Method | Path |
| --- | ------ | ---- |
| Create | `POST` | `/email-routing-rules/v1/create` |
| Update | `POST` | `/email-routing-rules/v1/update` |
| List | `POST` | `/email-routing-rules/v1/list-team-rules` |
| Delete | `POST` | `/email-routing-rules/v1/delete` |

---

## Related docs

- [departments-api.md](./departments-api.md) — create departments first
- [email-flow-plan.md](./email-flow-plan.md) — AI Department Router node
- [email-threads-api.md](./email-threads-api.md) — thread `department_id` visibility
