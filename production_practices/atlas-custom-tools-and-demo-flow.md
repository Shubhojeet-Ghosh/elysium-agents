# Atlas custom tools & demo flow — study notes

Short reference for **what we built**, **why**, and **where in the code**. Assumes you know FastAPI + async Mongo.

---

## 1. Big picture

```
Visitor message
    → RAG + chat history + system prompts
    → [optional] Tool orchestration (DeepSeek + HTTP)
    → Final reply LLM (agent's configured model, streamed)
```

| Piece | Where it lives |
|-------|----------------|
| Tool definitions (CRUD) | Team `atlas_tools` collection |
| Agent attachment | `atlas_agents.tool_ids[]` |
| Orchestration limits | `atlas_agents.tool_calling_config` |
| Chat entrypoint | `services/.../agent_chat_services.py` → `chat_with_agent_v1` |
| Tool execution | `services/.../atlas_tool_execution_services.py` |
| Demo HTTP APIs | `routes/demo/demo_customer_inquiry_routes.py` |

**Why two LLMs?** Tool calling uses OpenAI-style `tools` + `tool` roles. The final model might be Claude/Grok and only accepts plain messages. So **DeepSeek decides and runs tools**; results are injected as **plain-text assistant messages** for the final model.

---

## 2. Layering (production pattern)

```
routes/          → HTTP only, Depends(auth)
controllers/     → status codes, JSONResponse
services/        → business logic, Mongo, httpx
config/          → Pydantic models, defaults, validation
```

Demo follows the same split under `routes/demo/`, `controllers/demo_controller_files/`, `services/demo/`.

**Why:** handlers stay thin; tool logic is testable and reusable from ARQ later if needed.

---

## 3. Attaching tools to an agent

- Tools are **team-scoped** (`atlas_tools`).
- Agents store **`tool_ids: string[]`** (max 50, same team, deduped).
- Validated in `atlas_tool_services.validate_agent_tool_ids` on create/update.

No tools on agent → **no tool LLM call** (see §7).

---

## 4. One chat turn — tool path

**Gate in chat service** — only runs when there are IDs and config is enabled:

```python
tool_ids = (agent_data or {}).get("tool_ids") or []
tool_calling_config = normalize_tool_calling_config(
    (agent_data or {}).get("tool_calling_config")
)
if tool_ids and tool_calling_config.get("enabled"):
    tool_turn_messages = await run_agent_tool_calling_round(
        messages, tool_ids,
        tool_calling_config=tool_calling_config,
        temperature=tool_temperature,
    )
    if tool_turn_messages:
        messages = build_messages_list(..., tool_turn_messages=tool_turn_messages, ...)
```

Then the **normal** `handler(chat_payload)` runs with the enriched `messages`.

**Why rebuild messages?** Tool results must sit **before** the current user message, same as RAG context ordering.

---

## 5. Multi-round orchestration loop

File: `atlas_tool_execution_services.py` → `run_agent_tool_calling_round`

```
for round in range(max_rounds):
    DeepSeek(messages + tools) → tool_calls?
    if none: break
    append assistant + tool_calls to working_messages
    execute HTTP for each call (respect parallel_calls_per_round, max_executions)
    append role=tool results to working_messages (for next DeepSeek round)
    append plain-text results to final_turn_messages (for final LLM)
```

| Config key | Purpose |
|------------|---------|
| `max_rounds` | Plan → act → replan cycles (chaining) |
| `max_executions_per_turn` | Cap total HTTP calls per message |
| `parallel_calls_per_round` | All tool_calls in one round vs first only |
| `stop_on_error` | Stop loop on `{ "error": true }` payloads |
| `enabled` | Kill switch without detaching `tool_ids` |

Defaults live in `config/atlas_tool_calling_config.py` (same merge/validate pattern as `lead_collection_config`).

**Why limits?** Prevents runaway cost/latency if the model loops or fans out.

---

## 6. Executing one HTTP tool

