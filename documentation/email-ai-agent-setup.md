# Email AI Agent ? Configuration & Sync Guide

Configure an email AI agent: **system prompt**, **knowledge base**, **tools**, **reply_action**, and **Gmail sync**.

**Collections (this doc):** `email-ai-agents`, `email-knowledge`

**Inbox / threads:** [email-threads-api.md](./email-threads-api.md) (`email-threads`, `email-thread-messages`)

---

## What is an email AI agent?

An agent links:

- A **name** and **Gmail inbox** ? for sending/receiving email
- A **system prompt** ? instructions for how the AI should behave
- A **knowledge_id** ? team knowledge indexed in Qdrant (see [email-knowledge-api.md](./email-knowledge-api.md))
- An **llm_model** ? model code used when the agent generates replies
- A **reply_action** ? how replies are delivered: Gmail draft only, or auto-send when confidence is high enough (see [Reply action](#reply-action-draft-vs-auto-send)); controls which **tail node** appears on the agent?s workflow ([Agent ? workflow sync](#agent--workflow-sync))
- A **flow_id** (when attached) ? links a workflow graph; KB/tools/prompt on that flow **sync back** to the agent when the workflow is saved or attached

When active, sync pulls **complete email threads** into Mongo ? both emails you receive and replies you send from Gmail. AI reply generation (coming next) runs the agent?s **workflow** ([email-flow-plan.md](./email-flow-plan.md)) using the same fields configured here ? kept in sync with the workflow bidirectionally.

---

## Prerequisites

```
1. Login            ?  JWT (user_id + team_id)
2. Connect Gmail    ?  email-gmail_accounts (gmail_account_id)
3. Create knowledge ?  POST /email-knowledge/v1/create  ?  knowledge_id
4. Register tools   ?  POST /email-tool-definitions/v1/create  ?  tool_id(s)
5. Create agent     ?  name + gmail_account_id + system_prompt + knowledge_id + tool_ids + llm_model + reply_action (+ optional email_format_template)
6. Trigger sync     ?  fetch up to 20 threads with recent activity
7. List threads     ?  inbox list (snippet only)
8. Get thread       ?  full conversation with bodies
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
| **Create Knowledge**| `POST /email-knowledge/v1/create`            | Before agent setup ? user provides policy/FAQ text        |
| **Create Agent**    | `POST /email-ai-agents/v1/create`            | User picked inbox, prompt, and knowledge                  |
| **View Agent**      | `POST /email-ai-agents/v1/get-agent`         | Agent settings / detail page                              |
| **Update Agent**    | `POST /email-ai-agents/v1/update`            | User edits agent configuration                            |
| **Sync Inbox**      | `POST /email-ai-agents/v1/trigger-sync`      | Agent exists and `sync_status !== "syncing"`              |
| **Refresh Threads** | `POST /email-ai-agents/v1/list-team-threads` | Inbox list ? see [email-threads-api.md](./email-threads-api.md) |
| **Open Thread**     | `POST /email-ai-agents/v1/get-thread`        | Thread detail ? see [email-threads-api.md](./email-threads-api.md) |
| **Send AI Draft**   | `POST /email-ai-agents/v1/send-thread-draft` | See [email-threads-api.md](./email-threads-api.md) |
| **Refresh Agents**  | `POST /email-ai-agents/v1/list-team-agents`  | Agent list page                                           |

---

## Sync UX flow

```
User clicks "Sync Inbox"
        ?
POST /trigger-sync  ?  instant response { sync_status: "syncing" }
        ?
Poll POST /list-team-agents every 2?3s
        ?
When sync_status === "idle"  ?  POST /list-team-threads
When sync_status === "error" ?  show agent.last_sync_error
        ?
(New inbound during sync may have triggered the AI flow automatically ?
 threads may show ai_action without manual reprocess)
        ?
User clicks a thread  ?  POST /get-thread
```

While `sync_status === "syncing"`, the backend may still be running AI flows for threads with new inbound mail. Keep polling until `"idle"` before assuming inbox badges are final.

---

## How thread sync works (production approach)

1. **Discover threads** ? `threads.list?q=after:{cutoff} category:primary` (up to 20 per sync)
   - First sync cutoff: `activated_at` (`last_synced_at` is null)
   - Later syncs: `last_synced_at` on `email-ai-agents`
   - **Primary inbox only** ? Promotions, Social, Updates, and Forums are excluded
   - Includes **inbound and outbound** activity within those Primary threads (not `is:unread` only)

2. **Fetch full thread** ? `threads.get?format=full` for each thread
   - Returns every message in the conversation with full MIME bodies

3. **Store only new messages** ? watermark filter + dedup
   - **First sync:** store all messages in discovered threads (full conversation)
   - **Later syncs:** only messages with `received_at > last_synced_at`
   - Dedup: unique `(gmail_account_id, gmail_message_id)`
   - `direction`: `inbound` or `outbound` (outbound = Gmail `SENT` label)

4. **Advance watermark** ? set `last_synced_at` to the newest stored message time (or `now` if nothing new)

5. **Update thread summary** ? upsert into `email-threads` only when new messages were inserted

6. **Run AI flow (automatic)** ? for each thread that received a **new inbound** message this sync, run the full email flow sequentially (`force_reprocess: false`, same pipeline as reprocess-thread). Agent stays `sync_status: "syncing"` until sync + all flows finish.

**Example back-and-forth:**

- Customer emails you ? sync ? inbound message stored
- You reply in Gmail ? sync ? outbound reply stored in same `thread_id`
- Customer replies again ? sync ? only the new inbound message is inserted; full thread available via `get-thread`

---

## Reply action (draft vs auto-send)

After the flow generates a reply, **`reply_action`** controls what happens next.

| `reply_action.mode` | Behaviour |
| ------------------- | --------- |
| **`draft`** (default) | Save the AI reply as a **Gmail draft** on that thread in the user's inbox. User reviews and sends manually. | Workflow tail node: **Save Gmail Draft** |
| **`auto_send`** | If the flow's **confidence score ? `auto_send_min_confidence`**, send the reply automatically via Gmail. If confidence is below the threshold, **fall back to draft** (same as `draft` mode). | Workflow tail node: **Send Email** (draft fallback at runtime) |

**Confidence** is a number from **0.0 to 1.0** produced when the AI evaluates how well it can answer the email (using thread context, KB, and tool results). It is computed at flow runtime ? not passed by the frontend on each email.

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
| `auto_send_min_confidence` | number | `0.8` | Min confidence to auto-send (0?1). Used only when `mode` is `"auto_send"`. |

### Frontend UX

| Control | Maps to |
| ------- | ------- |
| **?Save as draft?** radio (recommended default) | `{ "mode": "draft", "auto_send_min_confidence": 0.8 }` |
| **?Auto-send when confident?** radio | `{ "mode": "auto_send", "auto_send_min_confidence": <slider> }` |
| Confidence slider (show when auto-send selected) | `auto_send_min_confidence` ? e.g. 0.7, 0.8, 0.9 |

Send `reply_action` on **create** and **update**. Omit on create ? defaults to draft + `0.8`.

**Example ? draft only:**

```json
"reply_action": { "mode": "draft", "auto_send_min_confidence": 0.8 }
```

**Example ? auto-send when confidence ? 80%:**

```json
"reply_action": { "mode": "auto_send", "auto_send_min_confidence": 0.8 }
```

> **Note:** Auto-send is applied by the flow **Send Email** node when the engine ships ([email-flow-plan.md](./email-flow-plan.md)). Until then, `reply_action` is stored on the agent and returned by the API; the workflow UI should still show the correct tail node from this config.

---

## Agent ? workflow sync

The agent document and the **workflow canvas** must always show the **same** KB, tools, prompt, model, and reply policy. Sync is **bidirectional** ? editing either side updates the other.

Full workflow design: [email-flow-plan.md](./email-flow-plan.md) ?5.2.

### How it works

| You edit? | API | Backend sync | Other side updates |
| --------- | --- | -------------- | ------------------- |
| Agent settings | `POST /email-ai-agents/v1/update` | `push_agent_to_flow` | Flow node `config` (e.g. Read KB gets new `knowledge_id`) |
| Workflow (KB, tools, ?) | `POST /email-flows/v1/update` | `push_flow_to_agent` | Agent doc fields (`knowledge_id`, `tool_ids`, ?) |
| Attach workflow to agent | `POST /email-ai-agents/v1/update` with `flow_id` | `push_flow_to_agent` (once) | Agent doc filled from flow node selections |

**Runtime:** The flow engine reads the **agent document** when processing email. Flow ? agent sync keeps that document current after workflow edits.

### Syncable fields

| Field | Agent (`email-ai-agents`) | Workflow node |
| ----- | ------------------------- | ------------- |
| `knowledge_id` | ? | **Read KB** ? `config.knowledge_id` |
| `tool_ids` | ? | **Read Tools** ? `config.tool_ids` |
| `system_prompt` | ? | **System Prompt** ? `config.system_prompt` |
| `llm_model` | ? | **Generate Email** ? `config.llm_model` |
| `reply_action` | ? | **Save Gmail Draft** / **Send Email** ? `config.reply_action` |
| `flow_id` | ? | Which workflow graph is linked |

**Agent-only (not from flow):** `name`, `gmail_account_id`, sync state.

**Flow-only (not copied to agent):** `generate_email.format_prompt`, `read_kb.limit`, `call_external_tool` post-draft tool list, node layout.

### Examples

**Workflow ? agent:** You pick **Return Policy v2** on the **Read KB** node and save the flow. Agent settings immediately show `knowledge_id` for v2 ? no separate agent form save required (backend `push_flow_to_agent`).

**Agent ? workflow:** You change `tool_ids` on the agent settings page. The linked flow?s **Read Tools** node updates; reopening the canvas shows the new tools.

**Attach flow:** You create a custom flow with KB `kb_1` and two tools, then set `"flow_id": "..."` on the agent. Attach runs **flow ? agent** sync ? agent doc gets `kb_1` and those tool ids even if the agent form had different values before.

### Tail node (draft vs send)

`reply_action` syncs like other fields ? tail node type on canvas follows `reply_action.mode`:

```
... ? Generate Email ? Call External Tool ? [tail] ? Stop

reply_action.mode = draft      ?  Save Gmail Draft
reply_action.mode = auto_send  ?  Send Email  (draft fallback if confidence low)
```

Changing tail mode on **either** agent settings **or** the tail node config syncs to the other side.

### Frontend behaviour

1. **Agent settings** ? edit fields ? save agent ? refresh workflow view (`push_agent_to_flow` on server).
2. **Workflow builder (power users)** ? edit KB/tools on node panel ? save flow ? **refresh agent settings** (`push_flow_to_agent` on server).
3. **Attach workflow** ? user picks flow on agent ? save ? agent form reflects flow selections.
4. Render nodes with **`binding`** chips; values must match agent API after every save.

**Shared flows:** If multiple agents use the same `flow_id`, saving the flow updates **all** attached agents (team template pattern).

### Flow-only settings (power users)

These stay on the flow JSON only ? they do **not** sync to the agent doc:

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
| `email_format_template` | No | Optional string describing how generated reply emails should be structured (sections, tone, sign-off). Passed to the **Generate Email** flow node at reply time. Omit or `""` ? no extra format constraint beyond `system_prompt`. Max 10,000 chars. |
| `knowledge_id` | Yes | UUID from `POST /email-knowledge/v1/create` (must belong to same team) |
| `tool_ids` | Yes | Array of Mongo `_id` strings from `email-tools` (1?20 tools, same team) |
| `llm_model` | Yes | LLM model code (e.g. `gpt-4o-mini`, `claude-sonnet-4-5`) ? stored on agent, used at reply time |
| `reply_action` | No | Reply delivery policy ? see [Reply action](#reply-action-draft-vs-auto-send). Defaults to `{ "mode": "draft", "auto_send_min_confidence": 0.8 }` |
| `routing_rule_ids` | No | Mongo `_id`s from `email-routing-rules` (0?50, same team). Which department routing rules this agent uses ? see [email-routing-rules-api.md](./email-routing-rules-api.md) |
| `recipient_rule_ids` | No | Mongo `_id`s from `email-recipient-rules` (0?50, same team). Which CC/BCC rules this agent uses ? see [email-recipient-rules-api.md](./email-recipient-rules-api.md) |
| `flow_id` | Response only | Set automatically on create ? Mongo `_id` of the default workflow in `email-flows`. See [email-flows-ui.md](./email-flows-ui.md) |

`user_id` and `team_id` come from the JWT ? do **not** pass them in the body.

On create: `status=active`, `activated_at=now` ? only thread activity **after** this time is discovered on first sync. A **non-deletable default workflow** is created in `email-flows` and linked via `flow_id`.

### Success ? `201 Created`

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
    "flow_id": "674f2b3c4d5e6f7890123456",
    "created_at": "2026-06-07T10:00:00+00:00",
    "updated_at": "2026-06-07T10:00:00+00:00"
  }
}
```

**Frontend:** store `agent.agent_id` for sync and thread APIs.

### Error ? `400`

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

### Error ? `401`

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

### Success ? `200 OK`

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

### Error ? `404`

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
| `email_format_template` | No | Optional reply layout/format template ? same as create |
| `knowledge_id` | Yes | Team knowledge UUID |
| `tool_ids` | Yes | Tool definition ids from `email-tools` |
| `llm_model` | Yes | Model code |
| `reply_action` | No | Reply delivery policy ? same shape as create |
| `routing_rule_ids` | No | Attached routing rule ids (same team) |
| `recipient_rule_ids` | No | Attached recipient rule ids (same team) |
| `flow_id` | No | Attach or change workflow; triggers **flow ? agent** sync on save (planned) |

`team_id` comes from JWT ? agent must belong to that team. Successful update also runs **agent ? flow** sync when `flow_id` is set (planned).

### Success ? `200 OK`

```json
{
  "success": true,
  "message": "Email AI agent updated successfully.",
  "agent": { "...full agent object..." }
}
```

### Error ? `403`

```json
{
  "success": false,
  "message": "Email AI agent does not belong to your team."
}
```

### Error ? `404`

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

### Success ? `200 OK`

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
- **`last_synced_at` on the agent is the sync watermark** ? only messages **after** this timestamp are stored (except the very first sync, which stores full threads since `activated_at`)
- Gmail `after:` search is day-level only; we apply a precise `internalDate` filter server-side
- Dedup by `gmail_message_id` as a second guard
- Thread summary refreshed only when new messages were inserted

**If you delete thread data in Mongo:** sync will **not** backfill old messages as long as `last_synced_at` is still set. To force a full re-import, set `last_synced_at: null` on the agent document and sync again.

---

## Threads & messages (inbox API)

After sync, use the dedicated threads doc for the inbox list, conversation view, send draft, Mongo shapes, and pagination examples:

**? [email-threads-api.md](./email-threads-api.md)**

| API | When |
| --- | ---- |
| `POST /email-ai-agents/v1/list-team-threads` | Main inbox page ? snippet rows, `ai_status`, `ai_action` |
| `POST /email-ai-agents/v1/get-thread` | Thread detail ? full messages + bodies |
| `POST /email-ai-agents/v1/send-thread-draft` | User sends pending AI draft from your app |

Frontend UX (badges, draft panel, auto-send): **[email-draft-review-ui.md](./email-draft-review-ui.md)**.

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
  "flow_id": "674f2b3c4d5e6f7890123456",
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
| `reply_action` | `{ mode, auto_send_min_confidence }` ? draft vs auto-send; selects workflow tail node |
| `routing_rule_ids` | Attached department routing rules (`email-routing-rules`) |
| `recipient_rule_ids` | Attached CC/BCC recipient rules (`email-recipient-rules`) |
| `flow_id` | Linked workflow (`email-flows`); flow edits sync KB/tools/prompt back to this agent |
| `gmail_account_id` | Mongo `_id` of the connected Gmail inbox |
| `activated_at` | First-sync cutoff ? threads before this are not imported |
| `sync_status` | `idle`, `syncing`, or `error` |
| `last_synced_at` | Watermark for incremental sync |

Knowledge text lives in **Qdrant** (`email-knowledge` collection), not on this document. Only the `knowledge_id` reference is stored here.

---

## Quick reference

### Email AI agent APIs

| API               | Method | Path                                    | Auth | Body |
| ----------------- | ------ | --------------------------------------- | ---- | ---- |
| Create agent      | `POST` | `/email-ai-agents/v1/create`            | JWT  | `{ name, gmail_account_id, system_prompt, knowledge_id, tool_ids, llm_model, email_format_template?, reply_action?, routing_rule_ids?, recipient_rule_ids? }` |
| Get agent         | `POST` | `/email-ai-agents/v1/get-agent`         | No   | `{ agent_id }` |
| Update agent      | `POST` | `/email-ai-agents/v1/update`            | JWT  | `{ agent_id, name, ?, email_format_template?, reply_action?, routing_rule_ids?, recipient_rule_ids? }` ? agent ? flow sync when `flow_id` set (planned) |
| List team agents  | `POST` | `/email-ai-agents/v1/list-team-agents`  | No   | `{ team_id }` |
| Trigger sync      | `POST` | `/email-ai-agents/v1/trigger-sync`      | JWT  | `{ agent_id }` |
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
---

## Migration note

The old `email-inbound-messages` collection and `list-agent-messages` API are replaced by thread-based storage. See [email-threads-api.md](./email-threads-api.md). Delete old test data and re-sync.

---

## What's next

- Email flow engine ? node pipeline per [email-flow-plan.md](./email-flow-plan.md) (agent config hydrated into workflow nodes)
- AI processing of thread messages (uses same agent fields as workflow bindings)
- Agent tools at runtime (ticket status, create ticket ? see [email-tools-api.md](./email-tools-api.md))
- Auto-sync (cron) or Gmail push via `historyId`
- Attachment download API

---

## Related docs

- [email-flow-plan.md](./email-flow-plan.md) ? workflow nodes, draft/send tail, agent ? flow sync
- [email-threads-api.md](./email-threads-api.md) ? inbox list, get-thread, send draft
- [email-routing-rules-api.md](./email-routing-rules-api.md) ? department routing rules (LLM conditions per team)
- [email-knowledge-api.md](./email-knowledge-api.md) ? create/list/delete team knowledge
- [email-tool-definitions-api.md](./email-tool-definitions-api.md) ? register external tools for LLM
- [email-tools-api.md](./email-tools-api.md) ? built-in tool execution APIs
- [gmail-oauth-setup.md](./gmail-oauth-setup.md)
- [email-auth-login-api.md](./email-auth-login-api.md)
- [departments-api.md](./departments-api.md)
