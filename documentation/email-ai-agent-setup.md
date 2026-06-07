# Email AI Agent — Configuration & Thread Sync Guide (MVP)

Configure an email AI agent with a **system prompt** and **knowledge base**, sync Gmail **threads** (inbound + outbound), and build a Gmail-style inbox in your app.

**Collections:** `email-ai-agents`, `email-knowledge`, `email-threads`, `email-thread-messages`

---

## What is an email AI agent?

An agent links:

- A **name** and **Gmail inbox** — for sending/receiving email
- A **system prompt** — instructions for how the AI should behave
- A **knowledge_id** — team knowledge indexed in Qdrant (see [email-knowledge-api.md](./email-knowledge-api.md))
- An **llm_model** — model code used when the agent generates replies
- A **reply_action** — how replies are delivered: Gmail draft only, or auto-send when confidence is high enough (see [Reply action](#reply-action-draft-vs-auto-send)); controls which **tail node** appears on the agent’s workflow ([Agent ↔ workflow sync](#agent--workflow-sync))
- A **flow_id** (when attached) — links a workflow graph; KB/tools/prompt on that flow **sync back** to the agent when the workflow is saved or attached

When active, sync pulls **complete email threads** into Mongo — both emails you receive and replies you send from Gmail. AI reply generation (coming next) runs the agent’s **workflow** ([email-flow-plan.md](./email-flow-plan.md)) using the same fields configured here — kept in sync with the workflow bidirectionally.

---

## Prerequisites

```
1. Login            →  JWT (user_id + team_id)
2. Connect Gmail    →  email-gmail_accounts (gmail_account_id)
3. Create knowledge →  POST /email-knowledge/v1/create  →  knowledge_id
4. Register tools   →  POST /email-tool-definitions/v1/create  →  tool_id(s)
5. Create agent     →  name + gmail_account_id + system_prompt + knowledge_id + tool_ids + llm_model + reply_action (+ optional email_format_template)
6. Trigger sync     →  fetch up to 20 threads with recent activity
7. List threads     →  inbox list (snippet only)
8. Get thread       →  full conversation with bodies
```

See [gmail-oauth-setup.md](./gmail-oauth-setup.md), [email-auth-login-api.md](./email-auth-login-api.md), [email-knowledge-api.md](./email-knowledge-api.md), and [email-tool-definitions-api.md](./email-tool-definitions-api.md).

---

## Base URL

```
http://localhost:7000/elysium-agents
```

---

## Frontend buttons needed

| Button              | API                                          | When to show                                              |
| ------------------- | -------------------------------------------- | --------------------------------------------------------- |
| **Create Knowledge**| `POST /email-knowledge/v1/create`            | Before agent setup — user provides policy/FAQ text        |
| **Create Agent**    | `POST /email-ai-agents/v1/create`            | User picked inbox, prompt, and knowledge                  |
| **View Agent**      | `POST /email-ai-agents/v1/get-agent`         | Agent settings / detail page                              |
| **Update Agent**    | `POST /email-ai-agents/v1/update`            | User edits agent configuration                            |
| **Sync Inbox**      | `POST /email-ai-agents/v1/trigger-sync`      | Agent exists and `sync_status !== "syncing"`              |
| **Refresh Threads** | `POST /email-ai-agents/v1/list-team-threads` | Inbox list page / after sync                              |
| **Open Thread**     | `POST /email-ai-agents/v1/get-thread`        | User clicks a thread row; show `ai_action` draft if ready |
| **Send AI Draft**   | `POST /email-ai-agents/v1/send-thread-draft` | User clicks Send on draft panel                           |
| **Refresh Agents**  | `POST /email-ai-agents/v1/list-team-agents`  | Agent list page                                           |

---

## Sync UX flow

```
User clicks "Sync Inbox"
        ↓
POST /trigger-sync  →  instant response { sync_status: "syncing" }
        ↓
Poll POST /list-team-agents every 2–3s
        ↓
When sync_status === "idle"  →  POST /list-team-threads
When sync_status === "error" →  show agent.last_sync_error
        ↓
User clicks a thread  →  POST /get-thread
```

---

## How thread sync works (production approach)

1. **Discover threads** — `threads.list?q=after:{cutoff} category:primary` (up to 20 per sync)
   - First sync cutoff: `activated_at` (`last_synced_at` is null)
   - Later syncs: `last_synced_at` on `email-ai-agents`
   - **Primary inbox only** — Promotions, Social, Updates, and Forums are excluded
   - Includes **inbound and outbound** activity within those Primary threads (not `is:unread` only)

2. **Fetch full thread** — `threads.get?format=full` for each thread
   - Returns every message in the conversation with full MIME bodies

3. **Store only new messages** — watermark filter + dedup
   - **First sync:** store all messages in discovered threads (full conversation)
   - **Later syncs:** only messages with `received_at > last_synced_at`
   - Dedup: unique `(gmail_account_id, gmail_message_id)`
   - `direction`: `inbound` or `outbound` (outbound = Gmail `SENT` label)

4. **Advance watermark** — set `last_synced_at` to the newest stored message time (or `now` if nothing new)

5. **Update thread summary** — upsert into `email-threads` only when new messages were inserted

**Example back-and-forth:**

- Customer emails you → sync → inbound message stored
- You reply in Gmail → sync → outbound reply stored in same `thread_id`
- Customer replies again → sync → only the new inbound message is inserted; full thread available via `get-thread`

---

## Reply action (draft vs auto-send)

After the flow generates a reply, **`reply_action`** controls what happens next.

| `reply_action.mode` | Behaviour |
| ------------------- | --------- |
| **`draft`** (default) | Save the AI reply as a **Gmail draft** on that thread in the user's inbox. User reviews and sends manually. | Workflow tail node: **Save Gmail Draft** |
| **`auto_send`** | If the flow's **confidence score ≥ `auto_send_min_confidence`**, send the reply automatically via Gmail. If confidence is below the threshold, **fall back to draft** (same as `draft` mode). | Workflow tail node: **Send Email** (draft fallback at runtime) |

**Confidence** is a number from **0.0 to 1.0** produced when the AI evaluates how well it can answer the email (using thread context, KB, and tool results). It is computed at flow runtime — not passed by the frontend on each email.

### Config object

```json
{
  "reply_action": {
    "mode": "draft",
    "auto_send_min_confidence": 0.8
  }
}
```

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `mode` | string | `"draft"` | `"draft"` or `"auto_send"` |
| `auto_send_min_confidence` | number | `0.8` | Min confidence to auto-send (0–1). Used only when `mode` is `"auto_send"`. |

### Frontend UX

| Control | Maps to |
| ------- | ------- |
| **“Save as draft”** radio (recommended default) | `{ "mode": "draft", "auto_send_min_confidence": 0.8 }` |
| **“Auto-send when confident”** radio | `{ "mode": "auto_send", "auto_send_min_confidence": <slider> }` |
| Confidence slider (show when auto-send selected) | `auto_send_min_confidence` — e.g. 0.7, 0.8, 0.9 |

Send `reply_action` on **create** and **update**. Omit on create → defaults to draft + `0.8`.

**Example — draft only:**

```json
"reply_action": { "mode": "draft", "auto_send_min_confidence": 0.8 }
```

**Example — auto-send when confidence ≥ 80%:**

```json
"reply_action": { "mode": "auto_send", "auto_send_min_confidence": 0.8 }
```

> **Note:** Auto-send is applied by the flow **Send Email** node when the engine ships ([email-flow-plan.md](./email-flow-plan.md)). Until then, `reply_action` is stored on the agent and returned by the API; the workflow UI should still show the correct tail node from this config.

---

## Agent ↔ workflow sync

The agent document and the **workflow canvas** must always show the **same** KB, tools, prompt, model, and reply policy. Sync is **bidirectional** — editing either side updates the other.

Full workflow design: [email-flow-plan.md](./email-flow-plan.md) §5.2.

### How it works

| You edit… | API | Backend sync | Other side updates |
| --------- | --- | -------------- | ------------------- |
| Agent settings | `POST /email-ai-agents/v1/update` | `push_agent_to_flow` | Flow node `config` (e.g. Read KB gets new `knowledge_id`) |
| Workflow (KB, tools, …) | `POST /email-flows/v1/update` | `push_flow_to_agent` | Agent doc fields (`knowledge_id`, `tool_ids`, …) |
| Attach workflow to agent | `POST /email-ai-agents/v1/update` with `flow_id` | `push_flow_to_agent` (once) | Agent doc filled from flow node selections |

**Runtime:** The flow engine reads the **agent document** when processing email. Flow → agent sync keeps that document current after workflow edits.

### Syncable fields

| Field | Agent (`email-ai-agents`) | Workflow node |
| ----- | ------------------------- | ------------- |
| `knowledge_id` | ✓ | **Read KB** — `config.knowledge_id` |
| `tool_ids` | ✓ | **Read Tools** — `config.tool_ids` |
| `system_prompt` | ✓ | **System Prompt** — `config.system_prompt` |
| `llm_model` | ✓ | **Generate Email** — `config.llm_model` |
| `reply_action` | ✓ | **Save Gmail Draft** / **Send Email** — `config.reply_action` |
| `flow_id` | ✓ | Which workflow graph is linked |

**Agent-only (not from flow):** `name`, `gmail_account_id`, sync state.

**Flow-only (not copied to agent):** `generate_email.format_prompt`, `read_kb.limit`, `call_external_tool` post-draft tool list, node layout.

### Examples

**Workflow → agent:** You pick **Return Policy v2** on the **Read KB** node and save the flow. Agent settings immediately show `knowledge_id` for v2 — no separate agent form save required (backend `push_flow_to_agent`).

**Agent → workflow:** You change `tool_ids` on the agent settings page. The linked flow’s **Read Tools** node updates; reopening the canvas shows the new tools.

**Attach flow:** You create a custom flow with KB `kb_1` and two tools, then set `"flow_id": "..."` on the agent. Attach runs **flow → agent** sync — agent doc gets `kb_1` and those tool ids even if the agent form had different values before.

### Tail node (draft vs send)

`reply_action` syncs like other fields — tail node type on canvas follows `reply_action.mode`:

```
... → Generate Email → Call External Tool → [tail] → Stop

reply_action.mode = draft      →  Save Gmail Draft
reply_action.mode = auto_send  →  Send Email  (draft fallback if confidence low)
```

Changing tail mode on **either** agent settings **or** the tail node config syncs to the other side.

### Frontend behaviour

1. **Agent settings** — edit fields → save agent → refresh workflow view (`push_agent_to_flow` on server).
2. **Workflow builder (power users)** — edit KB/tools on node panel → save flow → **refresh agent settings** (`push_flow_to_agent` on server).
3. **Attach workflow** — user picks flow on agent → save → agent form reflects flow selections.
4. Render nodes with **`binding`** chips; values must match agent API after every save.

**Shared flows:** If multiple agents use the same `flow_id`, saving the flow updates **all** attached agents (team template pattern).

### Flow-only settings (power users)

These stay on the flow JSON only — they do **not** sync to the agent doc:

| Node | Flow-only config |
| ---- | ---------------- |
| **Generate Email** | `format_prompt`, optional body template |
| **Read KB** | chunk `limit` (default 5) |
| **Call External Tool** | post-draft tool allowlist |

---

## 1. Create Email AI Agent

```
POST /elysium-agents/email-ai-agents/v1/create
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "name": "Support Agent",
  "gmail_account_id": "674a1b2c3d4e5f6789012345",
  "system_prompt": "You are a helpful support agent. Answer customer emails professionally using the provided knowledge base.",
  "email_format_template": "Use a professional tone.\n\nGreeting: Hi {customer_name},\n\nBody: 2-3 short paragraphs answering the question.\n\nClosing:\nBest regards,\nSupport Team",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tool_ids": [
    "674d1a2b3c4e5f6789012345",
    "674d2b3c4d5e6f7890123456"
  ],
  "llm_model": "gpt-4o-mini",
  "reply_action": {
    "mode": "draft",
    "auto_send_min_confidence": 0.8
  },
  "routing_rule_ids": [
    "674a1b2c3d4e5f6789012345",
    "674b2c3d4e5f6789012346"
  ],
  "recipient_rule_ids": [
    "674c3d4e5f6789012347"
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Display name for the agent |
| `gmail_account_id` | Yes | Mongo `_id` from `email-gmail_accounts` |
| `system_prompt` | Yes | Instructions for how the agent should behave |
| `email_format_template` | No | Optional string describing how generated reply emails should be structured (sections, tone, sign-off). Passed to the **Generate Email** flow node at reply time. Omit or `""` → no extra format constraint beyond `system_prompt`. Max 10,000 chars. |
| `knowledge_id` | Yes | UUID from `POST /email-knowledge/v1/create` (must belong to same team) |
| `tool_ids` | Yes | Array of Mongo `_id` strings from `email-tools` (1–20 tools, same team) |
| `llm_model` | Yes | LLM model code (e.g. `gpt-4o-mini`, `claude-sonnet-4-5`) — stored on agent, used at reply time |
| `reply_action` | No | Reply delivery policy — see [Reply action](#reply-action-draft-vs-auto-send). Defaults to `{ "mode": "draft", "auto_send_min_confidence": 0.8 }` |
| `routing_rule_ids` | No | Mongo `_id`s from `email-routing-rules` (0–50, same team). Which department routing rules this agent uses — see [email-routing-rules-api.md](./email-routing-rules-api.md) |
| `recipient_rule_ids` | No | Mongo `_id`s from `email-recipient-rules` (0–50, same team). Which CC/BCC rules this agent uses — see [email-recipient-rules-api.md](./email-recipient-rules-api.md) |
| `flow_id` | No | Custom workflow to attach (planned). On attach, **flow → agent** sync copies KB/tools/prompt from workflow nodes into this agent |

`user_id` and `team_id` come from the JWT — do **not** pass them in the body.

On create: `status=active`, `activated_at=now` — only thread activity **after** this time is discovered on first sync. Default system workflow is linked automatically when the flow engine ships; until then only agent fields apply.

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Email AI agent created successfully.",
  "agent": {
    "agent_id": "674c3d4e5f6789012349",
    "name": "Support Agent",
    "gmail_account_id": "674a1b2c3d4e5f6789012345",
    "user_id": "674b2c3d4e5f6789012346",
    "team_id": "team_123",
    "status": "active",
    "activated_at": "2026-06-07T10:00:00+00:00",
    "sync_status": "idle",
    "last_synced_at": null,
    "last_sync_error": null,
    "inbox_name": "Support Inbox",
    "email_address": "support@gmail.com",
    "system_prompt": "You are a helpful support agent...",
    "email_format_template": "Use a professional tone.\n\nGreeting: Hi {customer_name},\n\nBody: 2-3 short paragraphs.\n\nClosing:\nBest regards,\nSupport Team",
    "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "tool_ids": [
      "674d1a2b3c4e5f6789012345",
      "674d2b3c4d5e6f7890123456"
    ],
    "llm_model": "gpt-4o-mini",
    "reply_action": {
      "mode": "draft",
      "auto_send_min_confidence": 0.8
    },
    "routing_rule_ids": ["674a1b2c3d4e5f6789012345"],
    "recipient_rule_ids": ["674c3d4e5f6789012347"],
    "created_at": "2026-06-07T10:00:00+00:00",
    "updated_at": "2026-06-07T10:00:00+00:00"
  }
}
```

**Frontend:** store `agent.agent_id` for sync and thread APIs.

### Error — `400`

| Message | Cause |
|---------|-------|
| `Invalid knowledge_id. Knowledge does not exist.` | `knowledge_id` not found in `email-knowledge` |
| `Knowledge does not belong to your team.` | Knowledge belongs to another team |
| `At least one tool_id is required.` | Empty `tool_ids` array |
| `Invalid tool_id(s): ...` | One or more tool ids not found in `email-tools` |
| `Invalid routing_rule_id: ...` | Routing rule not found |
| `Routing rule ... does not belong to your team.` | Routing rule team mismatch |
| `Invalid recipient_rule_id: ...` | Recipient rule not found |
| `Recipient rule ... does not belong to your team.` | Recipient rule team mismatch |
| `Tool ... does not belong to your team.` | Tool belongs to another team |
| `Tool ... is not active.` | Tool `status` is not `active` |
| `Invalid gmail_account_id. Gmail inbox does not exist.` | Bad Gmail account id |
| `Gmail inbox is disconnected. Connect it before creating an agent.` | Gmail account `status=revoked` |
| `Gmail inbox does not belong to your team.` | Gmail account team mismatch |

### Error — `401`

Missing or invalid JWT, or `user_id` / `team_id` missing from token.

### Frontend example

```javascript
const BASE = "http://localhost:7000/elysium-agents";
const token = localStorage.getItem("auth_token");

async function createEmailAiAgent(name, gmailAccountId, systemPrompt, knowledgeId, toolIds, llmModel, replyAction, routingRuleIds, recipientRuleIds, emailFormatTemplate) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      name,
      gmail_account_id: gmailAccountId,
      system_prompt: systemPrompt,
      email_format_template: emailFormatTemplate ?? "",
      knowledge_id: knowledgeId,
      tool_ids: toolIds,
      llm_model: llmModel,
      reply_action: replyAction ?? { mode: "draft", auto_send_min_confidence: 0.8 },
      routing_rule_ids: routingRuleIds ?? [],
      recipient_rule_ids: recipientRuleIds ?? [],
    }),
  });

  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to create agent");
  }

  return data.agent;
}
```

---

## 2. Get Email AI Agent

Fetch a single agent by `agent_id`. Returns the same shape as create/list.

```
POST /elysium-agents/email-ai-agents/v1/get-agent
```

**Body:**

```json
{
  "agent_id": "674c3d4e5f6789012349"
}
```

No JWT required (prototype).

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Email AI agent fetched successfully.",
  "agent": {
    "agent_id": "674c3d4e5f6789012349",
    "name": "Support Agent",
    "gmail_account_id": "674a1b2c3d4e5f6789012345",
    "user_id": "674b2c3d4e5f6789012346",
    "team_id": "team_123",
    "status": "active",
    "sync_status": "idle",
    "system_prompt": "You are a helpful support agent...",
    "email_format_template": "Use a professional tone.\n\nGreeting: Hi {customer_name},\n\nBody: 2-3 short paragraphs.\n\nClosing:\nBest regards,\nSupport Team",
    "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "tool_ids": ["674d1a2b3c4e5f6789012345"],
    "llm_model": "gpt-4o-mini",
    "reply_action": {
      "mode": "draft",
      "auto_send_min_confidence": 0.8
    },
    "inbox_name": "Support Inbox",
    "email_address": "support@gmail.com",
    "created_at": "2026-06-07T10:00:00+00:00",
    "updated_at": "2026-06-07T10:00:00+00:00"
  }
}
```

### Error — `404`

```json
{
  "success": false,
  "message": "Email AI agent not found."
}
```

### Example

```javascript
async function getEmailAiAgent(agentId) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/get-agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId }),
  });

  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to fetch agent");
  }

  return data.agent;
}
```

---

## 3. Update Email AI Agent

Updates an agent's configuration. Same fields as create plus `agent_id`. Does **not** change sync state (`sync_status`, `last_synced_at`, `activated_at`).

```
POST /elysium-agents/email-ai-agents/v1/update
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "agent_id": "674c3d4e5f6789012349",
  "name": "Support Agent v2",
  "gmail_account_id": "674a1b2c3d4e5f6789012345",
  "system_prompt": "You are a helpful support agent. Always cite the knowledge base.",
  "email_format_template": "Keep replies under 200 words. Use bullet points for action items.",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tool_ids": [
    "674d1a2b3c4e5f6789012345",
    "674d2b3c4d5e6f7890123456"
  ],
  "llm_model": "claude-sonnet-4-5",
  "reply_action": {
    "mode": "auto_send",
    "auto_send_min_confidence": 0.8
  },
  "routing_rule_ids": ["674a1b2c3d4e5f6789012345"],
  "recipient_rule_ids": ["674c3d4e5f6789012347", "674d1a2b3c4e5f6789012348"]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `agent_id` | Yes | Mongo `_id` of the agent to update |
