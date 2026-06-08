# Email AI Inbox & Thread UI Guide

How to build the frontend inbox experience for AI-assisted replies: **draft review**, **auto-send**, and **draft fallback** (auto-send skipped). Covers inbox badges, thread panels, outbound labels, and **Send from app** when a Gmail draft is pending.

**Related:**
- [email-threads-api.md](./email-threads-api.md) — `list-team-threads`, `get-thread` API shapes
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — agent config and sync
- [email-flow-nodes.md](./email-flow-nodes.md) — `save_gmail_draft` and `send_email` node behaviour
- [gmail-oauth-setup.md](./gmail-oauth-setup.md) — `gmail.compose` + `gmail.send` scopes

---

## Overview

Behaviour depends on **`agent.reply_action.mode`**:

| Mode | After flow completes | User action |
| ---- | -------------------- | ----------- |
| **`draft`** | Gmail draft created; `ai_action.status: "draft_ready"` | Review + **Send** via app (or Gmail) |
| **`auto_send`** + confidence ≥ threshold | Reply **sent** via Gmail; `ai_action.status: "sent"` | None — informational UI only |
| **`auto_send`** + confidence &lt; threshold | Draft fallback; `ai_action.type: "draft_fallback"` | Same as draft mode — review + Send |

### Draft-only flow (`reply_action.mode: "draft"`)

1. A **Gmail draft** is created on the linked inbox (visible in Gmail).
2. **`email-threads.ai_action`** is set with `status: "draft_ready"`, `type: "draft"`.
3. The **trigger inbound message** gets `ai_outcome.type: "draft_created"`.
4. The user reviews the draft in your app and clicks **Send** → `POST /send-thread-draft`.

```
Flow completes (save_gmail_draft)
        ↓
list-team-threads  →  action_required: true  →  "Draft ready — review"
        ↓
get-thread         →  thread.ai_action.body_text  →  show draft panel + Send
        ↓
send-thread-draft  →  Gmail sends draft  →  ai_action.status: "resolved"
```

### Auto-send flow (`reply_action.mode: "auto_send"`)

1. Flow compares `draft.confidence` to `reply_action.auto_send_min_confidence`.
2. **High confidence** → direct Gmail send (`users.messages.send`); no draft in inbox.
3. **Low confidence** → same as draft mode but `ai_action.type: "draft_fallback"` + `fallback_reason: "confidence_below_threshold"`.

```
Flow completes (send_email)
        ↓
confidence >= threshold?
   yes → ai_action.status: "sent"     →  action_required: false  →  "AI replied"
   no  → ai_action.status: "draft_ready", type: "draft_fallback"
                              →  action_required: true  →  "Auto-send skipped — review draft"
```

**Sync trigger:** `POST /trigger-sync` runs the full flow automatically for threads with new inbound mail (same pipeline as manual reprocess). Poll until `sync_status === "idle"`, then refresh `list-team-threads`.

---
## 1. Inbox list — badges and filters

**API:** `POST /elysium-agents/email-ai-agents/v1/list-team-threads`

Each thread row may include:

| Field | Use in UI |
| ----- | --------- |
| `is_ai_processing` | `true` → show **“AI working…”** spinner/badge on the row |
| `ai_status.current_status` | `"processing"` while flow runs; `"idle"` / `"failed"` when done |
| `ai_status.flow_run_id` | Optional — link to debug `get-run` |
| `action_required` | `true` only when `ai_action.status === "draft_ready"` — human must review/send |
| `ai_action.status` | `"draft_ready"` (pending draft), `"sent"` (auto-sent audit), `"resolved"` (user sent via app) |
| `ai_action.type` | `"draft"`, `"draft_fallback"`, or `"auto_send"` — drives copy (see below) |
| `ai_action.fallback_reason` | When `type === "draft_fallback"`: `"confidence_below_threshold"` |
| `ai_action.confidence` | Model confidence; compare to `ai_action.auto_send_min_confidence` on fallback rows |
| `ai_action.subject` | Optional subtitle in list row |
| `ai_action.created_at` | “Draft created 2m ago” / “AI replied 2m ago” |

**`action_required` rule (backend):** `true` iff `ai_action.status === "draft_ready"`. Auto-sent threads (`status: "sent"`) → **`action_required: false`**.

**Example row logic:**

