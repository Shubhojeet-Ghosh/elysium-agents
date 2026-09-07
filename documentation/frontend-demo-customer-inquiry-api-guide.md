# Demo customer inquiry — tool definitions, setup, and demo scripts

Reference for the **customer inquiry demo**: lookup by email → create lead (new) or account summary (returning). These HTTP endpoints are registered as **Atlas custom tools** on your demo agent.

**Base path:** `/elysium-agents/demo/customer-inquiry/v1`

**Auth:** Tool endpoints are **open** (no passkey). Register each Atlas tool with `auth: { "type": "none" }`. Only `/admin/seed` and `/admin/reset` require header `X-Application-Passkey: <APPLICATION_PASSKEY>`.

---

## Quick start (before each demo)

1. **Seed** returning customer + tickets (clears demo leads):

```http
POST /elysium-agents/demo/customer-inquiry/v1/admin/seed
X-Application-Passkey: <APPLICATION_PASSKEY>
```

1. **Create three tools** in the Atlas tools UI (copy from [Tool definitions](#register-the-three-tools-on-your-agent) below).
2. **Attach tools** to your demo agent + set `tool_calling_config` (`max_rounds: 5`, etc.) — see [frontend-tools-api-guide.md](./frontend-tools-api-guide.md).
3. **System prompt** on the agent — see [Suggested system prompt](#suggested-system-prompt).

**Returning customer email (seeded):** `sarah@acme.com`  
**New lead demo email:** any other address, e.g. `john@newco.com`

---

## Endpoints

### Tool endpoints (register on agent — no auth)

| Method | Path                 | Tool name                   | Auth |
| ------ | -------------------- | --------------------------- | ---- |
| `POST` | `/customers/lookup`  | `lookup_demo_customer`      | None |
| `POST` | `/leads`             | `create_demo_lead`          | None |
| `GET`  | `/customers/summary` | `get_demo_customer_summary` | None |

### Admin endpoints (not LLM tools)

| Method | Path              | Auth                 | Purpose                                         |
| ------ | ----------------- | -------------------- | ----------------------------------------------- |
| `POST` | `/admin/seed`     | **Passkey required** | Upsert Sarah + tickets; delete all `demo_leads` |
| `POST` | `/admin/reset`    | **Passkey required** | Delete all demo customers, tickets, and leads   |
| `GET`  | `/admin/scenario` | None                 | JSON demo scripts + expected tool flows         |

---

## Mongo collections

| Collection       | Purpose                                         |
| ---------------- | ----------------------------------------------- |
| `demo_customers` | Returning customers (seed includes Sarah)       |
| `demo_tickets`   | Open support tickets linked by `customer_id`    |
| `demo_leads`     | Leads created by `create_demo_lead` during chat |

---

## API responses

### `POST /customers/lookup`

**Request:**

```json
{ "email": "sarah@acme.com" }
```

**Returning customer:**

```json
{
  "success": true,
  "found": true,
  "customer_id": "cust_sarah_acme",
  "name": "Sarah Chen",
  "company": "Acme Corp",
  "email": "sarah@acme.com",
  "plan": "enterprise"
}
```

**Unknown email:**

```json
{
  "success": true,
  "found": false,
  "email": "john@newco.com"
}
```

### `GET /customers/summary?customer_id=cust_sarah_acme`

```json
{
  "success": true,
  "customer_id": "cust_sarah_acme",
  "name": "Sarah Chen",
  "company": "Acme Corp",
  "email": "sarah@acme.com",
  "plan": "enterprise",
  "member_since": "2023-06-01",
  "account_manager": "Alex Rivera",
  "open_tickets_count": 2,
  "open_tickets": [
    {
      "ticket_id": "TKT-1042",
      "subject": "Billing discrepancy on March invoice",
      "status": "open",
      "priority": "high"
    },
    {
      "ticket_id": "TKT-1038",
      "subject": "SSO configuration for Acme Corp",
      "status": "open",
      "priority": "medium"
    }
  ],
  "suggestions": [
    "Your highest-priority open item is TKT-1042 (Billing discrepancy on March invoice) — reply on that ticket or contact Alex Rivera.",
    "If your question is about billing, focus on TKT-1042 (Billing discrepancy on March invoice).",
    "For SSO setup, track progress on TKT-1038 (SSO configuration for Acme Corp).",
    "Enterprise plans include priority support; mention your ticket ID if you need expedited review."
  ]
}
```

### `POST /leads`

**Request:**

```json
{
  "email": "john@newco.com",
  "name": "John",
  "company": "NewCo",
  "interest": "Enterprise pricing for 35-person team"
}
```

Only `email` is required.

**Response:**

```json
{
  "success": true,
  "lead_id": "lead_a1b2c3d4e5f6",
  "status": "new",
  "email": "john@newco.com",
  "name": "John",
  "company": "NewCo",
  "interest": "Enterprise pricing for 35-person team",
  "message": "Lead captured for sales follow-up.",
  "duplicate": false
}
```

---

## Register the three tools on your agent

Replace `{BASE_URL}` with your API origin, e.g. `http://localhost:8000/elysium-agents/demo/customer-inquiry/v1`.

### Tool auth for atlas_tools

For all three demo tools, set auth to `none` (default):

```json
{ "type": "none" }
```

No passkey or API key is sent when the agent executes these tools.

---

### 1. `lookup_demo_customer`

| Field          | Value                                                                                                                                                                                                                                                                                                      |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`         | `lookup_demo_customer`                                                                                                                                                                                                                                                                                     |
| `display_name` | Lookup demo customer                                                                                                                                                                                                                                                                                       |
| `description`  | Look up a demo customer by work email. Call this first when you have an email. Returns `found`, and when true includes `customer_id`, `name`, `company`, and `plan`. When `found` is false, use `create_demo_lead`. When `found` is true, use `get_demo_customer_summary` with the returned `customer_id`. |
| `api_url`      | `{BASE_URL}/customers/lookup`                                                                                                                                                                                                                                                                              |
| `http_method`  | `POST`                                                                                                                                                                                                                                                                                                     |

**Parameters:**

| name    | type   | required | description                |
| ------- | ------ | -------- | -------------------------- |
| `email` | string | yes      | Visitor work email address |

---

### 2. `create_demo_lead`

| Field          | Value                                                                                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`         | `create_demo_lead`                                                                                                                                                      |
| `display_name` | Create demo lead                                                                                                                                                        |
| `description`  | Create a sales lead when `lookup_demo_customer` returned `found: false`. Requires email. Optionally include name, company, and interest gathered from the conversation. |
| `api_url`      | `{BASE_URL}/leads`                                                                                                                                                      |
| `http_method`  | `POST`                                                                                                                                                                  |

**Parameters:**

| name       | type   | required | description                                       |
| ---------- | ------ | -------- | ------------------------------------------------- |
| `email`    | string | yes      | Visitor work email                                |
| `name`     | string | no       | Visitor name if known                             |
| `company`  | string | no       | Company name if known                             |
| `interest` | string | no       | What they are interested in (pricing, demo, etc.) |

---

### 3. `get_demo_customer_summary`

| Field          | Value                                                                                                                                                                                                                                  |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`         | `get_demo_customer_summary`                                                                                                                                                                                                            |
| `display_name` | Get demo customer summary                                                                                                                                                                                                              |
| `description`  | Get account summary for a returning demo customer. Use only after `lookup_demo_customer` returned `found: true`. Requires `customer_id` from the lookup result. Returns plan, open tickets, account manager, and suggested next steps. |
| `api_url`      | `{BASE_URL}/customers/summary`                                                                                                                                                                                                         |
| `http_method`  | `GET`                                                                                                                                                                                                                                  |

**Parameters:**

| name          | type   | required | description                             |
| ------------- | ------ | -------- | --------------------------------------- |
| `customer_id` | string | yes      | `customer_id` from lookup_demo_customer |

---

## Suggested system prompt

```
You are a demo sales and support assistant.

Before calling tools, if you do not have the visitor's work email, ask for it once in a friendly way.

When you have an email:
1. Call lookup_demo_customer first.
2. If found is false → call create_demo_lead with email and any name, company, or interest from the chat.
3. If found is true → call get_demo_customer_summary with the customer_id from lookup.

When responding:
- New leads: confirm their interest was registered, mention the lead reference if provided, and set expectations for follow-up within 1 business day.
- Returning customers: welcome them by name, summarize plan and open tickets from tool results, and include suggested next steps from the tool output. Do not invent account data.

Keep answers concise, warm, and formatted in Markdown.
```

---

## Demo paths (visitor questions → agent answers)

### Path 1 — Returning customer (`sarah@acme.com`)

**Visitor:**

> Hi, I'm Sarah — [sarah@acme.com](mailto:sarah@acme.com). Can you tell me what's going on with my account?

**Tools:** `lookup_demo_customer` → `get_demo_customer_summary`

**Agent (example):**

> Welcome back, **Sarah** — I found your **Acme Corp** account.
>
> **Your account**
>
> - **Plan:** Enterprise (member since June 2023)
> - **Account manager:** Alex Rivera
>
> **Open support items (2)**
>
> 1. **TKT-1042** — Billing discrepancy on March invoice _(high)_
> 2. **TKT-1038** — SSO configuration for Acme Corp _(medium)_
>
> **Suggested next steps**
>
> - For **billing**, focus on **TKT-1042** or contact Alex.
> - For **SSO**, track **TKT-1038**.
>
> What would you like to tackle first?

**Show in demo:** Mongo `demo_customers` / `demo_tickets` (read path).

---

### Path 2 — New lead (`john@newco.com`)

**Visitor:**

> We're a 35-person team looking at enterprise pricing.

**Agent:** asks for work email.

**Visitor:**

> [john@newco.com](mailto:john@newco.com)

**Tools:** `lookup_demo_customer` → `create_demo_lead`

**Agent (example):**

> Thanks — I don't have **[john@newco.com](mailto:john@newco.com)** in our system yet, so I've **registered your interest** (reference: **lead\_…**).
>
> A specialist will follow up within **1 business day** about **enterprise pricing** for your team.
>
> Anything specific you'd like covered — security, integrations, or billing?

**Show in demo:** new document in Mongo `demo_leads` (write path).

---

## Agent config reminder

```json
{
  "tool_ids": ["<tool_id_1>", "<tool_id_2>", "<tool_id_3>"],
  "tool_calling_config": {
    "enabled": true,
    "max_rounds": 5,
    "max_executions_per_turn": 10,
    "parallel_calls_per_round": true
  }
}
```

---

## Related docs

- [frontend-tools-api-guide.md](./frontend-tools-api-guide.md) — tools CRUD, `tool_calling_config`, runtime orchestration
- [frontend-agent-create-update-api-guide.md](./frontend-agent-create-update-api-guide.md) — attach `tool_ids` on create/update