| `name` | Yes | Display name |
| `gmail_account_id` | Yes | Connected Gmail inbox |
| `system_prompt` | Yes | LLM instructions |
| `email_format_template` | No | Optional reply layout/format template — same as create |
| `knowledge_id` | Yes | Team knowledge UUID |
| `tool_ids` | Yes | Tool definition ids from `email-tools` |
| `llm_model` | Yes | Model code |
| `reply_action` | No | Reply delivery policy — same shape as create |
| `routing_rule_ids` | No | Attached routing rule ids (same team) |
| `recipient_rule_ids` | No | Attached recipient rule ids (same team) |
| `flow_id` | No | Attach or change workflow; triggers **flow → agent** sync on save (planned) |

`team_id` comes from JWT — agent must belong to that team. Successful update also runs **agent → flow** sync when `flow_id` is set (planned).

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Email AI agent updated successfully.",
  "agent": { "...full agent object..." }
}
```

### Error — `403`

```json
{
  "success": false,
  "message": "Email AI agent does not belong to your team."
}
```

### Error — `404`

```json
{
  "success": false,
  "message": "Email AI agent not found."
}
```

Validation errors are the same as create (invalid `knowledge_id`, `tool_ids`, `gmail_account_id`, etc.).

### Example

```javascript
async function updateEmailAiAgent(agentId, payload) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/update`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ agent_id: agentId, ...payload }),
  });

  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to update agent");
  }

  return data.agent;
}
```

