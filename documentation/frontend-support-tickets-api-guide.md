# Support Tickets APIs — frontend guide

Reference for building the **Elysium support tickets** UI. Users create tickets describing an issue; support staff update status and add replies via an internal passkey-protected route (Postman / admin tooling for now).

**Base path:** `/elysium-agents/elysium-atlas/support-tickets`

Customer-facing routes require `Authorization: Bearer <session_jwt>` with `user_id` and `team_id` (see [backend-team-rbac-guide.md](./backend-team-rbac-guide.md)).

---

## Overview

| Concept | Detail |
|---------|--------|
| Scope | Tickets belong to the active JWT **`team_id`** and are owned by **`created_by_user_id`** |
| Ticket ID | Mongo `_id`, returned as `ticket_id` in API responses |
| Ticket number | `TKT-{year}-{ticket_id}` — e.g. `TKT-2026-674a1b2c3d4e5f6789012345` |
| Storage | `atlas_support_tickets` collection |
| User identity | Taken from JWT — never send `user_id` in the request body |
| Admin updates | Internal route uses `X-Application-Passkey` header (not for frontend) |

---

## Ticket status values

| Status | Meaning | Typical use |
|--------|---------|-------------|
| `open` | New ticket, not yet picked up | Default when a user creates a ticket |
| `in_progress` | Support is actively working on it | Set by internal update |
| `waiting_on_customer` | Support needs more info from the user | Set by internal update |
| `resolved` | Issue fixed; awaiting confirmation | Set by internal update |
| `closed` | Ticket finished | Set by internal update |

The frontend should treat these as **read-only labels** on customer routes. Only the internal update API changes status.

---

## Roles (customer routes)

Any active **team member** (`owner`, `admin`, or `member`) can:

