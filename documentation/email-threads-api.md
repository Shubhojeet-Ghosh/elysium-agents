# Email Threads & Messages API

Inbox list, thread detail (messages), send AI draft, Mongo collections, pagination, and JavaScript examples.

**Prerequisites:** Agent created and synced ? see [email-ai-agent-setup.md](./email-ai-agent-setup.md).

**Related:**
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) ? create agent, trigger sync, reply_action
- [email-draft-review-ui.md](./email-draft-review-ui.md) ? inbox badges, draft panel UX
- [email-routing-rules-api.md](./email-routing-rules-api.md) ? thread `department_id` visibility

**Collections:** `email-threads`, `email-thread-messages`

---

## Base URL

```
http://localhost:7000/elysium-agents
```

---

## 1. List Team Threads (inbox list ? snippet only)

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
| `team_id` | yes      | ?       | ?     | Team whose inbox threads to list |
| `page`    | no       | `1`     | ?     | Page number (1-based)            |
| `limit`   | no       | `20`    | `100` | Threads per page                 |

Sorted by `last_message_at` descending (newest conversations first).

**Thread visibility (enforced server-side):**

| User role | Rule |
| --------- | ---- |
| `admin` | Sees **all** threads for the team (any `department_id` / `assigned_user_id`) |
| `member` | `assigned_user_id` is this member ? **visible** (even if thread `department_id` differs from member's department) |
| `member` | `department_id` empty ? **hidden** (unless assigned above) |
| `member` | `department_id` does not match member's department ? **hidden** (unless assigned above) |
| `member` | `department_id` matches + `assigned_user_id` empty ? visible to **all members in that department** |
| `member` | `department_id` matches + `assigned_user_id` set to another user ? **hidden** |

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
      "department_id": "674a1b2c3d4e5f6789012345",
      "department_name": "Sales",
      "assigned_user_id": "674b2c3d4e5f6789012346",
      "assigned_user": {
        "user_id": "674b2c3d4e5f6789012346",
        "name": "Jane Doe",
        "email": "jane@example.com"
      },
      "is_ai_processing": false,
      "action_required": true,
      "ai_status": {
        "current_status": "idle",
        "flow_run_id": "run_abc123",
        "trigger_message_id": "674d4e5f6789012350",
        "started_at": "2026-06-06T14:30:00Z",
        "updated_at": "2026-06-06T14:30:05Z",
        "last_error": null
      },
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

No `body_text` / `body_html` here ? use `get-thread` for full content.

### AI action badges (inbox list)

After a flow run, threads include denormalized **`ai_action`**. Use **`action_required`** for actionable UI (`draft_ready` only). Covers draft mode, auto-send (`sent`), and draft fallback (`draft_fallback`).

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `action_required` | boolean | `true` when `ai_action.status === "draft_ready"` ? show **Review draft** / actionable UI |
| `ai_action` | object \| null | Denormalized draft metadata from `save_gmail_draft` (null when no pending action) |

**Frontend:** filter or badge threads where `action_required === true` ? e.g. **?Draft ready ? review?**.

Full UI guide (inbox badge, thread draft panel, **Send from app**): **[email-draft-review-ui.md](./email-draft-review-ui.md)**.

### AI processing indicator

While a flow run is active, poll **`list-team-threads`** or **`get-thread`** for thread-level progress (use **`is_ai_processing`** on inbox rows).

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `is_ai_processing` | boolean | `true` when `ai_status.current_status === "processing"` |
| `ai_status` | object \| null | In-flight or last-known AI run state |

**`ai_status.current_status`:** `processing` (Start node) ? `idle` (success) or `failed` (see `last_error`).

When a new run starts while `draft_ready` `ai_action` exists, the prior action is marked **`superseded`**.

Full badge copy and filters: **[email-draft-review-ui.md](./email-draft-review-ui.md)** �1.


---

## 2. Get Thread (full conversation ? paginated messages)

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
| `team_id`   | yes      | ?       | ?     | Team scope                    |
| `thread_id` | yes      | ?       | ?     | Gmail thread ID from list API |
| `page`      | no       | `1`     | ?     | Page of messages (1-based)    |
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
    "department_id": "674a1b2c3d4e5f6789012345",
    "department_name": "Sales",
    "assigned_user_id": "674b2c3d4e5f6789012346",
    "assigned_user": {
      "user_id": "674b2c3d4e5f6789012346",
      "name": "Jane Doe",
      "email": "jane@example.com"
    },
    "is_ai_processing": false,
    "action_required": true,
    "ai_status": {
      "current_status": "idle",
      "flow_run_id": "run_abc123",
      "trigger_message_id": "674d4e5f6789012350",
      "started_at": "2026-06-06T14:30:00Z",
      "updated_at": "2026-06-06T14:30:05Z",
      "last_error": null
    },
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
| `processing_status` | Sync + flow | `pending` ? `processing` ? `completed` / `failed` / `skipped` |
| `flow_run_id` | Flow Start | Links to `email-flow-runs.run_id` |
| `processed_at` | Flow complete | When processing finished |
| `ai_outcome` | `save_gmail_draft` | On the **trigger inbound** only ? `{ type: "draft_created", gmail_draft_id, recipients, ... }` |
| `ai_reply` | `send-thread-draft` | On **outbound** only ? AI-assisted send metadata (see below) |

**`ai_reply` (outbound messages only):**

| Field | Value |
| ----- | ----- |
| `assisted` | `true` |
| `mode` | `"reviewed"` ? sent via app after AI draft; `"auto"` ? future auto-send |
| `flow_run_id` | Source flow run |
| `agent_id` | Agent that generated the draft |
| `confidence` | Model confidence from generation |
| `gmail_draft_id` | Gmail draft that was sent |

**Frontend:** show chip **?AI ? reviewed?** on outbound when `message.ai_reply?.assisted && message.ai_reply.mode === "reviewed"`.

Highlight the message where `message_id === thread.ai_action.trigger_message_id` when showing ?AI drafted a reply to this email.?

Use `thread.ai_action.body_text` for the draft preview in the thread view (plain text).

---

## 3. Assign Thread

Assign a thread to a team user by updating `email-threads.assigned_user_id`.

```
POST /elysium-agents/email-ai-agents/v1/assign-thread
```

**Headers:** `Authorization: Bearer <jwt>`

**Body:**

```json
{
  "team_id": "team_123",
  "thread_id": "18f3abc123",
  "user_id": "674b2c3d4e5f6789012346"
}
```

| Field | Required | Description |
| ----- | -------- | ----------- |
| `team_id` | Yes | Must match JWT `team_id` |
| `thread_id` | Yes | Gmail thread id |
| `user_id` | Yes | Team user to assign (`email-users._id`) |

**Role rules:**

| Role | Can assign to |
| ---- | ------------- |
| `admin` | Any user in the team (any department) |
| `member` | **Only their own** `user_id` (assign to self) |

Caller must already be able to access the thread (same rules as `get-thread`).

**Success `200`:**

```json
{
  "success": true,
  "message": "Email thread assigned successfully.",
  "data": {
    "thread_id": "18f3abc123",
    "assigned_user_id": "674b2c3d4e5f6789012346",
    "assigned_user": {
      "user_id": "674b2c3d4e5f6789012346",
      "name": "Jane Doe",
      "email": "jane@example.com"
    },
    "thread": {
      "thread_id": "18f3abc123",
      "department_id": "674a1b2c3d4e5f6789012345",
      "department_name": "Sales",
      "assigned_user_id": "674b2c3d4e5f6789012346",
      "assigned_user": {
        "user_id": "674b2c3d4e5f6789012346",
        "name": "Jane Doe",
        "email": "jane@example.com"
      }
    }
  }
}
```

| Status | Meaning |
| ------ | ------- |
| `403` | Member tried to assign someone else, or caller cannot access thread |
| `404` | Thread or assignee user not found |
| `400` | Assignee not in team |

After assign, re-fetch `list-team-threads` or `get-thread` — both include `assigned_user_id` and hydrated `assigned_user` (plus `department_name` when `department_id` is set).

---

## 4. Send Thread AI Draft

Send the pending Gmail draft from your app. See **[email-draft-review-ui.md](./email-draft-review-ui.md)** for the full UX flow.

| `is_edited` | Behaviour |
| ----------- | --------- |
| `false` (default) | Gmail `drafts.send` on the existing AI draft |
| `true` | Gmail `drafts.update` with `body_text` (+ optional `cc` / `bcc`), then `drafts.send` |

```
POST /elysium-agents/email-ai-agents/v1/send-thread-draft
```

**Headers:** `Authorization: Bearer <jwt>`

**Body � unchanged draft:**

```json
{
  "team_id": "team_123",
  "thread_id": "18f3abc123"
}
```

**Body � user edited draft in app:**

```json
{
  "team_id": "team_123",
  "thread_id": "18f3abc123",
  "is_edited": true,
  "body_text": "Hi � updated reply body.\n\nThanks,\nSupport",
  "cc": ["manager@example.com"],
  "bcc": []
}
```

| Field | Required | Notes |
| ----- | -------- | ----- |
| `team_id` | Yes | Must match JWT |
| `thread_id` | Yes | Gmail thread id |
| `is_edited` | No | Default `false` |
| `body_text` | When `is_edited: true` | Full plain-text body from review UI |
| `cc` | No | Full Cc list when edited; omit to keep `ai_action.recipients.cc` |
| `bcc` | No | Full Bcc list when edited; omit to keep `ai_action.recipients.bcc` |

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
    "is_edited": true,
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

Sets `thread.ai_action.status` to **`resolved`** and tags the sent outbound row in **`email-thread-messages`** with **`ai_reply`** (using edited body/recipients when `is_edited: true`).

| Status | Meaning |
| ------ | ------- |
| `409` | No pending draft on this thread |
| `403` | User cannot access thread |
| `422` | `is_edited: true` without `body_text` |

After send, optionally **`trigger-sync`** on the agent so the outbound message appears in `get-thread` messages.

---

## 5. MongoDB: `email-threads`

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
  "ai_status": {
    "current_status": "processing",
    "flow_run_id": "...",
    "trigger_message_id": "...",
    "started_at": "...",
    "updated_at": "...",
    "last_error": null
  },
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
| `department_id` | Department assigned to this thread. Empty until assigned ? **members cannot see** unassigned threads. When set, only members in that department can see it (unless `assigned_user_id` restricts further). |
| `department_name` | Hydrated on list/get APIs when `department_id` is set |
| `assigned_user_id` | Team user assigned to this thread. Empty until assigned. When empty, all members in the thread's department can see it. When set, only that user (plus admins) can see it. |
| `assigned_user` | Hydrated on list/get APIs when `assigned_user_id` is set: `{ user_id, name, email }`; `null` when unassigned |
| `ai_status` | Thread-level flow progress (`processing` / `idle` / `failed`). Exposed as `is_ai_processing` on API responses. |
| `ai_action` | Latest AI outcome on this thread. See [email-draft-review-ui.md](./email-draft-review-ui.md) for `status` / `type` combinations. |

---

## 6. MongoDB: `email-thread-messages`

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
| `ai_outcome` | Inbound trigger only ? draft was created for this customer email |
| `ai_reply` | Outbound only ? AI assisted this sent reply (`mode: reviewed` or `auto`) |

**Gmail draft visibility:** drafts are created via Gmail API on the linked inbox account. The user sees them in **Gmail** on that thread (draft reply in the conversation). OAuth must include `gmail.compose` ? reconnect the inbox if an existing connection predates this scope.

---

## 7. Frontend guide ? pagination

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

### Inbox list ? page buttons or infinite scroll

**Option A ? page numbers:** increment `page` until `has_next === false`.

**Option B ? infinite scroll:** append `threads` when user scrolls; request `page: currentPage + 1` while `has_next`.

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

### Thread detail ? load more messages at bottom

Messages are oldest-first. For a long thread, start at `page: 1`, then load `page: 2`, `page: 3`, ? and **append** to the message list.

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

### Full setup flow (knowledge ? agent ? sync)

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

// 2. Register tools (no JWT) ? see email-tool-definitions-api.md
// ... create get_ticket_status + create_ticket, save tool_ids

// 3. Create agent (JWT required) ? draft mode (default)
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
| Update agent      | `POST` | `/email-ai-agents/v1/update`            | JWT  | `{ agent_id, name, ?, email_format_template?, reply_action?, routing_rule_ids?, recipient_rule_ids? }` ? agent ? flow sync when `flow_id` set (planned) |
| List team agents  | `POST` | `/email-ai-agents/v1/list-team-agents`  | No   | `{ team_id }` |
| Trigger sync      | `POST` | `/email-ai-agents/v1/trigger-sync`      | JWT  | `{ agent_id }` |
| List team threads | `POST` | `/email-ai-agents/v1/list-team-threads` | JWT  | `{ team_id, page?, limit? }` |
| Get thread        | `POST` | `/email-ai-agents/v1/get-thread`        | JWT  | `{ team_id, thread_id, page?, limit? }` |
| Assign thread     | `POST` | `/email-ai-agents/v1/assign-thread`     | JWT  | `{ team_id, thread_id, user_id }` |
| Send AI draft     | `POST` | `/email-ai-agents/v1/send-thread-draft` | JWT  | `{ team_id, thread_id, is_edited?, body_text?, cc?, bcc? }` |

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


---

## Quick reference

| API | Method | Path | Auth | Body |
| --- | ------ | ---- | ---- | ---- |
| List team threads | `POST` | `/email-ai-agents/v1/list-team-threads` | JWT | `{ team_id, page?, limit? }` |
| Get thread | `POST` | `/email-ai-agents/v1/get-thread` | JWT | `{ team_id, thread_id, page?, limit? }` |
| Assign thread | `POST` | `/email-ai-agents/v1/assign-thread` | JWT | `{ team_id, thread_id, user_id }` |
| Send AI draft | `POST` | `/email-ai-agents/v1/send-thread-draft` | JWT | `{ team_id, thread_id, is_edited?, body_text?, cc?, bcc? }` |

---

## Related docs

- [email-ai-agent-setup.md](./email-ai-agent-setup.md) ? agent config and Gmail sync
- [email-draft-review-ui.md](./email-draft-review-ui.md) ? frontend UX for drafts and auto-send
- [email-flow-reprocess-thread-api.md](./email-flow-reprocess-thread-api.md) ? manual reprocess
- [gmail-oauth-setup.md](./gmail-oauth-setup.md) ? Gmail scopes for draft/send
