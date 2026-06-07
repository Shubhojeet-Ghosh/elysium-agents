# Email Tools API — Agent Tool Guide

Built-in tool **execution** APIs the email AI agent can call during conversations:

- **Get ticket status** — look up a ticket by number
- **Create ticket** — raise a new open ticket (auto-generated number)
- **List tickets** — return all tickets (MVP, no pagination)

To **register** external tools for the LLM (endpoint, method, inputs, description), see [email-tool-definitions-api.md](./email-tool-definitions-api.md).

Ticket data is stored in `constants/email_ticket_status.json`. Replace with a real ticketing system when you move to production.

For knowledge indexing (Qdrant), see [email-knowledge-api.md](./email-knowledge-api.md).  
For email agent setup, see [email-ai-agent-setup.md](./email-ai-agent-setup.md).

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

| Action                  | API                                      | When                                                |
| ----------------------- | ---------------------------------------- | --------------------------------------------------- |
| **Check ticket status** | `POST /email-tools/v1/get-ticket-status` | Customer provides a ticket number (e.g. `TKT-1001`) |
| **Create ticket**       | `GET /email-tools/v1/create-ticket`      | Customer wants to raise a new support ticket        |
| **List all tickets**    | `GET /email-tools/v1/list-tickets`       | Admin UI or testing — show every ticket             |

No `Authorization` header required (prototype).

---

## Ticket object (API response shape)

Every ticket returned by the APIs uses this shape:

```json
{
  "ticket_number": "TKT-1001",
  "status": "in_progress",
  "remarks": "Our support team is reviewing your refund request...",
  "expected_resolution_due_date": "2026-06-15",
  "created_at": "2026-06-01T10:00:00+00:00"
}
```

| Field                          | Type   | Description                                               |
| ------------------------------ | ------ | --------------------------------------------------------- |
| `ticket_number`                | string | Unique ticket reference (e.g. `TKT-1001`)                 |
| `status`                       | string | `open`, `in_progress`, or `resolved`                      |
| `remarks`                      | string | Human-readable update the agent can relay to the customer |
| `expected_resolution_due_date` | string | Target resolution date (`YYYY-MM-DD`)                     |
| `created_at`                   | string | When the ticket was created (ISO 8601 UTC)                |

---

## Data source

### File: `constants/email_ticket_status.json`

Tickets are keyed by **ticket number**. Lookup normalizes to uppercase (`tkt-1001` → `TKT-1001`).

```json
{
  "tickets": {
    "TKT-1001": {
      "status": "in_progress",
      "remarks": "Our support team is reviewing your refund request. You will receive an update within 2 business days.",
      "expected_resolution_due_date": "2026-06-15",
      "created_at": "2026-06-01T10:00:00+00:00"
    },
    "TKT-1002": {
      "status": "resolved",
      "remarks": "Your replacement order has been shipped. Tracking number was sent to your inbox.",
      "expected_resolution_due_date": "2026-06-10",
      "created_at": "2026-06-03T14:30:00+00:00"
    },
    "TKT-1003": {
      "status": "open",
      "remarks": "Ticket received. A support agent will be assigned shortly.",
      "expected_resolution_due_date": "2026-06-20",
      "created_at": "2026-06-05T09:15:00+00:00"
    }
  }
}
```

**To add a ticket:** call `GET /v1/create-ticket`, or edit the JSON manually under `tickets` keyed by ticket number. No server restart needed — the file is read on each request.

---

## 1. Get Ticket Status

Look up a ticket by its number.

### Route

```
POST /elysium-agents/email-tools/v1/get-ticket-status
```

### Headers

```http
Content-Type: application/json
```

### Request body

```json
{
  "ticket_number": "TKT-1001"
}
```

