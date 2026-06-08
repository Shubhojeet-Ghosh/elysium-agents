# Email Recipient Rules API — CC / BCC Planner Guide

Define **when** to add team members to **CC** or **BCC** on AI-generated email replies, using natural-language conditions. Rules are scoped to **`team_id`**.

At runtime, the **AI Recipients Generator** flow node loads these rules, the LLM checks which conditions match the thread, and resolves `cc_user_ids` / `bcc_user_ids` to email addresses from `email-users`. Rule CC/BCC are **merged with inbound CC/BCC** on the trigger message (deduped) before draft or send — see [email-flow-nodes.md](./email-flow-nodes.md) § `ai_recipients_generator`.

For listing team members (to pick `user_id`s), see [departments-api.md](./departments-api.md) or [email-auth-login-api.md](./email-auth-login-api.md).  
For department routing (separate, independent feature), see [email-routing-rules-api.md](./email-routing-rules-api.md).

---

## Independent from department routing

**Department routing** and **recipient rules** do **not** affect each other.

| Feature | What it sets | Constraint |
| ------- | ------------ | ---------- |
| [Routing rules](./email-routing-rules-api.md) | Which **department** owns the thread (`email-threads.department_id`) | `department_id` must belong to the team |
| **Recipient rules** (this API) | Who gets **CC / BCC** on the AI reply | Each `user_id` must belong to the **team** — **not** the routed department |

**Cross-department CC/BCC is allowed and expected.** Example:

- Routing sends the thread to **Claims**
- A recipient rule matches and CCs a user in **Sales** or **Legal**

That is valid. The API does **not** check whether CC/BCC users are in the same department as the routed thread.

At runtime, the flow runs **AI Department Router** and **AI Recipients Generator** as **separate nodes** — each loads its own rules; neither blocks the other.

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
| Create a rule | `POST /email-recipient-rules/v1/create` |
| Update a rule | `POST /email-recipient-rules/v1/update` |
| List team rules | `POST /email-recipient-rules/v1/list-team-rules` |

No `Authorization` header required (prototype).

**Typical setup:**

```
1. List team users        →  POST /email-auth/v1/list-team-users  →  save user_id + email
2. Create recipient rules →  NL condition + cc_user_ids / bcc_user_ids
3. (Later) flow runs      →  AI Recipients Generator applies matching rules to outgoing reply
```

---

## Frontend buttons / screens

| Screen | API | Notes |
|--------|-----|-------|
| **Recipient rules list** | `list-team-rules` | Table: rule name, prompt snippet, CC count, BCC count |
| **Add rule** | `create` | Text field for `rule_name`, textarea for `recipient_prompt` + multi-select users for CC and BCC |
| **Edit rule** | `update` | Same form + `recipient_rule_id` |

**User picker:** Load team users first — store **`user_id`** (Mongo `_id` string), display **name** + **email** in the UI.

---

## Data model

### Collection: `email-recipient-rules`

