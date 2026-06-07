# Email AI Draft — Inbox & Thread UI Guide

How to build the **“draft ready — needs your attention”** experience in the frontend: inbox badges, thread draft panel, and **Send** from your app (without opening Gmail).

**Related:**
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — `list-team-threads`, `get-thread` API shapes
- [email-flow-nodes.md](./email-flow-nodes.md) — `save_gmail_draft` node behaviour
- [gmail-oauth-setup.md](./gmail-oauth-setup.md) — `gmail.compose` + `gmail.send` scopes

---

## Overview

After the AI flow runs with `reply_action.mode: "draft"`:

1. A **Gmail draft** is created on the linked inbox (visible in Gmail).
2. **`email-threads.ai_action`** is set with `status: "draft_ready"` (inbox badge).
3. The **trigger inbound message** gets `ai_outcome.type: "draft_created"`.
4. The user reviews the draft in your app and clicks **Send** → `POST /send-thread-draft`.

```
Flow completes (save_gmail_draft)
        ↓
list-team-threads  →  action_required: true  →  "Needs your attention"
        ↓
get-thread         →  thread.ai_action.body_text  →  show draft panel
        ↓
send-thread-draft  →  Gmail sends draft  →  ai_action.status: "resolved"
```

---

## 1. Inbox list — “requires your attention”

**API:** `POST /elysium-agents/email-ai-agents/v1/list-team-threads`

Each thread row may include:

| Field | Use in UI |
| ----- | --------- |
| `action_required` | `true` → show badge, dot, or banner: **“Draft ready — review”** |
| `ai_action.status` | `"draft_ready"` when pending; `"resolved"` after send |
| `ai_action.subject` | Optional subtitle in list row |
| `ai_action.confidence` | Optional chip (e.g. `72% confidence`) |
| `ai_action.created_at` | “Draft created 2m ago” |

**Example row logic:**

```javascript
function threadAttentionLabel(thread) {
  if (!thread.action_required) return null;
  return {
    label: "Draft ready — review",
    tone: "warning",
    threadId: thread.thread_id,
  };
}
```

**Filter (optional):** “Needs review” tab → `threads.filter(t => t.action_required)`.

**Note:** `list-team-threads` does **not** return draft `body_text` (keep the list lightweight). Open the thread for full content.

---

## 2. Thread view — show the AI draft

**API:** `POST /elysium-agents/email-ai-agents/v1/get-thread`

When `thread.action_required === true`, render an **AI Draft** panel (above the message list or after the trigger message).

### Data source: `thread.ai_action`

```json
{
  "status": "draft_ready",
  "type": "draft",
  "flow_run_id": "uuid",
  "trigger_message_id": "674d4e5f6789012350",
  "gmail_draft_id": "r-123456789",
  "gmail_draft_message_id": "18f3draft456",
  "confidence": 0.72,
  "subject": "Re: Refund request",
  "body_text": "Hi John,\n\nThank you for reaching out...",
  "recipients": {
    "to": ["customer@example.com"],
    "cc": ["manager@example.com"],
    "bcc": [],
    "cc_users": [{ "user_id": "...", "email": "...", "name": "..." }],
    "matched_recipient_rules": [{ "rule_name": "...", "cc": [], "bcc": [] }]
  },
  "created_at": "2026-06-07T16:30:00Z",
  "resolved_at": null
}
```

| Field | UI |
| ----- | -- |
| `body_text` | Main draft preview (plain text; preserve `\n`) |
| `subject` | Draft subject line |
| `recipients.to` / `cc` / `bcc` | To / Cc / Bcc chips |
| `confidence` | Optional trust indicator |
| `trigger_message_id` | Highlight which inbound message this replies to |

### Highlight the trigger message

In the `messages` array, find the inbound where `message_id === thread.ai_action.trigger_message_id` and add a visual marker (“AI drafted a reply to this email”). That message may also have:

```json
"ai_outcome": {
  "type": "draft_created",
  "gmail_draft_id": "r-123456789",
  "flow_run_id": "uuid",
  "confidence": 0.72,
  "recipients": { "to": [], "cc": [], "bcc": [] }
}
```

### Suggested layout

