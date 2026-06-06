# Email Auth & Departments — Frontend Guide

How the frontend should use department creation, user registration, login, and the JWT.

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

## Recommended flow

```
1. Create department(s)  →  POST /email-departments/v1/create
2. Register user(s)      →  POST /email-auth/v1/register  (needs department_id)
3. Login                   →  POST /email-auth/v1/login
4. Use JWT on protected APIs →  Authorization: Bearer <token>
```

---

## 1. Create Department

### Route

```
POST /elysium-agents/email-departments/v1/create
```

### Headers

```http
Content-Type: application/json
```

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
| `name` | string | Yes | Department name |
| `description` | string | Yes | Department description |

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

**Save `department_id`** — this is the MongoDB `_id` of the department document (24-char hex string). Required when registering users.

### Error — `500`

```json
{
  "success": false,
  "message": "An error occurred while creating the department."
}
```

---

## 2. Register User

Create a user, or update an existing user (same email) with new name, password, department, or role.

### Route

```
POST /elysium-agents/email-auth/v1/register
```

### Request body

```json
{
  "name": "Jane Doe",
  "email": "jane@example.com",
  "password": "yourpassword",
  "team_id": "team_123",
  "department_id": "674a1b2c3d4e5f6789012345",
  "role": "admin"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `name` | string | Yes | User's full name |
| `email` | string | Yes | Valid email |
| `password` | string | Yes | Min 8 characters |
| `team_id` | string | Yes | User's team |
| `department_id` | string | Yes | Mongo `_id` from `email-departments` (must exist) |
| `role` | string | Yes | User role. Must be `"admin"` or `"member"`. |

**Note:** Users created before `role` was introduced are backfilled to `role: "admin"` automatically on server startup.

### Success — new user `201`

```json
{
  "success": true,
  "message": "User created successfully.",
  "user": {
    "user_id": "674b2c3d4e5f6789012346",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "team_id": "team_123",
    "department_id": "674a1b2c3d4e5f6789012345",
    "department_name": "Sales",
    "role": "admin",
    "created_at": "2026-06-06T10:00:00Z",
    "updated_at": "2026-06-06T10:00:00Z"
  }
}
```

### Success — existing email `200`

Updates name, password, department, role, and user–department mapping.

```json
{
  "success": true,
  "message": "User updated successfully.",
  "user": { "...": "..." }
}
```

### Error — invalid department `400`

```json
{
  "success": false,
  "message": "Invalid department_id. Department does not exist."
}
```

---

## 3. Login

### Route

```
POST /elysium-agents/email-auth/v1/login
```

### Headers

```http
Content-Type: application/json
```

### Request body

```json
{
  "email": "jane@example.com",
  "password": "yourpassword"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `email` | string | Yes | Valid email |
| `password` | string | Yes | Min 1 character |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Login successful.",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "user_id": "674b2c3d4e5f6789012346",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "team_id": "team_123",
    "department_id": "674a1b2c3d4e5f6789012345",
    "department_name": "Sales",
    "role": "admin"
  },
  "decoded_token": {
    "success": true,
    "message": "Token is valid",
    "user_id": "674b2c3d4e5f6789012346",
    "name": "Jane Doe",
    "email": "jane@example.com",
    "team_id": "team_123",
    "department_id": "674a1b2c3d4e5f6789012345",
    "department_name": "Sales",
    "role": "admin",
    "exp": 1750000000,
    "iat": 1747408000
  }
}
```

**Token expiry:** 30 days.

Store `user.role` from the login response (or read `role` from the JWT) for frontend authorization checks.

**JWT claims:**

| Claim | Description |
|-------|-------------|
| `user_id` | User ID (Mongo `_id` as string) |
| `name` | Full name |
| `email` | Email |
| `team_id` | Team ID |
| `department_id` | Department ID |
| `department_name` | Department name |
| `role` | User role (`"admin"` or `"member"`) |
| `iat` | Issued at (Unix timestamp) |
| `exp` | Expires at (Unix timestamp) |

### Error — wrong credentials `401`

```json
{
  "success": false,
  "message": "Invalid email or password."
}
```

---

## Using the token

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Store `token` after login (`localStorage` is fine for prototype). Remove on logout. Redirect to login on `401`.

---

## Frontend example (full flow)

```javascript
const BASE = "http://localhost:7000/elysium-agents";

// Step 1: Create department
const deptRes = await fetch(`${BASE}/email-departments/v1/create`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Sales",
    description: "Sales team",
    team_id: "team_123",
  }),
});
const { department } = await deptRes.json();

// Step 2: Register user
await fetch(`${BASE}/email-auth/v1/register`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Jane Doe",
    email: "jane@example.com",
    password: "securepass123",
    team_id: "team_123",
    department_id: department.department_id,
    role: "admin",
  }),
});

// Step 3: Login
const loginRes = await fetch(`${BASE}/email-auth/v1/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    email: "jane@example.com",
    password: "securepass123",
  }),
});
const loginData = await loginRes.json();
localStorage.setItem("auth_token", loginData.token);
localStorage.setItem("user", JSON.stringify(loginData.user));
```

---

## 4. List Team Users

List all users belonging to a `team_id`, including department name and description.

### Route

```
POST /elysium-agents/email-auth/v1/list-team-users
```

### Request body

```json
{
  "team_id": "team_123"
}
```

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
    }
  ]
}
```

Returns an empty `users` array if no users exist for that team.

---

## Quick reference

| API | Method | Path |
|-----|--------|------|
| Create department | `POST` | `/elysium-agents/email-departments/v1/create` |
| Register user | `POST` | `/elysium-agents/email-auth/v1/register` |
| Login | `POST` | `/elysium-agents/email-auth/v1/login` |
| List team users | `POST` | `/elysium-agents/email-auth/v1/list-team-users` |

| Collection | Purpose |
|------------|---------|
| `email-departments` | Department name + description (`_id` is the department id) |
| `email-users` | User account (`_id` is the user id, hashed password, `role`) |
| `email-user-department-mapping` | Which user belongs to which department |
| `email-gmail_accounts` | Connected Gmail inboxes (see gmail-oauth-setup.md) |