```javascript
function threadAttentionLabel(thread) {
  const action = thread.ai_action;
  if (!action) return null;

  if (thread.action_required) {
    if (action.type === "draft_fallback") {
      return {
        label: "Auto-send skipped — review draft",
        tone: "warning",
        threadId: thread.thread_id,
      };
    }
    return {
      label: "Draft ready — review",
      tone: "warning",
      threadId: thread.thread_id,
    };
  }

  if (action.status === "sent" && action.type === "auto_send") {
    return {
      label: "AI replied",
      tone: "success",
      threadId: thread.thread_id,
    };
  }

  return null;
}
```

**Filter (optional):**

- **AI working** → `threads.filter(t => t.is_ai_processing)`
- **Needs review** → `threads.filter(t => t.action_required)`
- **AI auto-replied** → `threads.filter(t => t.ai_action?.status === "sent")`

**Note:** `list-team-threads` does **not** return draft `body_text` (keep the list lightweight). Open the thread for full content.
---

## 2. Thread view — draft panel vs auto-sent banner

**API:** `POST /elysium-agents/email-ai-agents/v1/get-thread`

### 2a. Pending draft (`action_required === true`)

Render an **AI Draft** panel when `thread.ai_action.status === "draft_ready"` (both `type: "draft"` and `type: "draft_fallback"`).

#### Data source: `thread.ai_action` (draft)

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

#### Draft fallback (`type: "draft_fallback"`)

Same shape as draft, plus:

```json
{
  "status": "draft_ready",
  "type": "draft_fallback",
  "fallback_reason": "confidence_below_threshold",
  "confidence": 0.65,
  "auto_send_min_confidence": 0.8,
  "threshold_met": false,
  "gmail_draft_id": "r-123456789",
  "body_text": "...",
  "resolved_at": null
}
```

**UI copy:** banner **“Auto-send skipped — confidence below threshold (65% &lt; 80%)”** + same draft panel and **Send reply** button as draft-only mode.

| Field | UI |
| ----- | -- |
| `body_text` | Main draft preview (plain text; preserve `\n`) |
| `subject` | Draft subject line |
| `recipients.to` / `cc` / `bcc` | To / Cc / Bcc chips |
| `confidence` | Trust indicator; show threshold when `draft_fallback` |
| `trigger_message_id` | Highlight which inbound message this replies to |

### 2b. Auto-sent (`ai_action.status === "sent"`)

No **Send** button — reply already sent. Show an informational banner (not actionable):

```json
{
  "status": "sent",
  "type": "auto_send",
  "flow_run_id": "uuid",
  "trigger_message_id": "674d4e5f6789012350",
  "gmail_message_id": "18f3sent789",
  "confidence": 0.92,
  "auto_send_min_confidence": 0.8,
  "threshold_met": true,
  "subject": "Re: Refund request",
  "body_text": "Hi John,\n\nThank you for reaching out...",
  "recipients": { "to": ["customer@example.com"], "cc": [], "bcc": [] },
  "created_at": "2026-06-07T16:30:00Z",
  "resolved_at": "2026-06-07T16:30:01Z"
}
```

**Suggested banner:** “AI replied automatically (92% confidence)” — optional expand to show `body_text` / recipients.

The sent **outbound** message appears in `messages[]` with `ai_reply.mode: "auto"` (stub immediately; sync merges full body later).

### Highlight the trigger message

In the `messages` array, find the inbound where `message_id === thread.ai_action.trigger_message_id`.

**Draft / fallback — trigger `ai_outcome`:**

```json
"ai_outcome": {
  "type": "draft_created",
  "gmail_draft_id": "r-123456789",
  "flow_run_id": "uuid",
  "confidence": 0.72,
  "fallback_reason": "confidence_below_threshold",
  "auto_send_min_confidence": 0.8,
  "threshold_met": false,
  "recipients": { "to": [], "cc": [], "bcc": [] }
}
```

**Auto-sent — trigger `ai_outcome`:**

```json
"ai_outcome": {
  "type": "auto_sent",
  "gmail_message_id": "18f3sent789",
  "flow_run_id": "uuid",
  "confidence": 0.92,
  "auto_send_min_confidence": 0.8,
  "threshold_met": true,
  "recipients": { "to": [], "cc": [], "bcc": [] }
}
```

### Suggested layout (draft / fallback)