```json
{
  "_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "rule_name": "Enterprise deal CC leadership",
  "recipient_prompt": "When the email mentions a deal over $1000 or an enterprise contract, add leadership to the loop.",
  "cc_user_ids": [
    "674b2c3d4e5f6789012346",
    "674c3d4e5f6789012347"
  ],
  "bcc_user_ids": [
    "674d1a2b3c4e5f6789012348"
  ],
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

| Field | Description |
| ----- | ----------- |
| `recipient_rule_id` | API alias for Mongo `_id` (24-char hex) |
| `team_id` | Team that owns this rule |
| `rule_name` | Human-readable label for the rule (max 256 chars) |
| `recipient_prompt` | Natural-language **when** to apply this CC/BCC plan |
| `cc_user_ids` | Team member `user_id`s to CC when condition matches (max 20) |
| `bcc_user_ids` | Team member `user_id`s to BCC when condition matches (max 20) |

**Validation:**

- At least **one** of `cc_user_ids` or `bcc_user_ids` must be non-empty.
- Every `user_id` must exist in `email-users` and belong to the same **`team_id`**.
- **No check** against routed department or CC/BCC user’s department — cross-department recipients are OK.
- Duplicate ids in a list are deduplicated on save.

**Indexes:** `team_id`

---

## Rule object (API response)

```json
{
  "recipient_rule_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "rule_name": "Enterprise deal CC leadership",
  "recipient_prompt": "When the email mentions a deal over $1000...",
  "cc_user_ids": ["674b2c3d4e5f6789012346", "674c3d4e5f6789012347"],
  "bcc_user_ids": ["674d1a2b3c4e5f6789012348"],
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

---

## 1. Create Recipient Rule

```
POST /elysium-agents/email-recipient-rules/v1/create
```

### Headers

```http
Content-Type: application/json
```

### Request body

```json
{
  "team_id": "team_123",
  "rule_name": "Enterprise deal CC leadership",
  "recipient_prompt": "When the email mentions a deal over $1000 or an enterprise contract, CC the founder and sales lead.",
  "cc_user_ids": [
    "674b2c3d4e5f6789012346",
    "674c3d4e5f6789012347"
  ],
  "bcc_user_ids": [
    "674d1a2b3c4e5f6789012348"
  ]
}
```

| Field | Required | Description |
| ----- | -------- | ----------- |
| `team_id` | Yes | Team scope |
| `rule_name` | Yes | Human-readable label (1–256 chars) |
| `recipient_prompt` | Yes | NL condition — when to add these people to CC/BCC |
| `cc_user_ids` | No* | Array of team member `user_id`s to CC |
| `bcc_user_ids` | No* | Array of team member `user_id`s to BCC |

\* At least one of `cc_user_ids` or `bcc_user_ids` must contain at least one id.

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Recipient rule created successfully.",
  "rule": {
    "recipient_rule_id": "674a1b2c3d4e5f6789012345",
    "team_id": "team_123",
    "rule_name": "Enterprise deal CC leadership",
    "recipient_prompt": "When the email mentions a deal over $1000...",
    "cc_user_ids": ["674b2c3d4e5f6789012346", "674c3d4e5f6789012347"],
    "bcc_user_ids": ["674d1a2b3c4e5f6789012348"],
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:00:00Z"
  }
}
```

**Frontend:** store `rule.recipient_rule_id` for edit flows.

### Error — `400`

| Message | Cause |
| ------- | ----- |
| `At least one cc_user_id or bcc_user_id is required.` | Both lists empty |
| `rule_name cannot be empty.` | Blank or whitespace-only `rule_name` |
| `Invalid cc user_id: ...` | Bad or unknown user id |
| `Invalid bcc user_id: ...` | Bad or unknown user id |
| `User ... in cc does not belong to this team.` | User team mismatch |
| `User ... in bcc does not belong to this team.` | User team mismatch |

### Error — `422`

Pydantic validation (e.g. missing required fields, list too long).

---

## 2. Update Recipient Rule

```
POST /elysium-agents/email-recipient-rules/v1/update
```

### Request body

```json
{
  "recipient_rule_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "rule_name": "Refund escalation CC",
  "recipient_prompt": "When refund amount is over $500, CC the support manager.",
  "cc_user_ids": ["674b2c3d4e5f6789012346"],
  "bcc_user_ids": []
}
```

| Field | Required | Description |
| ----- | -------- | ----------- |
| `recipient_rule_id` | Yes | Rule to update |
| `team_id` | Yes | Must match the rule's team |
| `rule_name` | Yes | Updated human-readable label |
| `recipient_prompt` | Yes | Updated NL condition |
| `cc_user_ids` | No* | Updated CC list |
| `bcc_user_ids` | No* | Updated BCC list |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Recipient rule updated successfully.",
  "rule": { "...full rule object..." }
}
```

### Error — `403`

```json
{
  "success": false,
  "message": "Recipient rule does not belong to this team."
}
```

### Error — `404`

```json
{
  "success": false,
  "message": "Recipient rule not found."
}
```

---

## 3. List Team Recipient Rules

```
POST /elysium-agents/email-recipient-rules/v1/list-team-rules
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
  "message": "Team recipient rules fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "rules": [
    {
      "recipient_rule_id": "674a1b2c3d4e5f6789012345",
      "team_id": "team_123",
      "rule_name": "Enterprise deal CC leadership",
      "recipient_prompt": "When the email mentions a deal over $1000...",
      "cc_user_ids": ["674b2c3d4e5f6789012346"],
      "bcc_user_ids": [],
      "created_at": "2026-06-07T10:00:00Z",
      "updated_at": "2026-06-07T10:00:00Z"
    }
  ]
}
```