- Create a ticket
- List **their own** tickets (not other team members' tickets)
- Get full details for **their own** tickets

When JWT has **no `team_id`**, do not call ticket APIs — redirect to team selection first.

---

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/v1/create-ticket` | JWT | Create a new support ticket |
| `POST` | `/v1/list-my-tickets` | JWT | Paginated list of the logged-in user's tickets |
| `POST` | `/v1/get-ticket` | **None (public)** | Full ticket details by `ticket_number` |
| `POST` | `/v1/internal/update-ticket` | Passkey | **Internal only** — update status and/or add support comment |

All endpoints use **POST** with a JSON body (consistent with other Elysium Agents routes).

---

## 1. Create ticket

**`POST /elysium-agents/elysium-atlas/support-tickets/v1/create-ticket`**

### Headers

```
Authorization: Bearer <session_jwt>
Content-Type: application/json
```

### Request body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `subject` | `string` | Yes | Short title, max 200 chars |
| `description` | `string` | Yes | Full issue description, max 10,000 chars |

### Example request

```json
{
  "subject": "Agent not indexing my website",
  "description": "I added https://example.com/docs two hours ago but the URLs still show as pending. Agent ID is visible in my dashboard."
}
```

### Success response (`200`)

```json
{
  "success": true,
  "ticket": {
    "ticket_id": "674a1b2c3d4e5f6789012345",
    "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345",
    "team_id": "699e9bf195fcec2ed8ef6763",
    "created_by_user_id": "69568df774db787c7f93b86b",
    "subject": "Agent not indexing my website",
    "status": "open",
    "description": "I added https://example.com/docs two hours ago...",
    "comments": [],
    "created_at": "2026-06-15T10:30:00+00:00",
    "updated_at": "2026-06-15T10:30:00+00:00",
    "last_activity_at": "2026-06-15T10:30:00+00:00"
  }
}
```

### Error responses

| Status | When |
|--------|------|
| `401` | Missing or invalid JWT |
| `403` | No `team_id` in JWT, or user is not a team member |
| `422` | Validation error (empty subject/description, extra fields) |
| `500` | Unexpected server error |

---

## 2. List my tickets

**`POST /elysium-agents/elysium-atlas/support-tickets/v1/list-my-tickets`**

Returns only tickets where `created_by_user_id` matches the JWT user and `team_id` matches the active team.

### Request body

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `page` | `integer` | No | `1` | Min 1 |
| `limit` | `integer` | No | `20` | Min 1, max 100 |
| `status` | `string` | No | — | Filter by status (see status table above) |

### Example request

```json
{
  "page": 1,
  "limit": 20,
  "status": "open"
}
```

### Success response (`200`)

```json
{
  "success": true,
  "tickets": [
    {
      "ticket_id": "674a1b2c3d4e5f6789012345",
      "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345",
      "team_id": "699e9bf195fcec2ed8ef6763",
      "created_by_user_id": "69568df774db787c7f93b86b",
      "subject": "Agent not indexing my website",
      "status": "open",
      "created_at": "2026-06-15T10:30:00+00:00",
      "updated_at": "2026-06-15T10:30:00+00:00",
      "last_activity_at": "2026-06-15T10:30:00+00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20,
  "total_pages": 1,
  "has_next": false,
  "has_prev": false
}
```

List items omit `description` and `comments` — use **get-ticket** for the full view.

Sorted by **`last_activity_at` descending** (most recently updated first).

---

## 3. Get ticket details (public)

**`POST /elysium-agents/elysium-atlas/support-tickets/v1/get-ticket`**

No authentication required. Look up a ticket by **`ticket_number`** (e.g. `TKT-2026-674a1b2c3d4e5f6789012345`).

### Headers

```
Content-Type: application/json
```

### Request body

| Field | Type | Required |
|-------|------|----------|
| `ticket_number` | `string` | Yes |

### Example request

```json
{
  "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345"
}
```

### Success response (`200`)

Same shape as create response, including `description` and `comments`:

```json
{
  "success": true,
  "ticket": {
    "ticket_id": "674a1b2c3d4e5f6789012345",
    "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345",
    "team_id": "699e9bf195fcec2ed8ef6763",
    "created_by_user_id": "69568df774db787c7f93b86b",
    "subject": "Agent not indexing my website",
    "status": "in_progress",
    "description": "I added https://example.com/docs two hours ago...",
    "comments": [
      {
        "comment_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "body": "We are checking your crawl logs and will update you shortly.",
        "author_type": "support",
        "created_at": "2026-06-15T11:00:00+00:00"
      }
    ],
    "created_at": "2026-06-15T10:30:00+00:00",
    "updated_at": "2026-06-15T11:00:00+00:00",
    "last_activity_at": "2026-06-15T11:00:00+00:00"
  }
}
```

### Error responses

| Status | When |
|--------|------|
| `404` | Ticket not found (unknown `ticket_number`) |
| `422` | Validation error |
| `500` | Unexpected server error |

---

## 4. Internal update ticket (not for frontend)

**`POST /elysium-agents/elysium-atlas/support-tickets/v1/internal/update-ticket`**

For **Postman / superuser tooling only**. Requires the application passkey header — value from server env `APPLICATION_PASSKEY`.

### Headers

```
X-Application-Passkey: <APPLICATION_PASSKEY>
Content-Type: application/json
```

Also accepts header name `X_Application_Passkey`.

### Request body

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `ticket_id` | `string` | One of `ticket_id` or `ticket_number` | Mongo `_id` |
| `ticket_number` | `string` | One of `ticket_id` or `ticket_number` | e.g. `TKT-2026-674a1b2c3d4e5f6789012345` |
| `status` | `string` | At least one of `status` or `comment` | One of the status enum values |
| `comment` | `string` | At least one of `status` or `comment` | Support reply appended to ticket |

### Example — change status and add comment

```json
{
  "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345",
  "status": "in_progress",
  "comment": "We are checking your crawl logs and will update you shortly."
}
```

### Example — comment only

```json
{
  "ticket_id": "674a1b2c3d4e5f6789012345",
  "comment": "Please share the exact URL you tried to index."
}
```

Returns the full updated ticket (same shape as get-ticket).

---

## Frontend UI checklist

1. **Team selection** — Block ticket UI when JWT lacks `team_id`.
2. **Create form** — `subject` + `description`; show returned `ticket_number` after submit.
3. **My tickets list** — Call `list-my-tickets`; show `ticket_number`, `subject`, `status`, `last_activity_at`.
4. **Ticket detail page** — Call public `get-ticket` with `ticket_number` (no JWT); render description + support `comments` thread.
5. **Status badge** — Map status strings to colors (e.g. `open` = blue, `resolved` = green, `closed` = gray).
6. **Polling or refresh** — After support updates via internal tools, user refreshes detail view to see new comments/status (no websocket in v1).
7. **Do not expose** internal update route or passkey in the frontend.

---

## MongoDB document shape (reference)

Collection: **`atlas_support_tickets`**

```json
{
  "_id": "ObjectId",
  "ticket_number": "TKT-2026-674a1b2c3d4e5f6789012345",
  "team_id": "699e9bf195fcec2ed8ef6763",
  "created_by_user_id": "69568df774db787c7f93b86b",
  "subject": "Short title",
  "description": "Full issue text",
  "status": "open",
  "comments": [
    {
      "comment_id": "uuid",
      "body": "Support reply text",
      "author_type": "support",
      "created_at": "ISODate"
    }
  ],
  "created_at": "ISODate",
  "updated_at": "ISODate",
  "last_activity_at": "ISODate"
}
```

`ticket_number` is set at create time as `TKT-{year}-{ticket_id}` where `ticket_id` is the Mongo `_id` of the new ticket document. No counter collection.

---

## TypeScript types (optional)

```typescript
type TicketStatus =
  | "open"
  | "in_progress"
  | "waiting_on_customer"
  | "resolved"
  | "closed";

type SupportTicketComment = {
  comment_id: string;
  body: string;
  author_type: "support";
  created_at: string;
};

type SupportTicketSummary = {
  ticket_id: string;
  ticket_number: string;
  team_id: string;
  created_by_user_id: string;
  subject: string;
  status: TicketStatus;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
};

type SupportTicketDetail = SupportTicketSummary & {
  description: string;
  comments: SupportTicketComment[];
};
```
