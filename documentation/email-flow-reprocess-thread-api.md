# Email Flow — Reprocess Thread API

Re-run the **full email AI flow** on an **existing** Gmail thread without sending a new inbound email. Use this to test workflow nodes, regenerate a draft, or debug a thread end-to-end.

**Related:**
- [email-flow-nodes.md](./email-flow-nodes.md) — per-node I/O and pipeline order
- [email-flow-plan.md](./email-flow-plan.md) — architecture and Mongo collections
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — agent configuration

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

## Endpoint

```
POST /email-flows/v1/reprocess-thread
```

| Item | Value |
| ---- | ----- |
| Auth | **None** (public test route — no JWT) |
| Content-Type | `application/json` |
| Behaviour | **Fire-and-forget** — returns immediately; pipeline runs in a background task |

---

## What it does

1. Validates `agent_id` and `thread_id`.
2. Creates an `email-flow-runs` document with `status: "queued"` and a new `run_id`.
3. Returns **`202 Accepted`** right away with that `run_id`.
4. Runs the full node pipeline in the background (same orchestrator production sync will use later).
5. Appends each node’s log to the run document as steps complete.
6. Sets final run `status` to `completed`, `failed`, or `skipped`.

**Current pipeline (in order):**

```
start → load_thread_context → read_kb → read_tools → ai_department_router
  → ai_recipients_generator → generate_email → save_gmail_draft → stop
```

When `agent.reply_action.mode` is **`auto_send`**, the tail is **`send_email`** (not shipped yet) — today the pipeline ends at **`stop`** after `generate_email`.

When `reply_action.mode` is **`draft`** (default), **`save_gmail_draft`** creates a Gmail draft on the thread (To + CC + BCC from `ai_recipients_generator`), sets `email-threads.ai_action`, and sets `ai_outcome` on the trigger inbound message.

Poll **`POST /email-flows/v1/get-run`** with the returned `run_id` to see progress and the final draft, routing, recipients, etc. For inbox UX, poll **`list-team-threads`** / **`get-thread`** — see [email-ai-agent-setup.md](./email-ai-agent-setup.md) (`ai_action`, `action_required`).

---

## Request body

```json
{
  "agent_id": "674abc123def456789012345",
  "thread_id": "6a253934725d1aa8ca28452c",
  "trigger_message_id": "",
  "force_reprocess": true,
  "message_limit": 10
}
```

| Field | Required | Default | Description |
| ----- | -------- | ------- | ----------- |
| `agent_id` | Yes | — | Mongo `_id` of the email AI agent (`email-ai-agents`) |
| `thread_id` | Yes | — | Gmail thread id (stored on `email-threads`) |
| `trigger_message_id` | No | `""` | Mongo message `_id` or `gmail_message_id` for the inbound message to reply to. If omitted, the **Start** node picks a trigger automatically (see below). |
| `force_reprocess` | No | `true` | Controls idempotency vs forced re-run (see dedicated section below). |
| `message_limit` | No | `10` | Max messages loaded by **Load Thread Context** (1–100). |

---

## `force_reprocess` — `true` vs `false`

This flag is passed to the **Start** node. It controls whether the flow behaves like a **test re-run** or like **production idempotency**.

### `force_reprocess: true` (default — recommended for testing)

Use when you want to **always run the pipeline**, even if this thread was already processed.

| Behaviour | Detail |
| --------- | ------ |
| Trigger selection | If `trigger_message_id` is set → that message. Otherwise → **latest inbound** message on the thread. |
| Idempotency | **Disabled** — ignores `processing_status` and existing `flow_run_id` on the trigger message. |
| Start node | Proceeds and marks the trigger message `processing_status: "processing"`. |
| Downstream nodes | Full pipeline runs (KB, tools, routing, recipients, generate email). |
| Typical use | Manual testing, “Regenerate reply” in dev, debugging after code changes. |

### `force_reprocess: false` (production-like guard)

Use when you only want to process a message that **has not been handled yet** — similar to what sync will do on a **new pending inbound**.

| Behaviour | Detail |
| --------- | ------ |
| Trigger selection | If `trigger_message_id` is set → that message. Otherwise → **latest inbound with `processing_status: "pending"`**. If none pending → falls back to latest inbound. |
| Idempotency | **Enabled** — Start **skips** the run when: |
| | • Trigger message `processing_status` is **not** `"pending"` (e.g. already `"completed"` or `"processing"`) |
| | • Trigger message already has a **`flow_run_id`** |
| Start node | Returns `status: "skipped"` with a `skip_reason`. |
| Downstream nodes | **Not executed** — run ends early with `status: "skipped"`. |
| Typical use | Simulating production “process this new email once”; avoiding duplicate drafts/sends on the same inbound. |

**Skip reasons (poll `get-run` → `node_logs[0]`):**

| `skip_reason` | Meaning |
| ------------- | ------- |
| `processing_status is 'completed', expected 'pending'.` | That inbound was already processed (or is in another state). |
| `Trigger message already has a flow_run_id.` | A previous flow run already claimed this message. |

**Example:** A customer email was processed yesterday (`processing_status: "completed"`). Calling reprocess with `force_reprocess: false` → run **`skipped`**, no new draft. Calling with `force_reprocess: true` → full pipeline runs again.

---

## Immediate response — `202 Accepted`

The HTTP response does **not** wait for LLM calls or the full pipeline.

