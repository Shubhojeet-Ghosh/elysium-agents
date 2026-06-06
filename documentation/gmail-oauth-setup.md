# Gmail OAuth — Frontend-First Guide (Phase 1)

Connect a user's Gmail inbox to Elysium Agents. **OAuth UI runs entirely on the frontend.** The backend only receives the authorization `code` and saves the inbox.

**Storage:** MongoDB only. No Redis.

**Not in Phase 1:** reading emails, sending emails, push notifications.

---

## Overview

```
1. User logs in → JWT
2. On inbox-settings page → user clicks "Connect Gmail"
3. Frontend opens Google consent screen
4. Google redirects back to inbox-settings with ?code=...
5. Frontend saves code → user enters inbox name
6. Frontend POSTs code + inbox_name to backend
7. Backend exchanges code, saves email-gmail_accounts
```

---

## Google Cloud Console setup

**OAuth client type:** Web application

| Setting | Value (local dev) |
|---------|-------------------|
| **Authorized JavaScript origins** | `http://localhost:3000` |
| **Authorized redirect URIs** | `http://localhost:3000/email/inbox-settings` |

Also enable **Gmail API** on the project.

**Production:** add your production frontend origin + redirect URI.

---

## Backend `.env`

```env
GOOGLE_CLIENT_ID="your-client-id"
GOOGLE_CLIENT_SECRET="your-client-secret"
GOOGLE_REDIRECT_URI="http://localhost:3000/email/inbox-settings"
```

`GOOGLE_REDIRECT_URI` is the **frontend page** where Google redirects with `?code=...`. It must match Google Console **exactly**.

---

## Frontend: inbox-settings page

**Page URL:** `http://localhost:3000/email/inbox-settings`

### Step 1 — Build Google OAuth URL

When user clicks **Connect Gmail**, redirect or open:

```
https://accounts.google.com/o/oauth2/v2/auth
  ?client_id={GOOGLE_CLIENT_ID}
  &redirect_uri=http://localhost:3000/email/inbox-settings
  &response_type=code
  &scope=https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send openid email profile
  &access_type=offline
  &prompt=consent
  &state={random_string}
```

| Param | Required | Notes |
|-------|----------|-------|
| `client_id` | Yes | From Google Console (can be env var on frontend) |
| `redirect_uri` | Yes | Must match `GOOGLE_REDIRECT_URI` |
| `response_type` | Yes | Always `code` |
| `scope` | Yes | Gmail + openid scopes (see above) |
| `access_type` | Yes | `offline` — needed for **refresh_token** |
| `prompt` | Yes | `consent` — ensures refresh token on first connect |
| `state` | Recommended | CSRF protection; validate on return |

Use `encodeURIComponent` for `redirect_uri` and `scope` in the URL.

### Step 2 — Read `code` from query params

After consent, Google redirects to:

```
http://localhost:3000/email/inbox-settings?code=4/0A...&scope=...&state=...
```

On page load:

```javascript
const params = new URLSearchParams(window.location.search);
const code = params.get("code");
const error = params.get("error");

if (error) {
  // User denied access — show message
}

if (code) {
  sessionStorage.setItem("gmail_oauth_code", code);
  // Remove code from URL so refresh doesn't reuse it
  window.history.replaceState({}, "", "/email/inbox-settings");
}
```

**Important:** authorization `code` is **one-time use**. Don't reuse after calling the backend.

### Step 3 — User enters inbox name

Show an input e.g. `"Support Inbox"`, `"Sales Gmail"`.

### Step 4 — Call backend to create inbox

```javascript
const BASE = "http://localhost:7000/elysium-agents";
const token = localStorage.getItem("auth_token");
const code = sessionStorage.getItem("gmail_oauth_code");
const inboxName = "Support Inbox";

const res = await fetch(`${BASE}/email/gmail/v1/accounts`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  },
  body: JSON.stringify({
    inbox_name: inboxName,
    code: code,
  }),
});

const data = await res.json();

if (data.success) {
  sessionStorage.removeItem("gmail_oauth_code");
  // Show success, refresh inbox list
}
```

---

## Backend APIs

**Base path:** `/elysium-agents/email/gmail`

All endpoints require JWT: `Authorization: Bearer <token>`

---

### 1. Create Gmail inbox

```
POST /elysium-agents/email/gmail/v1/accounts
```

**Request:**
```json
{
  "inbox_name": "Support Inbox",
  "code": "authorization_code_from_google"
}
```

**Success — new inbox `201`:**
```json
{
  "success": true,
  "message": "Gmail inbox created successfully.",
  "account": {
    "account_id": "674a1b2c3d4e5f6789012345",
    "user_id": "674b2c3d4e5f6789012346",
    "team_id": "team_123",
    "inbox_name": "Support Inbox",
    "email_address": "user@gmail.com",
    "display_name": "Jane Doe",
    "status": "active",
    "created_at": "2026-06-06T10:00:00Z",
    "updated_at": "2026-06-06T10:00:00Z"
  }
}
```

`team_id` is taken from the JWT automatically (not sent in the request body).

**Success — same email reconnected `200`:**
Updates inbox name, refresh token, and status.

**Errors:**

| Status | Message |
|--------|---------|
| `400` | Invalid code, missing refresh token, or Google API failure |
| `401` | Missing or invalid JWT |
| `500` | Server error |

**Common `400`:** `"Google did not return a refresh token..."`  
→ Frontend must use `access_type=offline` and `prompt=consent`.

Tokens are **never** returned to the frontend.

---

### 2. List Gmail inboxes

```
GET /elysium-agents/email/gmail/v1/accounts
```

**Headers:**