---

## 4. List Team Agents

```
POST /elysium-agents/email-ai-agents/v1/list-team-agents
```

**Body:**

```json
{
  "team_id": "team_123"
}
```

No JWT required (prototype). Use this to poll `sync_status` / `last_sync_error` / `last_synced_at`.

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Email AI agents fetched successfully.",
  "team_id": "team_123",
  "count": 1,
  "agents": [
    {
      "agent_id": "674c3d4e5f6789012349",
      "name": "Support Agent",
      "gmail_account_id": "674a1b2c3d4e5f6789012345",
      "user_id": "674b2c3d4e5f6789012346",
      "team_id": "team_123",
      "status": "active",
      "activated_at": "2026-06-07T10:00:00+00:00",
      "sync_status": "idle",
      "last_synced_at": "2026-06-07T11:30:00+00:00",
      "last_sync_error": null,
      "inbox_name": "Support Inbox",
      "email_address": "support@gmail.com",
      "system_prompt": "You are a helpful support agent...",
      "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "tool_ids": [
        "674d1a2b3c4e5f6789012345",
        "674d2b3c4d5e6f7890123456"
      ],
      "llm_model": "gpt-4o-mini",
      "reply_action": {
        "mode": "draft",
        "auto_send_min_confidence": 0.8
      },
      "created_at": "2026-06-07T10:00:00+00:00",
      "updated_at": "2026-06-07T11:30:00+00:00"
    }
  ]
}
```

---

## 5. Trigger Inbox Sync

Same endpoint as before. Now syncs **threads** (inbound + outbound).

```
POST /elysium-agents/email-ai-agents/v1/trigger-sync
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "agent_id": "674c3d4e5f6789012349"
}
```

**Success `202`:**

```json
{
  "success": true,
  "message": "Inbox sync started.",
  "agent_id": "674c3d4e5f6789012349",
  "sync_status": "syncing"
}
```

**Sync rules:**

- Max **20 threads** per click
- Each thread fetched with `format=full`
- **`last_synced_at` on the agent is the sync watermark** — only messages **after** this timestamp are stored (except the very first sync, which stores full threads since `activated_at`)
- Gmail `after:` search is day-level only; we apply a precise `internalDate` filter server-side
- Dedup by `gmail_message_id` as a second guard
- Thread summary refreshed only when new messages were inserted

**If you delete thread data in Mongo:** sync will **not** backfill old messages as long as `last_synced_at` is still set. To force a full re-import, set `last_synced_at: null` on the agent document and sync again.

---

## 6. List Team Threads (inbox list — snippet only)

```
POST /elysium-agents/email-ai-agents/v1/list-team-threads
```

**Headers:**

```http
Content-Type: application/json
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "team_id": "team_123",
  "page": 1,
  "limit": 20
}
```

| Field     | Required | Default | Max   | Description                      |
| --------- | -------- | ------- | ----- | -------------------------------- |
| `team_id` | yes      | —       | —     | Team whose inbox threads to list |
| `page`    | no       | `1`     | —     | Page number (1-based)            |
| `limit`   | no       | `20`    | `100` | Threads per page                 |

Sorted by `last_message_at` descending (newest conversations first).

**Thread visibility (enforced server-side):**

| User role | Rule |
| --------- | ---- |
| `admin` | Sees **all** threads for the team (any `department_id` / `assigned_user_id`) |
| `member` | `department_id` empty → **hidden** |
| `member` | `department_id` does not match member's department → **hidden** |
| `member` | `department_id` matches + `assigned_user_id` empty → visible to **all members in that department** |
| `member` | `department_id` matches + `assigned_user_id` set to another user → **hidden** |
| `member` | `department_id` matches + `assigned_user_id` is this member → visible |

`team_id` in the request body must match the JWT `team_id`.

**Success `200`:**

```json
{
  "success": true,
  "message": "Email threads fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "threads": [
    {
      "thread_id": "18f3abc123",
      "agent_id": "674c3d4e5f6789012349",
      "gmail_account_id": "674a1b2c3d4e5f6789012345",
      "team_id": "team_123",
      "subject": "Need help with my order",
      "snippet": "Thanks for your reply...",
      "latest_from": "customer@example.com",
      "participants": ["customer@example.com", "Support <support@gmail.com>"],
      "last_message_at": "2026-06-06T14:30:00Z",
      "message_count": 3,
      "has_unread": true,
      "department_id": "",
      "assigned_user_id": "",
      "action_required": true,
      "ai_action": {
        "status": "draft_ready",
        "type": "draft",
        "flow_run_id": "run_abc123",
        "trigger_message_id": "674d4e5f6789012350",
        "gmail_draft_id": "r-123456789",
        "gmail_draft_message_id": "18f3draft456",
        "confidence": 0.72,
        "subject": "Re: Need help with my order",
        "recipients": {
          "to": ["customer@example.com"],
          "cc": ["shubhojeet.official@gmail.com"],
          "bcc": [],
          "cc_users": [
            { "user_id": "6a23597fc25333c86ca81440", "email": "shubhojeet.official@gmail.com", "name": "Shubh" }
          ],
          "bcc_users": [],
          "matched_recipient_rules": [
            {
              "_id": "6a25892b6548ece0c1cd4904",
              "rule_name": "Sales and Pricing Inquiries",
              "cc": ["shubhojeet.official@gmail.com"],
              "bcc": []
            }
          ]
        },
        "created_at": "2026-06-06T14:30:04Z",
        "resolved_at": null
      },
      "updated_at": "2026-06-06T14:30:05Z"
    }
  ],
  "pagination": {
    "total": 45,
    "page": 1,
    "limit": 20,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

| Pagination field | Meaning                     |
| ---------------- | --------------------------- |
| `total`          | Total threads for this team |
| `page`           | Current page                |
| `limit`          | Items per page              |
| `total_pages`    | `ceil(total / limit)`       |
| `has_next`       | `true` if more pages exist  |
| `has_prev`       | `true` if `page > 1`        |

No `body_text` / `body_html` here — use `get-thread` for full content.

### AI action badges (draft ready)

After a successful flow run with `reply_action.mode: "draft"`, threads with a pending Gmail draft include:

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `action_required` | boolean | `true` when `ai_action.status === "draft_ready"` — show **Review draft** / actionable UI |
| `ai_action` | object \| null | Denormalized draft metadata from `save_gmail_draft` (null when no pending action) |

**Frontend:** filter or badge threads where `action_required === true` — e.g. **“Draft ready — review”**.

Full UI guide (inbox badge, thread draft panel, **Send from app**): **[email-draft-review-ui.md](./email-draft-review-ui.md)**.

---

## 7. Get Thread (full conversation — paginated messages)

```
POST /elysium-agents/email-ai-agents/v1/get-thread
```

**Headers:**

```http
Content-Type: application/json
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "team_id": "team_123",
  "thread_id": "18f3abc123",
  "page": 1,
  "limit": 20
}
```

| Field       | Required | Default | Max   | Description                   |
| ----------- | -------- | ------- | ----- | ----------------------------- |
| `team_id`   | yes      | —       | —     | Team scope                    |
| `thread_id` | yes      | —       | —     | Gmail thread ID from list API |
| `page`      | no       | `1`     | —     | Page of messages (1-based)    |
| `limit`     | no       | `20`    | `100` | Messages per page             |

Messages are sorted **oldest first** (chronological). Page 1 = earliest messages in the thread.

Same thread visibility rules as **List Team Threads** apply here. Returns `403` if the authenticated user cannot access the thread.

**Success `200`:**

```json
{
  "success": true,
  "message": "Email thread fetched successfully.",
  "thread": {
    "thread_id": "18f3abc123",
    "subject": "Need help with my order",
    "snippet": "Thanks for your reply...",
    "message_count": 3,
    "has_unread": true,
    "department_id": "",
    "assigned_user_id": "",
    "action_required": true,
    "ai_action": {
      "status": "draft_ready",
      "type": "draft",
      "flow_run_id": "run_abc123",
      "trigger_message_id": "674d4e5f6789012350",
      "gmail_draft_id": "r-123456789",
      "confidence": 0.72,
      "subject": "Re: Need help with my order",
      "body_text": "Hi John,\n\nThank you for reaching out...",
      "recipients": {
        "to": ["customer@example.com"],
        "cc": ["shubhojeet.official@gmail.com"],
        "bcc": []
      },
      "created_at": "2026-06-06T14:30:04Z",
      "resolved_at": null
    }
  },
  "count": 2,
  "messages": [
    {
      "message_id": "674d4e5f6789012350",
      "gmail_message_id": "18f3abc123",
      "thread_id": "18f3abc123",
      "direction": "inbound",
      "from": "customer@example.com",
      "to": ["support@gmail.com"],
      "cc": [],
      "bcc": [],
      "reply_to": "",
      "subject": "Need help with my order",
      "snippet": "Hi, I need help...",
      "body_text": "Hi, I need help with my order...",
      "body_html": "<div>Hi, I need help...</div>",
      "received_at": "2026-06-06T12:05:00Z",
      "is_unread": false,
      "label_ids": ["INBOX"],
      "processing_status": "completed",
      "flow_run_id": "run_abc123",
      "processed_at": "2026-06-06T14:30:05Z",
      "ai_outcome": {
        "type": "draft_created",
        "flow_run_id": "run_abc123",
        "gmail_draft_id": "r-123456789",
        "confidence": 0.72,
        "recipients": {
          "to": ["customer@example.com"],
          "cc": ["shubhojeet.official@gmail.com"],
          "bcc": []
        }
      },
      "created_at": "2026-06-06T12:06:00Z"
    },
    {
      "message_id": "674d4e5f6789012351",
      "direction": "outbound",
      "from": "Support <support@gmail.com>",
      "to": ["customer@example.com"],
      "body_text": "Thanks for reaching out...",
      "received_at": "2026-06-06T13:00:00Z",
      "ai_reply": {
        "assisted": true,
        "mode": "reviewed",
        "flow_run_id": "run_abc123",
        "agent_id": "674c3d4e5f6789012349",
        "confidence": 0.72,
        "gmail_draft_id": "r-123456789"
      }
    }
  ],
  "pagination": {
    "total": 3,
    "page": 1,
    "limit": 20,
    "total_pages": 1,
    "has_next": false,
    "has_prev": false
  }
}
```

`thread.message_count` = total messages in thread. `pagination.total` matches that count. `count` = messages returned on **this page** only.

### Message AI fields

| Field | When set | Meaning |
| ----- | -------- | ------- |
| `processing_status` | Sync + flow | `pending` → `processing` → `completed` / `failed` / `skipped` |
| `flow_run_id` | Flow Start | Links to `email-flow-runs.run_id` |
| `processed_at` | Flow complete | When processing finished |
| `ai_outcome` | `save_gmail_draft` | On the **trigger inbound** only — `{ type: "draft_created", gmail_draft_id, recipients, ... }` |
| `ai_reply` | `send-thread-draft` | On **outbound** only — AI-assisted send metadata (see below) |

**`ai_reply` (outbound messages only):**

| Field | Value |
| ----- | ----- |
| `assisted` | `true` |
| `mode` | `"reviewed"` — sent via app after AI draft; `"auto"` — future auto-send |
| `flow_run_id` | Source flow run |
| `agent_id` | Agent that generated the draft |
| `confidence` | Model confidence from generation |
| `gmail_draft_id` | Gmail draft that was sent |

**Frontend:** show chip **“AI · reviewed”** on outbound when `message.ai_reply?.assisted && message.ai_reply.mode === "reviewed"`.

Highlight the message where `message_id === thread.ai_action.trigger_message_id` when showing “AI drafted a reply to this email.”

Use `thread.ai_action.body_text` for the draft preview in the thread view (plain text).

---

## 8. Send Thread AI Draft

Send the pending Gmail draft from your app (Gmail `drafts.send`). See **[email-draft-review-ui.md](./email-draft-review-ui.md)** for the full UX flow.

```
POST /elysium-agents/email-ai-agents/v1/send-thread-draft
```

**Headers:** `Authorization: Bearer <jwt>`

**Body:**

```json
{
  "team_id": "team_123",
  "thread_id": "18f3abc123"
}
```

**Success `200`:**

```json
{
  "success": true,
  "message": "AI draft sent successfully.",
  "data": {
    "thread_id": "18f3abc123",
    "gmail_draft_id": "r-123456789",
    "gmail_message_id": "18f3sent789",
    "gmail_thread_id": "18f3abc123",
    "label_ids": ["SENT"],
    "ai_action_status": "resolved",
    "ai_reply": {
      "assisted": true,
      "mode": "reviewed",
      "flow_run_id": "run_abc123",
      "agent_id": "674c3d4e5f6789012349",
      "confidence": 0.72,
      "gmail_draft_id": "r-123456789"
    }
  }
}
```

Sets `thread.ai_action.status` to **`resolved`** and tags the sent outbound row in **`email-thread-messages`** with **`ai_reply`**.

| Status | Meaning |
| ------ | ------- |
| `409` | No pending draft on this thread |
| `403` | User cannot access thread |

After send, optionally **`trigger-sync`** on the agent so the outbound message appears in `get-thread` messages.

---

## MongoDB: `email-ai-agents`

Agent configuration document.

```json
{
  "_id": "674c3d4e5f6789012349",
  "name": "Support Agent",
  "gmail_account_id": "674a1b2c3d4e5f6789012345",
  "system_prompt": "You are a helpful support agent. Answer customer emails professionally using the provided knowledge base.",
  "email_format_template": "Use a professional tone.\n\nGreeting: Hi {customer_name},\n\nBody: 2-3 short paragraphs answering the question.\n\nClosing:\nBest regards,\nSupport Team",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tool_ids": [
    "674d1a2b3c4e5f6789012345",
    "674d2b3c4d5e6f7890123456"
  ],
  "llm_model": "gpt-4o-mini",
  "flow_id": null,
  "reply_action": {
    "mode": "draft",
    "auto_send_min_confidence": 0.8
  },
  "routing_rule_ids": [],
  "recipient_rule_ids": [],
  "user_id": "674b2c3d4e5f6789012346",
  "team_id": "team_123",
  "status": "active",
  "activated_at": "2026-06-07T10:00:00+00:00",
  "sync_status": "idle",
  "last_synced_at": null,
  "last_sync_error": null,
  "created_at": "2026-06-07T10:00:00+00:00",
  "updated_at": "2026-06-07T10:00:00+00:00"
}
```

| Field | Description |
| ----- | ----------- |
| `system_prompt` | LLM instructions for this agent's tone and behaviour |
| `email_format_template` | Optional template for how AI reply emails should be formatted (used by Generate Email node) |
| `knowledge_id` | Links to `email-knowledge` Mongo doc + Qdrant chunks for RAG |
| `tool_ids` | Array of Mongo `_id` strings from `email-tools` tool definitions |
| `llm_model` | Model code for AI replies (e.g. `gpt-4o-mini`) |
| `reply_action` | `{ mode, auto_send_min_confidence }` — draft vs auto-send; selects workflow tail node |
| `routing_rule_ids` | Attached department routing rules (`email-routing-rules`) |
| `recipient_rule_ids` | Attached CC/BCC recipient rules (`email-recipient-rules`) |
| `flow_id` | Linked workflow (`email-flows`); flow edits sync KB/tools/prompt back to this agent |
| `gmail_account_id` | Mongo `_id` of the connected Gmail inbox |
| `activated_at` | First-sync cutoff — threads before this are not imported |
| `sync_status` | `idle`, `syncing`, or `error` |
| `last_synced_at` | Watermark for incremental sync |

Knowledge text lives in **Qdrant** (`email-knowledge` collection), not on this document. Only the `knowledge_id` reference is stored here.

---

## MongoDB: `email-threads`

Thread summary for inbox list.

```json
{
  "thread_id": "gmail_thread_id",
  "team_id": "team_123",
  "agent_id": "...",
  "gmail_account_id": "...",
  "subject": "Need help with my order",
  "snippet": "latest message preview",
  "latest_from": "customer@example.com",
  "participants": ["customer@example.com", "support@gmail.com"],
  "last_message_at": "...",
  "message_count": 3,
  "has_unread": true,
  "department_id": "",
  "assigned_user_id": "",
  "ai_action": {
    "status": "draft_ready",
    "type": "draft",
    "flow_run_id": "...",
    "trigger_message_id": "...",
    "gmail_draft_id": "...",
    "confidence": 0.72,
    "subject": "Re: ...",
    "recipients": { "to": [], "cc": [], "bcc": [] },
    "created_at": "...",
    "resolved_at": null
  },
  "created_at": "...",
  "updated_at": "..."
}
```

| Field | Description |
| ----- | ----------- |
| `department_id` | Department assigned to this thread. Empty until assigned — **members cannot see** unassigned threads. When set, only members in that department can see it (unless `assigned_user_id` restricts further). |
| `assigned_user_id` | Team user assigned to this thread. Empty until assigned. When empty, all members in the thread's department can see it. When set, only that user (plus admins) can see it. |
| `ai_action` | Pending AI work on this thread. `status: "draft_ready"` when a Gmail draft awaits human review. Cleared or superseded when the user sends or a newer inbound is processed (future). |

---

## MongoDB: `email-thread-messages`

One document per email (inbound or outbound).

```json
{
  "gmail_message_id": "unique per inbox",
  "thread_id": "gmail_thread_id",
  "direction": "inbound",
  "from": "customer@example.com",
  "to": ["support@gmail.com"],
  "cc": [],
  "bcc": [],
  "body_text": "...",
  "body_html": "...",
  "snippet": "...",
  "received_at": "...",
  "label_ids": ["UNREAD", "INBOX"],
  "is_unread": true,
  "metadata": { "has_attachments": false },
  "status": "stored",
  "processing_status": "completed",
  "flow_run_id": "...",
  "processed_at": "...",
  "ai_outcome": {
    "type": "draft_created",
    "flow_run_id": "...",
    "gmail_draft_id": "...",
    "confidence": 0.72,
    "recipients": { "to": [], "cc": [], "bcc": [] }
  },
  "ai_reply": {
    "assisted": true,
    "mode": "reviewed",
    "flow_run_id": "...",
    "agent_id": "...",
    "confidence": 0.72,
    "gmail_draft_id": "..."
  }
}
```

`direction: "outbound"` when Gmail `labelIds` contains `SENT`.

| Field | Description |
| ----- | ----------- |
| `processing_status` | Flow lifecycle on inbound messages (`pending` on new sync inserts) |
| `ai_outcome` | Inbound trigger only — draft was created for this customer email |
| `ai_reply` | Outbound only — AI assisted this sent reply (`mode: reviewed` or `auto`) |

**Gmail draft visibility:** drafts are created via Gmail API on the linked inbox account. The user sees them in **Gmail** on that thread (draft reply in the conversation). OAuth must include `gmail.compose` — reconnect the inbox if an existing connection predates this scope.

---

## Frontend guide — pagination

### Pagination shape (both APIs)

Every paginated response includes:

```json
{
  "pagination": {
    "total": 45,
    "page": 1,
    "limit": 20,
    "total_pages": 3,
    "has_next": true,
    "has_prev": false
  }
}
```

### Inbox list — page buttons or infinite scroll

**Option A — page numbers:** increment `page` until `has_next === false`.

**Option B — infinite scroll:** append `threads` when user scrolls; request `page: currentPage + 1` while `has_next`.

```javascript
const BASE = "http://localhost:7000/elysium-agents";
const token = localStorage.getItem("auth_token");
const teamId = JSON.parse(localStorage.getItem("user")).team_id;

async function loadThreadsPage(page = 1, limit = 20) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/list-team-threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ team_id: teamId, page, limit }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);
  return data; // { threads, pagination, count }
}

// Example: load all pages
async function loadAllThreads(limit = 20) {
  let page = 1;
  const all = [];
  while (true) {
    const data = await loadThreadsPage(page, limit);
    all.push(...data.threads);
    if (!data.pagination.has_next) break;
    page += 1;
  }
  return all;
}
```

### Thread detail — load more messages at bottom

Messages are oldest-first. For a long thread, start at `page: 1`, then load `page: 2`, `page: 3`, … and **append** to the message list.

```javascript
async function loadThreadPage(threadId, page = 1, limit = 20) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/get-thread`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ team_id: teamId, thread_id: threadId, page, limit }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);
  return data; // { thread, messages, pagination, count }
}