```python
# GET/DELETE → query params from LLM arguments
if method in {"GET", "DELETE"}:
    response = await client.request(method, url, params={**auth_query, **safe_arguments}, ...)
# POST/PUT/PATCH → JSON body
else:
    response = await client.request(method, url, json=safe_arguments, ...)
```

- Tool `name` in DB must match OpenAI function name.
- Auth tokens stored encrypted (`atlas_tool_secrets`); never returned on read.
- Results truncated per tool (`ATLAS_TOOL_LLM_RESULT_MAX_CHARS`).

**Demo tools:** auth `none`, local URLs — no passkey on tool endpoints.

---

## 7. Agents with no tools — latency

```python
if tool_ids and tool_calling_config.get("enabled"):
    # ... entire tool pipeline
```

Empty `tool_ids` → **no DeepSeek tool call, no Mongo tool load, no HTTP**. Only tiny in-memory config normalize. Final LLM latency unchanged.

---

## 8. Demo: customer inquiry

**Story:** email → lookup → if new `create_demo_lead` (Mongo write), if returning `get_demo_customer_summary` (read plan + tickets).

| Endpoint | Method | Atlas tool name |
|----------|--------|-----------------|
| `/demo/customer-inquiry/v1/customers/lookup` | POST | `lookup_demo_customer` |
| `/demo/customer-inquiry/v1/leads` | POST | `create_demo_lead` |
| `/demo/customer-inquiry/v1/customers/summary?customer_id=` | GET | `get_demo_customer_summary` |

**Admin (passkey only):** `/admin/seed`, `/admin/reset`

**Mongo collections:** `demo_customers`, `demo_tickets`, `demo_leads` — isolated from production `atlas_*` data.

**Seed:** upserts Sarah (`sarah@acme.com`) + 2 tickets; clears `demo_leads`.

Full tool copy-paste + scripts: `documentation/frontend-demo-customer-inquiry-api-guide.md`

---

## 9. Design choices worth remembering

| Choice | Reason |
|--------|--------|
| DeepSeek for tools, agent model for reply | Native function calling + compatibility with any final chat API |
| Plain-text tool results for final model | Avoids `tool` role / `tool_call_id` issues on Claude/Grok |
| `tool_calling_config` on agent | User-tunable chaining without code deploy |
| Partial config merge on update | Same UX as `lead_collection_config` |
| Demo routes open, seed/reset passkey | Easy tool registration; protect destructive setup |
| Indexes in `mongo_indexes.py` | Query paths for email, customer_id, ticket_id |

---

## 10. File map (quick lookup)

```
config/atlas_tool_calling_config.py     # defaults + validation
config/atlas_tool_config.py             # truncation caps, absolute max rounds
config/demo_customer_inquiry_*.py       # demo seed + request models

services/elysium_atlas_services/
  agent_chat_services.py                # chat pipeline + tool gate
  atlas_tool_execution_services.py      # multi-round loop + httpx
  atlas_tool_services.py                # CRUD + validate_agent_tool_ids

services/demo/demo_customer_inquiry_services.py

routes/demo/demo_customer_inquiry_routes.py
controllers/demo_controller_files/demo_customer_inquiry_controllers.py

documentation/frontend-tools-api-guide.md
documentation/frontend-demo-customer-inquiry-api-guide.md
```

---

## 11. One-line explanations (if you need to walk someone through it)

- **“How do custom tools work?”** — Team defines HTTP endpoints as OpenAI functions; agent attaches tool IDs; at chat time DeepSeek may call them; results feed the main model.
- **“How does chaining work?”** — Bounded loop: model calls tool A, sees result in context, may call tool B in the next round.
- **“Why no slowdown without tools?”** — Early `if tool_ids` guard skips the whole orchestration path.
- **“What did the demo prove?”** — Same agent branches on DB state: lookup → lead write vs account summary read.

---

*Last aligned with: multi-round `tool_calling_config`, demo customer-inquiry APIs, open demo tools + passkey seed/reset.*