```
┌─────────────────────────────────────────────┐
│ Thread: Re: Refund request                  │
├─────────────────────────────────────────────┤
│ ⚠ AI draft ready (confidence 72%)           │
│ To: customer@example.com                    │
│ Cc: manager@example.com                     │
│ Subject: Re: Refund request                 │
│ ─────────────────────────────────────────── │
│ Hi John,                                    │
│ Thank you for reaching out...               │
│ ─────────────────────────────────────────── │
│ [ Send reply ]  [ Open in Gmail ] (optional)│
├─────────────────────────────────────────────┤
│ (chronological messages…)                   │
└─────────────────────────────────────────────┘
```

**Open in Gmail (optional):** deep link is not provided by the API today; user can open Gmail manually. The draft already exists there via `gmail_draft_id`.

---

## 3b. Outbound messages — `ai_reply` (after Send)

Once the user sends via **`send-thread-draft`**, the sent **outbound** row in `email-thread-messages` is tagged with **`ai_reply`**.

**API:** `get-thread` → each message in `messages[]` (outbound only when set)

```json
{
  "message_id": "674d4e5f6789012352",
  "direction": "outbound",
  "from": "Orvera Support <support@orvera.ai>",
  "body_text": "Hi John,\n\nThank you for reaching out...",
  "ai_reply": {
    "assisted": true,
    "mode": "reviewed",
    "flow_run_id": "uuid",
    "agent_id": "674c3d4e5f6789012349",
    "confidence": 0.72,
    "gmail_draft_id": "r-123456789",
    "sender_email": "support@orvera.ai",
    "sender_name": "Orvera Support"
  }
}
```

| Field | Meaning |
| ----- | ------- |
| `from` | Formatted sender on the outbound row (same as other messages); use for display name in thread UI |
| `ai_reply.sender_email` / `ai_reply.sender_name` | Linked Gmail account that sent the draft (fallback if `from` is empty on older rows) |
| `ai_reply.assisted` | `true` — this outbound was AI-assisted |
| `ai_reply.mode` | `"reviewed"` — human sent after reviewing AI draft; `"auto"` — future auto-send without review |
| *(field absent)* | Normal outbound (human wrote in Gmail / unknown) |

**Frontend chip on outbound bubble:**

```javascript
function outboundLabel(message) {
  if (message.direction !== "outbound" || !message.ai_reply?.assisted) return null;
  if (message.ai_reply.mode === "reviewed") return "AI · reviewed";
  if (message.ai_reply.mode === "auto") return "AI · auto";
  return "AI";
}
```

Set immediately on **`send-thread-draft`** success (stub row if sync has not run yet; sync merges full Gmail body later).

---

## 3. Send draft from your app

**API:** `POST /elysium-agents/email-ai-agents/v1/send-thread-draft`

Sends the **existing Gmail draft** via Gmail `users.drafts.send` (uses `gmail.compose` / `gmail.send` on the linked inbox). Marks `ai_action.status` as **`resolved`**.

### Request

```http
POST /elysium-agents/email-ai-agents/v1/send-thread-draft
Content-Type: application/json
Authorization: Bearer <jwt>
```

```json
{
  "team_id": "callbotics",
  "thread_id": "19ea2eb87b3aaf4a"
}
```

| Field | Required | Description |
| ----- | -------- | ----------- |
| `team_id` | Yes | Must match JWT `team_id` |
| `thread_id` | Yes | Gmail thread id from list/get-thread |

Same **thread visibility rules** as `get-thread` (department / assigned user). Returns `403` if the user cannot access the thread.

### Success `200`

```json
{
  "success": true,
  "message": "AI draft sent successfully.",
  "data": {
    "thread_id": "19ea2eb87b3aaf4a",
    "gmail_draft_id": "r-123456789",
    "gmail_message_id": "18f3sent789",
    "gmail_thread_id": "19ea2eb87b3aaf4a",
    "label_ids": ["SENT"],
    "ai_action_status": "resolved",
    "ai_reply": {
      "assisted": true,
      "mode": "reviewed",
      "flow_run_id": "uuid",
      "agent_id": "674c3d4e5f6789012349",
      "confidence": 0.72,
      "gmail_draft_id": "r-123456789",
      "sender_email": "support@orvera.ai",
      "sender_name": "Orvera Support"
    }
  }
}
```