// Example: open thread + load more on scroll
let threadPage = 1;
let allMessages = [];

async function openThread(threadId) {
  threadPage = 1;
  allMessages = [];
  return appendThreadMessages(threadId);
}

async function appendThreadMessages(threadId, limit = 20) {
  const data = await loadThreadPage(threadId, threadPage, limit);
  allMessages.push(...data.messages);
  threadPage += 1;
  return {
    thread: data.thread,
    messages: allMessages,
    hasMore: data.pagination.has_next,
  };
}

// UI: show "Load older messages" or infinite scroll when hasMore === true
```

### Full setup flow (knowledge → agent → sync)

```javascript
const BASE = "http://localhost:7000/elysium-agents";
const token = localStorage.getItem("auth_token");
const teamId = "team_123";

// 1. Create team knowledge (no JWT)
const knowledgeRes = await fetch(`${BASE}/email-knowledge/v1/create`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    team_id: teamId,
    title: "Return Policy",
    knowledge_text: "Our return policy allows customers to return products within 30 days...",
  }),
});
const { knowledge } = await knowledgeRes.json();

// 2. Register tools (no JWT) — see email-tool-definitions-api.md
// ... create get_ticket_status + create_ticket, save tool_ids

// 3. Create agent (JWT required) — draft mode (default)
const agent = await createEmailAiAgent(
  "Support Agent",
  "674a1b2c3d4e5f6789012345", // gmail_account_id
  "You are a helpful support agent. Use the knowledge base to answer accurately.",
  knowledge.knowledge_id,
  ["674d1a2b3c4e5f6789012345", "674d2b3c4d5e6f7890123456"], // tool_ids
  "gpt-4o-mini", // llm_model
  { mode: "draft", auto_send_min_confidence: 0.8 },
);