```http
Authorization: Bearer <jwt>
```

Returns **all connected Gmail inboxes for the authenticated user's `team_id`**. Works for both `admin` and `member` roles (not limited to inboxes the current user connected).

**Success `200`:**
```json
{
  "success": true,
  "message": "Team Gmail accounts fetched successfully.",
  "team_id": "team_123",
  "count": 1,
  "accounts": [
    {
      "account_id": "674a1b2c3d4e5f6789012345",
      "user_id": "674b2c3d4e5f6789012346",
      "team_id": "team_123",
      "inbox_name": "Support Inbox",
      "email_address": "user@gmail.com",
      "display_name": "Jane Doe",
      "status": "active",
      "connected_at": "2026-06-06T10:00:00Z",
      "updated_at": "2026-06-06T10:00:00Z"
    }
  ]
}
```

---

### 3. List team Gmail inboxes

List **all** connected Gmail inboxes for everyone in a team. Use this for a team admin / inbox-settings overview.

```
POST /elysium-agents/email/gmail/v1/list-team-accounts
```

**No JWT required** (prototype — same pattern as list-team-users).

**Request:**
```json
{
  "team_id": "team_123"
}
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Team Gmail accounts fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "accounts": [
    {
      "account_id": "674a1b2c3d4e5f6789012345",
      "user_id": "674b2c3d4e5f6789012346",
      "team_id": "team_123",
      "inbox_name": "Support Inbox",
      "email_address": "support@gmail.com",
      "display_name": "Jane Doe",
      "status": "active",
      "connected_at": "2026-06-06T10:00:00Z",
      "updated_at": "2026-06-06T10:00:00Z"
    },
    {
      "account_id": "674a1b2c3d4e5f6789012348",
      "user_id": "674b2c3d4e5f6789012347",
      "team_id": "team_123",
      "inbox_name": "Sales Inbox",
      "email_address": "sales@gmail.com",
      "display_name": "John Smith",
      "status": "active",
      "connected_at": "2026-06-06T11:00:00Z",
      "updated_at": "2026-06-06T11:00:00Z"
    }
  ]
}
```

Returns `"count": 0` and `"accounts": []` if no inboxes exist for that team.

**Frontend example:**
```javascript
const res = await fetch(`${BASE}/email/gmail/v1/list-team-accounts`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ team_id: "team_123" }),
});
const data = await res.json();
// data.accounts → all team Gmail inboxes
```

---

### 4. Disconnect Gmail inbox

```
DELETE /elysium-agents/email/gmail/v1/accounts/{account_id}
```

**Success `200`:**
```json
{
  "success": true,
  "message": "Gmail account disconnected.",
  "account_id": "674a1b2c3d4e5f6789012345"
}
```

---

## MongoDB collection: `email-gmail_accounts`

One document = one Gmail inbox linked to one user.

```json
{
  "_id": "ObjectId",
  "user_id": "from JWT",
  "team_id": "from JWT",
  "inbox_name": "Support Inbox",
  "provider": "gmail",
  "email_address": "user@gmail.com",
  "google_subject_id": "google_user_id",
  "display_name": "John Doe",
  "scopes": ["gmail.readonly", "gmail.send", "openid", "email", "profile"],
  "refresh_token": "stored_plain_mvp",
  "status": "active",
  "last_token_refresh_at": "2026-06-06T10:00:00Z",
  "last_error": null,
  "created_at": "2026-06-06T10:00:00Z",
  "updated_at": "2026-06-06T10:00:00Z"
}
```

| Field | Notes |
|-------|-------|
| `_id` | Returned as `account_id` in API |
| `team_id` | Team that owns this inbox (from JWT at connect time) |
| `inbox_name` | User-chosen label from frontend |
| `refresh_token` | MVP: stored plain in Mongo; never exposed via API |
| `status` | `active` or `revoked` |

**Unique rule:** one Gmail email per user (`user_id` + `email_address`).

---

## OAuth scopes

| Scope | Purpose |
|-------|---------|
| `gmail.readonly` | Read mail (Phase 2+) |
| `gmail.send` | Send replies (later) |
| `openid` `email` `profile` | User identity |

---

## Frontend checklist

- [ ] Login first → store JWT
- [ ] Build Google OAuth URL with correct `redirect_uri` and scopes
- [ ] Use `access_type=offline` + `prompt=consent`
- [ ] On inbox-settings load, read `code` from query params
- [ ] Save `code` to `sessionStorage`, clean URL with `replaceState`
- [ ] Collect `inbox_name` from user
- [ ] `POST /email/gmail/v1/accounts` with JWT + `code` + `inbox_name`
- [ ] Clear `gmail_oauth_code` from sessionStorage on success
- [ ] `GET /email/gmail/v1/accounts` to show current user's inboxes
- [ ] `POST /email/gmail/v1/list-team-accounts` to show all team inboxes

---

## Quick reference

| API | Method | Path | Auth |
|-----|--------|------|------|
| Create inbox | `POST` | `/elysium-agents/email/gmail/v1/accounts` | JWT |
| List team inboxes (JWT) | `GET` | `/elysium-agents/email/gmail/v1/accounts` | JWT |
| List team inboxes | `POST` | `/elysium-agents/email/gmail/v1/list-team-accounts` | No |
| Disconnect | `DELETE` | `/elysium-agents/email/gmail/v1/accounts/{account_id}` | JWT |

---

## Related docs

- [email-auth-login-api.md](./email-auth-login-api.md) — login & JWT
- [departments-api.md](./departments-api.md) — departments & team users

---

## Next phase (preview)

Phase 2 uses `refresh_token` from `email-gmail_accounts` to poll or watch for new emails.