Also tags the outbound message in **`email-thread-messages`** with the same `ai_reply` object (visible on next `get-thread`).

### Errors

| Status | When |
| ------ | ---- |
| `403` | User cannot access thread |
| `404` | Thread not found |
| `409` | No pending draft (`ai_action.status !== "draft_ready"`) |
| `400` | Missing `gmail_draft_id`, Gmail token/draft send failure |

### Frontend flow after Send

```javascript
async function sendAiDraft({ teamId, threadId, token }) {
  const res = await fetch(`${BASE}/email-ai-agents/v1/send-thread-draft`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ team_id: teamId, thread_id: threadId }),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message);

  // Refresh thread — action_required should now be false
  await refreshThread(teamId, threadId);

  // Optional: trigger agent sync so the sent message appears in messages[]
  // POST /email-ai-agents/v1/trigger-sync { agent_id }
  return data.data;
}
```

1. Disable **Send** button while request is in flight.
2. On success → re-fetch `get-thread` (draft panel hides; `action_required: false`).
3. Optionally call **`trigger-sync`** on the agent so the new **outbound** message appears in `messages` without waiting for the next poll.

---

## 4. State lifecycle

| State | `action_required` | `ai_action.status` | UI |
| ----- | ----------------- | ------------------ | -- |
| AI draft saved | `true` | `draft_ready` | Badge + draft panel + Send enabled |
| User sent via app | `false` | `resolved` | Hide panel; outbound message gets `ai_reply.mode: "reviewed"` |
| User sent from Gmail only | `true`* | `draft_ready`* | *Until sync + resolve logic ships — may still show badge briefly |
| New inbound on thread | TBD | `superseded` (future) | New flow run replaces old action |

**Today:** sending via **`send-thread-draft`** clears the actionable state immediately. Sending from Gmail directly does not auto-clear `ai_action` yet (future: sync detects outbound `SENT` and resolves).

---

## 5. Polling / refresh

| Screen | When to refresh |
| ------ | ---------------- |
| Inbox list | After sync, after user sends draft, periodic poll if flow runs in background |
| Thread detail | On open, after Send, after reprocess-thread |

If you use **`reprocess-thread`** for testing, poll `get-thread` until `action_required` becomes `true`.

---

## 6. API quick reference

| Action | Method | Path |
| ------ | ------ | ---- |
| Inbox list + badges | `POST` | `/email-ai-agents/v1/list-team-threads` |
| Thread + draft body | `POST` | `/email-ai-agents/v1/get-thread` |
| Send AI draft | `POST` | `/email-ai-agents/v1/send-thread-draft` |
| Refresh messages after send | `POST` | `/email-ai-agents/v1/trigger-sync` |

---

## 7. Checklist for frontend

- [ ] Inbox row: show attention badge when `thread.action_required`
- [ ] Thread page: render `thread.ai_action` panel when `draft_ready`
- [ ] Display `body_text`, `subject`, To/Cc/Bcc from `ai_action.recipients`
- [ ] Highlight message where `message_id === ai_action.trigger_message_id`
- [ ] **Send reply** button → `POST /send-thread-draft`
- [ ] After send: refresh `get-thread`; clear badge on list
- [ ] Outbound bubbles: show **AI · reviewed** when `message.ai_reply?.mode === "reviewed"`
- [ ] Outbound sender: use `message.from`, or `ai_reply.sender_name` + `ai_reply.sender_email` as fallback
- [ ] Handle `409` (already sent / no draft) gracefully
- [ ] Gmail OAuth includes `gmail.compose` + `gmail.send` ([gmail-oauth-setup.md](./gmail-oauth-setup.md))

---

## 8. Older runs without `body_text`

Threads processed **before** `body_text` was stored on `ai_action` may have a draft in Gmail but empty `ai_action.body_text`. Options:

- Re-run **`reprocess-thread`** to regenerate, or
- Fall back to **`get-run`** with `ai_action.flow_run_id` and read `context.draft.body_text` (debug only).

New flow runs always populate `body_text` on `ai_action`.