// Or auto-send when confidence >= 0.8:
// { mode: "auto_send", auto_send_min_confidence: 0.8 }

// 4. Sync inbox
await syncInbox(agent.agent_id);

// 5. Load threads
const inbox = await loadThreadsPage(1, 20);
console.log(inbox.threads);
```

### Full sync + inbox flow

```javascript
const token = localStorage.getItem("auth_token");

async function syncInbox(agentId) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/trigger-sync`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ agent_id: agentId }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);

  while (true) {
    await new Promise((r) => setTimeout(r, 2500));
    const agentsRes = await fetch(
      `${BASE}/email-ai-agents/v1/list-team-agents`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ team_id: teamId }),
      },
    );
    const agentsData = await agentsRes.json();
    const agent = agentsData.agents.find((a) => a.agent_id === agentId);
    if (agent.sync_status === "idle") break;
    if (agent.sync_status === "error") throw new Error(agent.last_sync_error);
  }

  return loadThreadsPage(1, 20);
}
```

---

## Quick reference

### Email AI agent APIs

| API               | Method | Path                                    | Auth | Body |
| ----------------- | ------ | --------------------------------------- | ---- | ---- |
| Create agent      | `POST` | `/email-ai-agents/v1/create`            | JWT  | `{ name, gmail_account_id, system_prompt, knowledge_id, tool_ids, llm_model, email_format_template?, reply_action?, routing_rule_ids?, recipient_rule_ids? }` |
| Get agent         | `POST` | `/email-ai-agents/v1/get-agent`         | No   | `{ agent_id }` |
| Update agent      | `POST` | `/email-ai-agents/v1/update`            | JWT  | `{ agent_id, name, …, email_format_template?, reply_action?, routing_rule_ids?, recipient_rule_ids? }` — agent ↔ flow sync when `flow_id` set (planned) |
| List team agents  | `POST` | `/email-ai-agents/v1/list-team-agents`  | No   | `{ team_id }` |
| Trigger sync      | `POST` | `/email-ai-agents/v1/trigger-sync`      | JWT  | `{ agent_id }` |
| List team threads | `POST` | `/email-ai-agents/v1/list-team-threads` | JWT  | `{ team_id, page?, limit? }` |
| Get thread        | `POST` | `/email-ai-agents/v1/get-thread`        | JWT  | `{ team_id, thread_id, page?, limit? }` |
| Send AI draft     | `POST` | `/email-ai-agents/v1/send-thread-draft` | JWT  | `{ team_id, thread_id }` |