```json
{
  "success": true,
  "message": "Thread reprocess in progress.",
  "data": {
    "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "queued",
    "agent_id": "674abc123def456789012345",
    "thread_id": "6a253934725d1aa8ca28452c",
    "trigger_message_id": "",
    "force_reprocess": true,
    "message_limit": 10,
    "poll_run_endpoint": "/elysium-agents/email-flows/v1/get-run"
  }
}
```

Store **`data.run_id`** — you need it to poll for results.

---

## Poll for completion

```
POST /elysium-agents/email-flows/v1/get-run
```

**Body:**

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### Run status lifecycle

| `status` | Meaning |
| -------- | ------- |
| `queued` | Run created; background worker not started or about to start |
| `running` | Pipeline in progress |
| `completed` | All nodes finished successfully |
| `failed` | A node failed or an unexpected background error occurred |
| `skipped` | Start node skipped (usually `force_reprocess: false` + already processed) |

Poll until `status` is terminal (`completed`, `failed`, or `skipped`).

### Completed run — useful fields

```json
{
  "success": true,
  "message": "Flow run fetched successfully.",
  "data": {
    "run_id": "...",
    "status": "completed",
    "run_type": "reprocess",
    "node_logs": [
      { "node_id": "start", "status": "ok" },
      { "node_id": "load_thread_context", "status": "ok" },
      { "node_id": "read_kb", "status": "ok" },
      { "node_id": "read_tools", "status": "ok" },
      { "node_id": "ai_department_router", "status": "ok" },
      { "node_id": "ai_recipients_generator", "status": "ok" },
      { "node_id": "generate_email", "status": "ok", "output": { "llm_prompt_text": "..." } }
    ],
    "context": {
      "compressed_query": "...",
      "kb_chunks": [],
      "routing": { "department_id": "...", "decision_source": "llm_matched" },
      "recipients": { "to": ["customer@example.com"], "cc": [], "bcc": [] },
      "draft": {
        "subject": "Re: Support request",
        "body_text": "...",
        "confidence": 0.72,
        "decision_source": "llm_generated"
      }
    }
  }
}
```

**Audit tip:** `node_logs[].output.llm_prompt_text` on **generate_email** (and similar fields on other LLM nodes) contains the full prompt sent to the model.

---

## Error responses (immediate — before background starts)

| HTTP | `message` | Cause |
| ---- | --------- | ----- |
| `400` | `Invalid agent_id.` | Malformed Mongo id |
| `400` | `thread_id is required.` | Empty thread id |
| `404` | `Email AI agent not found.` | Unknown `agent_id` |
| `500` | Queue/server error | Unexpected failure creating the run |

Validation errors return synchronously (no `run_id`).

---

## Frontend examples

### Fire-and-forget + poll

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function reprocessThread(agentId, threadId, options = {}) {
  const {
    triggerMessageId = "",
    forceReprocess = true,
    messageLimit = 10,
    pollIntervalMs = 2000,
    maxPollAttempts = 120,
  } = options;

  const startRes = await fetch(`${BASE}/email-flows/v1/reprocess-thread`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agent_id: agentId,
      thread_id: threadId,
      trigger_message_id: triggerMessageId,
      force_reprocess: forceReprocess,
      message_limit: messageLimit,
    }),
  });

  const startData = await startRes.json();
  if (!startRes.ok || !startData.success) {
    throw new Error(startData.message || "Failed to queue reprocess");
  }

  const runId = startData.data.run_id;

  for (let attempt = 0; attempt < maxPollAttempts; attempt += 1) {
    await new Promise((r) => setTimeout(r, pollIntervalMs));

    const pollRes = await fetch(`${BASE}/email-flows/v1/get-run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    });

    const pollData = await pollRes.json();
    if (!pollRes.ok || !pollData.success) {
      throw new Error(pollData.message || "Failed to poll run");
    }

    const status = pollData.data.status;
    if (["completed", "failed", "skipped"].includes(status)) {
      return pollData.data;
    }
  }

  throw new Error("Reprocess timed out while polling");
}

// Testing — always re-run
await reprocessThread("674abc...", "6a253934...", { forceReprocess: true });

// Production-like — skip if already processed
await reprocessThread("674abc...", "6a253934...", { forceReprocess: false });
```

---

## Related APIs

| API | Path | Purpose |
| --- | ---- | ------- |
| Get run | `POST /email-flows/v1/get-run` | Poll run status, `node_logs`, final `context` |
| List thread runs | `POST /email-flows/v1/list-thread-runs` | History of runs for a thread |
| Preview load context | `POST /email-flows/v1/preview-load-thread-context` | **Only** Load Thread Context — not the full pipeline |

---

## Mongo collections

| Collection | What gets written |
| ---------- | ----------------- |
| `email-flow-runs` | One document per reprocess: `run_id`, `status`, `node_logs[]`, final `context` |
| `email-thread-messages` | Start node updates trigger message `processing_status` / `flow_run_id` when the run proceeds |

---

## Quick reference

| | |
| --- | --- |
| **Method** | `POST` |
| **Path** | `/elysium-agents/email-flows/v1/reprocess-thread` |
| **Auth** | None |
| **Response** | `202` — `{ run_id, status: "queued", ... }` |
| **Poll** | `POST /email-flows/v1/get-run` with `{ run_id }` |
| **`force_reprocess: true`** | Always run (testing) |
| **`force_reprocess: false`** | Skip if inbound already processed (production-like) |