Rules are sorted by `created_at` ascending.

---

## Frontend examples

### Load team users (for pickers)

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function listTeamUsers(teamId) {
  const res = await fetch(`${BASE}/email-auth/v1/list-team-users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);
  return data.users; // { user_id, name, email, department_name, ... }
}
```

### Create recipient rule

```javascript
async function createRecipientRule({
  teamId,
  ruleName,
  recipientPrompt,
  ccUserIds = [],
  bccUserIds = [],
}) {
  const res = await fetch(`${BASE}/email-recipient-rules/v1/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: teamId,
      rule_name: ruleName,
      recipient_prompt: recipientPrompt,
      cc_user_ids: ccUserIds,
      bcc_user_ids: bccUserIds,
    }),
  });
  const data = await res.json();
  if (!res.ok || !data.success) throw new Error(data.message);
  return data.rule;
}

// Example: CC founder on big deals
const users = await listTeamUsers("team_123");
const founder = users.find((u) => u.email === "founder@company.com");

await createRecipientRule({
  teamId: "team_123",
  ruleName: "Enterprise deal CC leadership",
  recipientPrompt:
    "When the customer mentions a deal over $1000 or enterprise pricing, CC leadership.",
  ccUserIds: [founder.user_id],
  bccUserIds: [],
});
```

### Update recipient rule

```javascript
async function updateRecipientRule({
  recipientRuleId,
  teamId,
  ruleName,
  recipientPrompt,
  ccUserIds = [],
  bccUserIds = [],
}) {
  const res = await fetch(`${BASE}/email-recipient-rules/v1/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      recipient_rule_id: recipientRuleId,
      team_id: teamId,
      rule_name: ruleName,
      recipient_prompt: recipientPrompt,
      cc_user_ids: ccUserIds,
      bcc_user_ids: bccUserIds,
    }),
  });
  const data = await res.json();
  if (!res.ok || !data.success) throw new Error(data.message);
  return data.rule;
}
```

### List recipient rules

```javascript
async function listRecipientRules(teamId) {
  const res = await fetch(`${BASE}/email-recipient-rules/v1/list-team-rules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);
  return data.rules;
}
```

---

## Use case (what `recipient_prompt` means)

**Important:** This example assumes the thread was already routed to **Claims** by a routing rule. The CC user below can be from **any department** on the team — that is intentional.

**Rule:**

| Field | Value |
| ----- | ----- |
| `rule_name` | “Refund escalation CC” |
| `recipient_prompt` | “When the email mentions refund over $500 or legal action” |
| `cc_user_ids` | `[manager_user_id]` |
| `bcc_user_ids` | `[compliance_user_id]` |

**Inbound email:**

> “I want a full refund of $800 or I will contact my lawyer.”

**At runtime:** LLM matches this rule → outgoing reply CCs manager, BCCs compliance (emails resolved from `user_id`s at runtime), **plus** any CC/BCC already on the inbound message.

**Another email:**

> “Thanks, issue resolved!”

No rule matches → default **To** (customer) and **inbound CC/BCC preserved**; no extra CC/BCC from this rule.

---

## Runtime status

| Layer | Status |
| ----- | ------ |
| Create / update / list APIs | **Implemented** |
| LLM **AI Recipients Generator** flow node | **Implemented** |

Rules are consumed at flow runtime by `ai_recipients_generator` ([email-flow-nodes.md](./email-flow-nodes.md)).

---

## Quick reference

| API | Method | Path | Body |
| --- | ------ | ---- | ---- |
| Create | `POST` | `/email-recipient-rules/v1/create` | `{ team_id, rule_name, recipient_prompt, cc_user_ids?, bcc_user_ids? }` |
| Update | `POST` | `/email-recipient-rules/v1/update` | `{ recipient_rule_id, team_id, rule_name, recipient_prompt, cc_user_ids?, bcc_user_ids? }` |
| List | `POST` | `/email-recipient-rules/v1/list-team-rules` | `{ team_id }` |

---

## Related docs

- [email-routing-rules-api.md](./email-routing-rules-api.md) — department routing rules
- [departments-api.md](./departments-api.md) — departments + list team users
- [email-flow-plan.md](./email-flow-plan.md) — AI Recipients Generator node
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — email agent setup
