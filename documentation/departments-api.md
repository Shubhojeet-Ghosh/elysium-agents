# Departments API — Frontend Guide

How the frontend should create departments and list team users with department details.

For user registration and login, see [email-auth-login-api.md](./email-auth-login-api.md).

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

```
1. Create department(s)     →  POST /email-departments/v1/create  (needs team_id)
2. List team departments    →  POST /email-departments/v1/list-team-departments
3. Register users           →  POST /email-auth/v1/register  (needs department_id)
4. List team members        →  POST /email-auth/v1/list-team-users
```

Departments must exist **before** registering users. Each user is assigned a `department_id` at registration.

For **LLM email routing** (which department owns an inbound thread), create rules per department via [email-routing-rules-api.md](./email-routing-rules-api.md).

For **CC / BCC on AI replies** (when to add team members), see [email-recipient-rules-api.md](./email-recipient-rules-api.md).

---

## Data model (for reference)

### Collection: `email-departments`

```json
{
  "_id": "674a1b2c3d4e5f6789012345",
  "team_id": "team_123",
  "department_name": "Sales",
  "department_description": "Handles inbound sales inquiries",
  "created_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:00:00Z"
}
```

- **`_id`** is the department id — the API returns it as `department_id` (24-char hex string).

### Collection: `email-user-department-mapping`

Created automatically when a user registers. Maps which user belongs to which department.

```json
{
  "user_id": "674b2c3d4e5f6789012346",
  "department_id": "674a1b2c3d4e5f6789012345",
  "email": "jane@example.com",
  "name": "Jane Doe",
  "created_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:00:00Z"
}
```

---

## 1. Create Department

Creates a new department. Returns `department_id` — save this for user registration.

### Route

```
POST /elysium-agents/email-departments/v1/create
```

### Headers

```http
Content-Type: application/json
```

No `Authorization` header required (prototype).

### Request body

```json
{
  "name": "Sales",
  "description": "Handles inbound sales inquiries and quotes",
  "team_id": "team_123"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | Yes | Department name (min 1 char) |
| `description` | string | Yes | Department description (min 1 char) |
| `team_id` | string | Yes | Team this department belongs to |

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Department created successfully.",
  "department": {
    "department_id": "674a1b2c3d4e5f6789012345",
    "team_id": "team_123",
    "department_name": "Sales",
    "department_description": "Handles inbound sales inquiries and quotes",
    "created_at": "2026-06-06T10:00:00Z",
    "updated_at": "2026-06-06T10:00:00Z"
  }
}
```

**Frontend:** store `department.department_id` — pass it as `department_id` when registering users.

### Error — validation `422`