### Related APIs (knowledge & tools)

| API               | Method | Path                                    | Auth | Docs |
| ----------------- | ------ | --------------------------------------- | ---- | ---- |
| Create knowledge  | `POST` | `/email-knowledge/v1/create`            | No   | [email-knowledge-api.md](./email-knowledge-api.md) |
| Query knowledge   | `POST` | `/email-knowledge/v1/query`             | No   | [email-knowledge-api.md](./email-knowledge-api.md) |
| Register tool     | `POST` | `/email-tool-definitions/v1/create`     | No   | [email-tool-definitions-api.md](./email-tool-definitions-api.md) |
| Get ticket status | `POST` | `/email-tools/v1/get-ticket-status`     | No   | [email-tools-api.md](./email-tools-api.md) |
| Create ticket     | `GET`  | `/email-tools/v1/create-ticket`         | No   | [email-tools-api.md](./email-tools-api.md) |

| Collection | Purpose |
| ---------- | ------- |
| `email-ai-agents` | Agent config: inbox, system_prompt, email_format_template, knowledge_id, tool_ids, llm_model, reply_action, routing_rule_ids, recipient_rule_ids, flow_id, sync state |
| `email-knowledge` | Knowledge metadata (text + vectors in Qdrant) |
| `email-tools` | Registered external tool definitions for LLM |
| `email-threads` | Thread summaries for inbox list |
| `email-thread-messages` | Full message bodies per thread |

