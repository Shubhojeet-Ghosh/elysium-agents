# Agent APIs — team RBAC (frontend guide)

Short reference for the **Elysium Agents** agent routes after team-based access was added.

**Base path:** `/elysium-agents/elysium-atlas/agent`

All authenticated routes expect `Authorization: Bearer <session_jwt>`. The JWT must include `user_id`, `team_id`, and `role` (see [backend-team-rbac-guide.md](./backend-team-rbac-guide.md)).

---

## What changed

| Before | After |
|--------|-------|
| Agents scoped to **user** (`owner_user_id`) | Agents scoped to **team** (`team_id` from JWT) |
| Only the creator could access their agents | **All team members** can **view** team agents |
| Owner-only checks on some routes | **Owner + admin** can **create / edit / delete**; **member** is read-only |

`list-agents` now returns every agent for the JWT’s active `team_id`, not just agents created by the logged-in user.

---

## Roles

| Role | Agent access |
|------|----------------|
| `owner` | Full — create, edit, delete, view |
| `admin` | Full — create, edit, delete, view |
| `member` | **View only** — list and read config/knowledge; cannot create, update, upload, or delete |

Use JWT `role` to **disable UI controls** (buttons, inputs, upload zones). The backend **re-checks membership/role in MongoDB** on every request — UI gating alone is not enough.

---

## API permissions

### Read — owner, admin, member

User must be an active member of the **agent’s team** (resolved from the agent document, not only JWT `team_id`).

| Endpoint | Description |
|----------|-------------|
| `POST /v1/list-agents` | List all agents for the active team |
| `POST /v1/get-agent-details` | Full agent config/details |
| `POST /v1/get-agent-urls` | Paginated indexed URLs |
| `POST /v1/get-agent-files` | Paginated uploaded files |
| `POST /v1/get-agent-custom-texts` | Paginated custom texts |
| `POST /v1/get-agent-qa-pairs` | Paginated QA pairs |
| `POST /v1/get-custom-text-content` | Custom text body from vector store |
| `POST /v1/get-qa-pair-content` | QA pair body from vector store |

### Write — owner and admin only

| Endpoint | Description |
|----------|-------------|
| `POST /v1/pre-build-agent-operations` | Create agent shell (name, initial config) |
| `POST /v1/generate-presigned-urls` | S3 upload URLs for files/icons |
| `POST /v1/build-agent` | Index links/files/knowledge (build pipeline) |
| `POST /v1/update-agent` | Update agent metadata and re-index |
| `POST /v1/delete-agent` | Delete agent and related data |
| `POST /v1/remove-agent-links` | Remove indexed URLs |
| `POST /v1/delete-agent-files` | Remove uploaded files |
| `POST /v1/delete-agent-custom-data` | Remove custom texts / QA pairs |

### Unchanged (not part of team RBAC)

| Endpoint | Notes |
|----------|-------|
| `POST /v1/get-agent-fields` | **No JWT** — used by widget/visitor flows |
| `POST /v1/query-agent` | Chat/query — separate plan/usage checks |
| `POST /v1/rotate-conversation-id` | Public chat session helper |
| `POST /v1/mark-chat-message-read` | Public chat helper |

---

## Frontend UI checklist

When `role === "member"`:

- **Hide or disable:** Create agent, Save/Update, Build/Re-index, Delete agent, file upload, add/remove links, add/remove custom knowledge, delete files/links/knowledge.
- **Keep enabled:** Agent list, agent detail/settings **view**, knowledge base **view** (URLs, files, texts, QA lists and content).
- **Read-only mode:** Prefer disabling entire forms/sections rather than individual fields — all write APIs above return 403 for members.

When `role === "owner"` or `role === "admin"`:

- Full agent management for agents belonging to the team.

When JWT has **no `team_id`** (user has not selected a team):

- Do not call agent APIs; redirect to team selection first.

---

## Error responses

| Status | Message | When |
|--------|---------|------|
| `401` | Token invalid/expired | Missing or bad JWT |
| `403` | `No team context. Select a team to continue.` | JWT missing `team_id` |
| `403` | `You are not a member of this team.` | User removed or wrong team (list) |
| `403` | `You are not authorized to access this agent.` | Read — not on agent’s team |
| `403` | `You are not authorized to modify this agent.` | Write — member or not on agent’s team |
| `403` | `You are not authorized to create or modify agents for this team.` | Create flow — member role |

Always handle `403` gracefully; do not rely only on JWT `role` — membership can change after login.

---

## Quick reference

```
member  → can call all READ endpoints
member  → cannot call any WRITE endpoints

owner   → READ + WRITE
admin   → READ + WRITE
```

For related team-member management (invite/remove), see the Express Atlas API docs referenced in [backend-team-rbac-guide.md](./backend-team-rbac-guide.md).