Invalid or missing fields (e.g. empty name):

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "name"],
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
  "message": "An error occurred while creating the department."
}
```

### Frontend example

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function createDepartment(name, description, teamId) {
  const res = await fetch(`${BASE}/email-departments/v1/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, team_id: teamId }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to create department");
  }

  return data.department; // includes department_id
}
```

---

## 2. List Team Departments

Returns all departments for a given `team_id` with name, description, and timestamps.

Use this to populate department dropdowns (e.g. thread assignment, user registration).

### Route

```
POST /elysium-agents/email-departments/v1/list-team-departments
```

### Headers

```http
Content-Type: application/json
```

No `Authorization` header required (prototype).

### Request body

```json
{
  "team_id": "team_123"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `team_id` | string | Yes | Team whose departments to list |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Team departments fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "departments": [
    {
      "department_id": "674a1b2c3d4e5f6789012345",
      "team_id": "team_123",
      "department_name": "Sales",
      "department_description": "Handles inbound sales inquiries and quotes",
      "created_at": "2026-06-06T10:00:00Z",
      "updated_at": "2026-06-06T10:00:00Z"
    },
    {
      "department_id": "674a1b2c3d4e5f6789012348",
      "team_id": "team_123",
      "department_name": "Support",
      "department_description": "Customer support and help desk",
      "created_at": "2026-06-06T11:00:00Z",
      "updated_at": "2026-06-06T11:00:00Z"
    }
  ]
}
```

Returns an empty `departments` array if the team has no departments yet.

### Frontend example

```javascript
async function listTeamDepartments(teamId) {
  const res = await fetch(`${BASE}/email-departments/v1/list-team-departments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId }),
  });

  const data = await res.json();
  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to fetch departments");
  }

  return data.departments;
}
```

---

## 3. List Team Users

Returns all users for a given `team_id`, with each user's department name and description.

Use this to build a **team members** or **admin dashboard** view.

### Route

```
POST /elysium-agents/email-auth/v1/list-team-users
```

### Headers

```http
Content-Type: application/json
```

### Request body

```json
{
  "team_id": "team_123"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `team_id` | string | Yes | Team identifier (min 1 char) |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Team users fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "users": [
    {
      "user_id": "674b2c3d4e5f6789012346",
      "name": "Jane Doe",
      "email": "jane@example.com",
      "team_id": "team_123",
      "department_id": "674a1b2c3d4e5f6789012345",
      "department_name": "Sales",
      "department_description": "Handles inbound sales inquiries and quotes",
      "created_at": "2026-06-06T10:00:00Z",
      "updated_at": "2026-06-06T10:00:00Z"
    },
    {
      "user_id": "674b2c3d4e5f6789012347",
      "name": "John Smith",
      "email": "john@example.com",
      "team_id": "team_123",
      "department_id": "674a1b2c3d4e5f6789012348",
      "department_name": "Support",
      "department_description": "Customer support and help desk",
      "created_at": "2026-06-06T11:00:00Z",
      "updated_at": "2026-06-06T11:00:00Z"
    }
  ]
}
```

| Response field | Description |
|----------------|-------------|
| `team_id` | The team you queried |
| `count` | Number of users returned |
| `users` | Array of user objects with department info |
| `user_id` | Mongo `_id` of the user (string) |
| `department_name` | From `email-departments` |
| `department_description` | From `email-departments` |

**Empty team:** if no users exist for that `team_id`, you still get `200` with `"count": 0` and `"users": []`.

Passwords are never included in the response.

### Error — server `500`

```json
{
  "success": false,
  "message": "An error occurred while fetching team users."
}
```

### Frontend example

```javascript
async function listTeamUsers(teamId) {
  const res = await fetch(`${BASE}/email-auth/v1/list-team-users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to fetch team users");
  }

  return data; // { team_id, count, users }
}

// Example: render a team table
const { users } = await listTeamUsers("team_123");
users.forEach((user) => {
  console.log(`${user.name} (${user.email}) — ${user.department_name}`);
});
```

---

## Full setup flow (departments + users)

```javascript
const BASE = "http://localhost:7000/elysium-agents";

const teamId = "team_123";

// 1. Create departments
const salesDept = await createDepartment("Sales", "Sales inquiries", teamId);
const supportDept = await createDepartment("Support", "Customer support", teamId);

// Optional: list all departments for the team
const departments = await listTeamDepartments(teamId);

// 2. Register users (see email-auth-login-api.md)
await fetch(`${BASE}/email-auth/v1/register`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Jane Doe",
    email: "jane@example.com",
    password: "securepass123",
    team_id: teamId,
    department_id: salesDept.department_id,
    role: "member",
  }),
});

// 3. List all users in the team with department info
const teamData = await listTeamUsers(teamId);
console.log(teamData.users);
```

---

## Quick reference

| API | Method | Path | Auth | Body |
|-----|--------|------|------|------|
| Create department | `POST` | `/elysium-agents/email-departments/v1/create` | No | `{ name, description, team_id }` |
| List team departments | `POST` | `/elysium-agents/email-departments/v1/list-team-departments` | No | `{ team_id }` |
| List team users | `POST` | `/elysium-agents/email-auth/v1/list-team-users` | No | `{ team_id }` |

| Collection | Purpose |
|------------|---------|
| `email-departments` | Department records per team (`_id` = `department_id`, `team_id`) |
| `email-users` | User accounts with `team_id` + `department_id` |
| `email-user-department-mapping` | User ↔ department mapping (auto on register) |
| `email-gmail_accounts` | Connected Gmail inboxes (see gmail-oauth-setup.md) |

---

## Related docs

- [email-auth-login-api.md](./email-auth-login-api.md) — register, login, JWT
- [gmail-oauth-setup.md](./gmail-oauth-setup.md) — Gmail connect (next phase)
