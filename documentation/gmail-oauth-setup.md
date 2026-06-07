# Gmail OAuth — Frontend-First Guide (Phase 1)

Connect a user's Gmail inbox to Elysium Agents. **OAuth UI runs entirely on the frontend.** The backend only receives the authorization `code` and saves the inbox.

**Storage:** MongoDB only. No Redis.

**Backend uses the inbox for:** sync/read mail (`gmail.readonly`), **save AI reply drafts** (`gmail.compose`), and **send replies** when auto-send is enabled (`gmail.send`).

**Frontend rule:** on **every** Connect / Reconnect, request **all three** Gmail scopes in one OAuth URL. Do not request only `readonly` + `compose` — users would need to reconnect again when auto-send ships.

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

Under **OAuth consent screen → Scopes**, add (or verify) at minimum:

| Scope | Used for |
| ----- | -------- |
| `.../auth/gmail.readonly` | Inbox sync, read threads |
| `.../auth/gmail.compose` | Save Gmail drafts (`save_gmail_draft` — draft mode) |
| `.../auth/gmail.send` | Send emails (`send_email` — auto-send mode; request now so users don't reconnect later) |
| `openid` `email` `profile` | User identity |

Enabling scopes in Google Cloud Console only allows the app to **request** them. The user must still **grant** them in the OAuth URL `scope` param when connecting (see below).

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

**Required Gmail scopes — request all of these on connect (must match backend `config/gmail_oauth_config.py`):**

```javascript
// Single source of truth on the frontend — keep in sync with backend.
// Always pass the FULL list on Connect and Reconnect (readonly + compose + send).
const GMAIL_OAUTH_SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/gmail.compose",
  "https://www.googleapis.com/auth/gmail.send",
  "openid",
  "email",
  "profile",
].join(" ");
```

| Scope | Why the frontend must request it **now** |
| ----- | ---------------------------------------- |
| `gmail.readonly` | Sync + read threads in the app |
| `gmail.compose` | Create Gmail drafts when AI finishes (`save_gmail_draft`) — missing → **403** on draft save |
| `gmail.send` | Send replies when `reply_action.mode` is `auto_send` (`send_email` node) — request at connect so the same refresh token works for send later |
| `openid` `email` `profile` | Identity |

| Agent `reply_action.mode` | Gmail scope used at runtime |
| ------------------------- | --------------------------- |
| `draft` (default) | `gmail.compose` (create draft) |
| `auto_send` | `gmail.send` (send message); may fall back to `gmail.compose` if confidence is low |

When user clicks **Connect Gmail**, redirect or open:

```
https://accounts.google.com/o/oauth2/v2/auth
  ?client_id={GOOGLE_CLIENT_ID}
  &redirect_uri=http://localhost:3000/email/inbox-settings
  &response_type=code
  &scope=https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.send openid email profile
  &access_type=offline
  &prompt=consent
  &state={random_string}
```

**JavaScript example:**

```javascript
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID;
const REDIRECT_URI = "http://localhost:3000/email/inbox-settings";

function buildGmailOAuthUrl() {
  const params = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    response_type: "code",
    scope: GMAIL_OAUTH_SCOPES,
    access_type: "offline",
    prompt: "consent",
    state: crypto.randomUUID(),
  });
  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

// Connect new inbox OR reconnect after scope changes — always use prompt=consent
window.location.href = buildGmailOAuthUrl();
```

| Param | Required | Notes |
|-------|----------|-------|
| `client_id` | Yes | From Google Console (can be env var on frontend) |
| `redirect_uri` | Yes | Must match `GOOGLE_REDIRECT_URI` |
| `response_type` | Yes | Always `code` |
| `scope` | Yes | **All three Gmail scopes** + openid (see `GMAIL_OAUTH_SCOPES` above) |
| `access_type` | Yes | `offline` — needed for **refresh_token** |
| `prompt` | Yes | `consent` — required when **adding scopes** or reconnecting; ensures user re-approves and Google returns a new refresh token |
| `state` | Recommended | CSRF protection; validate on return |

Use `encodeURIComponent` for `redirect_uri` and `scope` if building the URL manually ( `URLSearchParams` handles this automatically).

### Reconnect after scope changes

If an inbox was connected with an **old** `scope` string (e.g. only `readonly` + `send`, or missing `compose` / `send`), API calls fail with **403 insufficient scopes** — even if scopes are enabled in Google Cloud Console.

**Fix for users with existing connections:**

1. Update frontend `GMAIL_OAUTH_SCOPES` to the **full** list: `readonly` + `compose` + `send` + openid (above).
2. User clicks **Reconnect** (same flow as Connect — `POST /accounts` with a new `code`).
3. Use `prompt=consent` so Google shows the consent screen again and issues a token with all scopes.
4. After redirect, verify Google's `scope` query param includes **`gmail.compose`** and **`gmail.send`** (URL-encoded as `...%2Fgmail.compose` and `...%2Fgmail.send`).

Same email reconnecting updates the existing `email-gmail_accounts` row (`200` response).

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
  "scopes": [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
    "profile"
  ],
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
| `gmail.readonly` | Sync inbox, list/get threads |
| `gmail.compose` | Create Gmail drafts (`reply_action.mode: draft`) |
| `gmail.send` | Send replies (`reply_action.mode: auto_send`) — **include on connect** |
| `openid` `email` `profile` | User identity |

**Important:** Scopes on the Google Cloud Console ≠ scopes on the user's token. Only scopes in the frontend OAuth URL `scope` param are granted at connect time.

**Do not** use a minimal scope set (e.g. readonly-only) and add more later — Google does not upgrade existing refresh tokens when you change the frontend URL; users must reconnect.

### Troubleshooting: 403 insufficient scopes

If the email flow fails at `save_gmail_draft` or (later) `send_email` with:

```text
ACCESS_TOKEN_SCOPE_INSUFFICIENT
```

→ The inbox refresh token is missing a required scope (`gmail.compose` and/or `gmail.send`). Use the **full** `GMAIL_OAUTH_SCOPES` list and **reconnect** with `prompt=consent`.

---

## Frontend checklist

- [ ] Login first → store JWT
- [ ] Define `GMAIL_OAUTH_SCOPES` with **`readonly` + `compose` + `send`** + openid (all three Gmail scopes every time)
- [ ] Build Google OAuth URL with correct `redirect_uri` and **full** scope string
- [ ] Use `access_type=offline` + `prompt=consent` (especially on reconnect)
- [ ] After OAuth redirect, confirm `scope` query param includes **`gmail.compose`** and **`gmail.send`**
- [ ] **Reconnect** any inbox connected before the full scope string was used on the frontend
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

## Related — email AI agent

- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — agents, sync, threads, `ai_action` / draft-ready badges
- [email-flow-reprocess-thread-api.md](./email-flow-reprocess-thread-api.md) — test full flow including `save_gmail_draft`