```
┌─────────────────────────────────────────────┐
│ Thread: Re: Refund request                  │
├─────────────────────────────────────────────┤
│ ⚠ AI draft ready (confidence 72%)           │
│   — or —                                    │
│ ⚠ Auto-send skipped (65% < 80%) — review    │
│ To: customer@example.com                    │
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

**Open in Gmail (optional):** deep link is not provided by the API today; user can open Gmail manually. Drafts use `gmail_draft_id`; auto-sent messages appear as normal sent mail.
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
| `ai_reply.mode` | `"reviewed"` — human sent via app after AI draft; `"auto"` — auto-send (no review) |
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

Set on **`send-thread-draft`** success (`mode: "reviewed"`) or immediately after **auto-send** flow (`mode: "auto"`). Stub row if sync has not run yet; sync merges full Gmail body later.

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

| State | `action_required` | `ai_action.status` | `ai_action.type` | UI |
| ----- | ----------------- | ------------------ | ---------------- | -- |
| Draft saved (`mode: draft`) | `true` | `draft_ready` | `draft` | Badge + draft panel + Send |
| Auto-send skipped (low confidence) | `true` | `draft_ready` | `draft_fallback` | “Auto-send skipped” + draft panel + Send |
| Auto-sent (high confidence) | `false` | `sent` | `auto_send` | “AI replied” banner; outbound `ai_reply.mode: "auto"` |
| User sent via app | `false` | `resolved` | `draft` / `draft_fallback` | Hide panel; outbound `ai_reply.mode: "reviewed"` |
| User sent from Gmail only | `true`* | `draft_ready`* | `draft`* | *Until sync + resolve logic ships — may still show badge briefly |
| New inbound on thread | TBD | `superseded` (future) | — | New flow run replaces old action |

**Today:** **`send-thread-draft`** clears actionable draft state immediately. Auto-sent threads keep `ai_action` with `status: "sent"` as an audit trail (`resolved_at` set). Sending from Gmail directly does not auto-clear `ai_action` yet (future: sync detects outbound `SENT` and resolves).
---

## 5. Polling / refresh

| Screen | When to refresh |
| ------ | ---------------- |
| Inbox list | After sync completes (`sync_status: "idle"`), after user sends draft, periodic poll while sync runs |
| Thread detail | On open, after Send, after sync/reprocess |

After **`trigger-sync`**, poll `list-team-agents` until `sync_status === "idle"` — sync runs the flow for new inbound threads automatically. Then refresh inbox.

If you use **`reprocess-thread`** for testing, poll `get-thread` until `action_required` becomes `true` (draft/fallback) or `ai_action.status === "sent"` (auto-send).
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

- [ ] Inbox row: **“AI working…”** when `thread.is_ai_processing`
- [ ] Inbox row: attention badge when `thread.action_required` (`draft` or `draft_fallback`)
- [ ] Inbox row: optional “AI replied” badge when `ai_action.status === "sent"`
- [ ] Different copy for `ai_action.type === "draft_fallback"` vs `"draft"`
- [ ] Thread page: draft panel when `ai_action.status === "draft_ready"`
- [ ] Thread page: info banner when `ai_action.status === "sent"` (no Send button)
- [ ] Display `body_text`, `subject`, To/Cc/Bcc from `ai_action.recipients`
- [ ] Show confidence vs `auto_send_min_confidence` on fallback rows
- [ ] Highlight message where `message_id === ai_action.trigger_message_id`
- [ ] **Send reply** button → `POST /send-thread-draft` (only when `draft_ready`)
- [ ] After send: refresh `get-thread`; clear badge on list
- [ ] Outbound bubbles: **AI · reviewed** when `ai_reply.mode === "reviewed"`
- [ ] Outbound bubbles: **AI · auto** when `ai_reply.mode === "auto"`
- [ ] Handle `409` on send (already sent / no draft) gracefully
- [ ] Gmail OAuth includes `gmail.compose` + `gmail.send` ([gmail-oauth-setup.md](./gmail-oauth-setup.md))
- [ ] Agent form: `reply_action.mode` radio + confidence slider for `auto_send`
---

## 8. Older runs without `body_text`

Threads processed **before** `body_text` was stored on `ai_action` may have a draft in Gmail but empty `ai_action.body_text`. Options:

- Re-run **`reprocess-thread`** to regenerate, or
- Fall back to **`get-run`** with `ai_action.flow_run_id` and read `context.draft.body_text` (debug only).

New flow runs always populate `body_text` on `ai_action`.