| Field           | Type   | Required | Rules                                        |
| --------------- | ------ | -------- | -------------------------------------------- |
| `ticket_number` | string | Yes      | Ticket reference; matched case-insensitively |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Ticket status fetched successfully.",
  "ticket": {
    "ticket_number": "TKT-1001",
    "status": "in_progress",
    "remarks": "Our support team is reviewing your refund request. You will receive an update within 2 business days.",
    "expected_resolution_due_date": "2026-06-15",
    "created_at": "2026-06-01T10:00:00+00:00"
  }
}
```

### Error — not found `404`

```json
{
  "success": false,
  "message": "No ticket found for this ticket number."
}
```

### Error — validation `422`

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "ticket_number"],
      "msg": "String should have at least 1 character",
      "input": ""
    }
  ]
}
```

### Error — server `500`

```json
{
  "success": false,
  "message": "An error occurred while fetching ticket status."
}
```

### Example

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function getTicketStatus(ticketNumber) {
  const res = await fetch(`${BASE}/email-tools/v1/get-ticket-status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket_number: ticketNumber }),
  });

  const data = await res.json();

  if (res.status === 404) return null;

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to fetch ticket status");
  }

  return data.ticket;
}
```

---

## 2. Create Ticket

Creates a new ticket in `constants/email_ticket_status.json`. No request body or parameters.

### Auto-generated values

| Field                          | Value                                                                                                 |
| ------------------------------ | ----------------------------------------------------------------------------------------------------- |
| `ticket_number`                | Next available `TKT-XXXX` (increments from highest existing number)                                   |
| `status`                       | `open`                                                                                                |
| `remarks`                      | `"Your support ticket has been created. A team member will review your request and respond shortly."` |
| `expected_resolution_due_date` | 7 days from today (`YYYY-MM-DD`)                                                                      |
| `created_at`                   | Current UTC timestamp (ISO 8601)                                                                      |

### Route

```
GET /elysium-agents/email-tools/v1/create-ticket
```

No headers or body required.

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Ticket created successfully.",
  "ticket_number": "TKT-1004",
  "status": "open",
  "expected_resolution_due_date": "2026-06-14",
  "created_at": "2026-06-07T10:30:00+00:00"
}
```

`remarks` is stored in the JSON file but not included in the create response. Look up the full ticket via `get-ticket-status` or `list-tickets` to read it.

### Error — server `500`

```json
{
  "success": false,
  "message": "An error occurred while creating the ticket."
}
```

### Example

```javascript
async function createTicket() {
  const res = await fetch(`${BASE}/email-tools/v1/create-ticket`, {
    method: "GET",
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to create ticket");
  }

  return data;
}
```

---

## 3. List All Tickets

Returns every ticket from `constants/email_ticket_status.json`. No pagination (MVP). Sorted by `created_at` descending (newest first).

### Route

```
GET /elysium-agents/email-tools/v1/list-tickets
```

No headers, body, or parameters required.

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Tickets fetched successfully.",
  "count": 3,
  "tickets": [
    {
      "ticket_number": "TKT-1003",
      "status": "open",
      "remarks": "Ticket received. A support agent will be assigned shortly.",
      "expected_resolution_due_date": "2026-06-20",
      "created_at": "2026-06-05T09:15:00+00:00"
    },
    {
      "ticket_number": "TKT-1002",
      "status": "resolved",
      "remarks": "Your replacement order has been shipped. Tracking number was sent to your inbox.",
      "expected_resolution_due_date": "2026-06-10",
      "created_at": "2026-06-03T14:30:00+00:00"
    },
    {
      "ticket_number": "TKT-1001",
      "status": "in_progress",
      "remarks": "Our support team is reviewing your refund request. You will receive an update within 2 business days.",
      "expected_resolution_due_date": "2026-06-15",
      "created_at": "2026-06-01T10:00:00+00:00"
    }
  ]
}
```

### Error — server `500`

```json
{
  "success": false,
  "message": "An error occurred while listing tickets."
}
```

### Example

```javascript
async function listTickets() {
  const res = await fetch(`${BASE}/email-tools/v1/list-tickets`, {
    method: "GET",
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to list tickets");
  }

  return data.tickets;
}
```

---

## Full test flow

```javascript
const BASE = "http://localhost:7000/elysium-agents";

// 1. List existing tickets
const listRes = await fetch(`${BASE}/email-tools/v1/list-tickets`);
const { tickets } = await listRes.json();
console.log(`Found ${tickets.length} tickets`);

// 2. Create a new ticket
const createRes = await fetch(`${BASE}/email-tools/v1/create-ticket`);
const newTicket = await createRes.json();
console.log(
  `Created ${newTicket.ticket_number}, due ${newTicket.expected_resolution_due_date}`,
);

// 3. Look up the new ticket by number
const statusRes = await fetch(`${BASE}/email-tools/v1/get-ticket-status`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ ticket_number: newTicket.ticket_number }),
});
const { ticket } = await statusRes.json();
console.log(ticket.status, ticket.remarks);
```

---

## Agent tool registration (future)

When wiring these into the email AI agent's tool-calling loop:

| Tool name           | Description              | Endpoint                                 | Input               | Output                                                                  |
| ------------------- | ------------------------ | ---------------------------------------- | ------------------- | ----------------------------------------------------------------------- |
| `get_ticket_status` | Look up ticket by number | `POST /email-tools/v1/get-ticket-status` | `{ ticket_number }` | Full ticket object                                                      |
| `create_ticket`     | Raise a new open ticket  | `GET /email-tools/v1/create-ticket`      | None                | `ticket_number`, `status`, `expected_resolution_due_date`, `created_at` |
| `list_tickets`      | List all tickets         | `GET /email-tools/v1/list-tickets`       | None                | `count`, `tickets[]`                                                    |

**Status check flow:**

```
Customer: "What's the status of ticket TKT-1001?"
    ↓
Agent extracts ticket number  →  TKT-1001
    ↓
POST /v1/get-ticket-status  { ticket_number: "TKT-1001" }
    ↓
Agent drafts reply using status, remarks, expected_resolution_due_date
```

**Create ticket flow:**

```
Customer: "I'd like to raise a support ticket."
    ↓
GET /v1/create-ticket
    ↓
Agent replies with ticket_number, status, expected_resolution_due_date, created_at
```

---

## Sample ticket numbers for testing

| Ticket number | Status        | Created    |
| ------------- | ------------- | ---------- |
| `TKT-1001`    | `in_progress` | 2026-06-01 |
| `TKT-1002`    | `resolved`    | 2026-06-03 |
| `TKT-1003`    | `open`        | 2026-06-05 |

Any other ticket number returns `404 — No ticket found for this ticket number.`  
Call `GET /v1/create-ticket` to generate `TKT-1004` and above.

---

## Code layout (for developers)

```
constants/
└── email_ticket_status.json              # ticket storage (JSON file)

services/email_agent_services/email_tools/
├── email_tools_constants.py              # paths, defaults (status, remarks, 7-day due date)
└── ticket_status_services.py             # create, list, lookup by ticket number

routes/email_agent/email_tools_routes.py
config/email_tools_models.py
controllers/email_agent_controller_files/email_tools_controllers.py
```

---

## Quick reference

| API               | Method | Path                                               | Auth | Input               |
| ----------------- | ------ | -------------------------------------------------- | ---- | ------------------- |
| Get ticket status | `POST` | `/elysium-agents/email-tools/v1/get-ticket-status` | No   | `{ ticket_number }` |
| Create ticket     | `GET`  | `/elysium-agents/email-tools/v1/create-ticket`     | No   | None                |
| List all tickets  | `GET`  | `/elysium-agents/email-tools/v1/list-tickets`      | No   | None                |

| Storage                              | Purpose                                |
| ------------------------------------ | -------------------------------------- |
| `constants/email_ticket_status.json` | All ticket records keyed by `TKT-XXXX` |

---

## Related docs

- [email-tool-definitions-api.md](./email-tool-definitions-api.md) — register tools in Mongo `email-tools` for LLM
- [email-knowledge-api.md](./email-knowledge-api.md) — team knowledge indexing in Qdrant
- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — Gmail agents and thread sync
- [departments-api.md](./departments-api.md) — team departments
