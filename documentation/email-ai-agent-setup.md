# Email AI Agent — Configuration & Thread Sync Guide (MVP)

Configure an email AI agent, sync Gmail **threads** (inbound + outbound), and build a Gmail-style inbox in your app.

**Collections:** `email-ai-agents`, `email-threads`, `email-thread-messages`

---

## What is an email AI agent?

An agent links a **name** to a **Gmail inbox**. When active, sync pulls **complete email threads** into Mongo — both emails you receive and replies you send from Gmail.

---

## Prerequisites

```
1. Login          →  JWT (user_id + team_id)
2. Connect Gmail  →  email-gmail_accounts (account_id)
3. Create agent   →  name + gmail_account_id (status=active, activated_at set)
4. Trigger sync   →  fetch up to 20 threads with recent activity
5. List threads   →  inbox list (snippet only)
6. Get thread     →  full conversation with bodies
```

See [gmail-oauth-setup.md](./gmail-oauth-setup.md) and [email-auth-login-api.md](./email-auth-login-api.md).

---

## Base URL

```
http://localhost:7000/elysium-agents
```

---

## Frontend buttons needed

| Button              | API                                          | When to show                                 |
| ------------------- | -------------------------------------------- | -------------------------------------------- |
| **Create Agent**    | `POST /email-ai-agents/v1/create`            | User picked inbox + entered agent name       |
| **Sync Inbox**      | `POST /email-ai-agents/v1/trigger-sync`      | Agent exists and `sync_status !== "syncing"` |
| **Refresh Threads** | `POST /email-ai-agents/v1/list-team-threads` | Inbox list page / after sync                 |
| **Open Thread**     | `POST /email-ai-agents/v1/get-thread`        | User clicks a thread row                     |
| **Refresh Agents**  | `POST /email-ai-agents/v1/list-team-agents`  | Agent list page                              |

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

## 1. Create Email AI Agent

```
POST /elysium-agents/email-ai-agents/v1/create
Authorization: Bearer <jwt>
```

**Body:**

```json
{
  "name": "Support Agent",
  "gmail_account_id": "674a1b2c3d4e5f6789012345"
}
```

On create: `status=active`, `activated_at=now` — only thread activity **after** this time is discovered on first sync.

---

## 2. List Team Agents

```
POST /elysium-agents/email-ai-agents/v1/list-team-agents
```

**Body:** `{ "team_id": "team_123" }`

Use this to poll `sync_status` / `last_sync_error` / `last_synced_at`.

---

## 3. Trigger Inbox Sync

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

## 4. List Team Threads (inbox list — snippet only)

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

---

## 5. Get Thread (full conversation — paginated messages)

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
    "assigned_user_id": ""
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
      "created_at": "2026-06-06T12:06:00Z"
    },
    {
      "message_id": "674d4e5f6789012351",
      "direction": "outbound",
      "from": "Support <support@gmail.com>",
      "to": ["customer@example.com"],
      "body_text": "Thanks for reaching out...",
      "received_at": "2026-06-06T13:00:00Z"
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
  "created_at": "...",
  "updated_at": "..."
}
```

| Field | Description |
| ----- | ----------- |
| `department_id` | Department assigned to this thread. Empty until assigned — **members cannot see** unassigned threads. When set, only members in that department can see it (unless `assigned_user_id` restricts further). |
| `assigned_user_id` | Team user assigned to this thread. Empty until assigned. When empty, all members in the thread's department can see it. When set, only that user (plus admins) can see it. |

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
  "status": "stored"
}
```

`direction: "outbound"` when Gmail `labelIds` contains `SENT`.

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

| API               | Method | Path                                    | Auth |
| ----------------- | ------ | --------------------------------------- | ---- |
| Create agent      | `POST` | `/email-ai-agents/v1/create`            | JWT  |
| List team agents  | `POST` | `/email-ai-agents/v1/list-team-agents`  | No   |
| Trigger sync      | `POST` | `/email-ai-agents/v1/trigger-sync`      | JWT  |
| List team threads | `POST` | `/email-ai-agents/v1/list-team-threads` | JWT  |
| Get thread        | `POST` | `/email-ai-agents/v1/get-thread`        | JWT  |

---

## Migration note

The old `email-inbound-messages` collection and `list-agent-messages` API are replaced by thread-based storage. Delete old test data and re-sync to populate `email-threads` and `email-thread-messages`.

---

## What's next

- System prompt, KB, tools per agent
- AI processing of thread messages
- Auto-sync (cron) or Gmail push via `historyId`
- Attachment download API

---

## Related docs

- [gmail-oauth-setup.md](./gmail-oauth-setup.md)
- [email-auth-login-api.md](./email-auth-login-api.md)
- [departments-api.md](./departments-api.md)