---

## Migration note

The old `email-inbound-messages` collection and `list-agent-messages` API are replaced by thread-based storage. Delete old test data and re-sync to populate `email-threads` and `email-thread-messages`.

---

## What's next

- Email flow engine — node pipeline per [email-flow-plan.md](./email-flow-plan.md) (agent config hydrated into workflow nodes)
- AI processing of thread messages (uses same agent fields as workflow bindings)
- Agent tools at runtime (ticket status, create ticket — see [email-tools-api.md](./email-tools-api.md))
- Auto-sync (cron) or Gmail push via `historyId`
- Attachment download API

---

## Related docs

- [email-flow-plan.md](./email-flow-plan.md) — workflow nodes, draft/send tail, agent ↔ flow sync
- [email-routing-rules-api.md](./email-routing-rules-api.md) — department routing rules (LLM conditions per team)
- [email-knowledge-api.md](./email-knowledge-api.md) — create/list/delete team knowledge
- [email-tool-definitions-api.md](./email-tool-definitions-api.md) — register external tools for LLM
- [email-tools-api.md](./email-tools-api.md) — built-in tool execution APIs
- [gmail-oauth-setup.md](./gmail-oauth-setup.md)
- [email-auth-login-api.md](./email-auth-login-api.md)
- [departments-api.md](./departments-api.md)
