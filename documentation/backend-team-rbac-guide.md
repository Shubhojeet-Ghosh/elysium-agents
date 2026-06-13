# Team & role-based access — backend integration guide

Short reference for **Python (or any downstream) services** that share the same MongoDB and validate Atlas session JWTs.

The Express Atlas API is moving to **team-scoped** and **role-based** access. Every authenticated request carries an **active team** and a **role for that team**.

---

## Session JWT (what changed)

Issued after login (password, magic link, Google) or `POST /elysium-atlas/v1/auth/select-team` when the user has multiple teams.

**Verify with the same `JWT_SECRET` as the Node server** (HS256).

### Payload (session token)

```json
{
  "user_id": "69568df774db787c7f93b86b",
  "email": "user@example.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "is_profile_complete": true,
  "team_id": "699e9bf195fcec2ed8ef6763",
  "role": "owner",
  "iat": 1781374961,
  "exp": 1783966961
}
```

| Claim     | Meaning                                                                  |
| --------- | ------------------------------------------------------------------------ |
| `user_id` | User id (`elysium_atlas_users._id`)                                      |
| `team_id` | **Active team** for this session — all team-scoped APIs use this         |
| `role`    | User's role **for `team_id` only**: `"owner"` \| `"admin"` \| `"member"` |

**Important:** `role` in the JWT is a snapshot at login / team selection (TTL ~30 days). For sensitive checks, re-resolve role from MongoDB (see below).

Users with **multiple teams** pick one at login; until then they get a short-lived `selection_token` (no session JWT, no `team_id` / `role`).

---

## Roles

| Role     | How assigned                            | In DB                                                         |
| -------- | --------------------------------------- | ------------------------------------------------------------- |
| `owner`  | Created the team                        | `atlas_teams.owner_user_id` — **not** in `atlas_team_members` |
| `admin`  | Invited with `role: "admin"`            | `atlas_team_members.role`                                     |
| `member` | Invited with `role: "member"` (default) | `atlas_team_members.role`                                     |

A user can belong to **many teams** (own one or more + join others). The JWT only reflects **one active team** at a time.

---

## MongoDB — where to check role

### 1. Resolve role for `(user_id, team_id)` — recommended for Python guards

```python
def get_user_role_for_team(db, user_id: str, team_id: str) -> str | None:
    uid, tid = str(user_id), str(team_id)

    team = db.atlas_teams.find_one({
        "_id": ObjectId(tid),
        "owner_user_id": uid,
        "is_active": True,
        "status": "active",
    })
    if team:
        return "owner"

    membership = db.atlas_team_members.find_one({
        "team_id": tid,
        "user_id": uid,
        "status": "active",
    })
    if membership:
        return membership["role"]  # "admin" | "member"

    return None  # not on this team
```

Use **`team_id` from the JWT** (or from the resource you're authorizing) together with **`user_id` from the JWT**.

### 2. Collections cheat sheet

| Collection                   | Use for                                                                                                                            |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| **`atlas_teams`**            | Team metadata; `owner_user_id`, `owner_email`, `team_name`, `member_count`, **`max_members`** (team size cap — source of truth)    |
| **`atlas_team_members`**     | Invited users who **accepted** — `team_id`, `user_id`, `email`, **`role`** (`admin` \| `member`), `status` (`active` \| `removed`) |
| **`atlas_team_invitations`** | Pending/declined invites — `role` on invite is `admin` \| `member`                                                                 |
| **`elysium_atlas_users`**    | Profile — `email`, `first_name`, `last_name`, `is_profile_complete`                                                                |

**Owner is not a row in `atlas_team_members`.** List APIs synthesize the owner with `role: "owner"`.

**Do not** read team capacity from `atlas_user_available_plan_limits` — `max_team_members` is not stored there. Use `atlas_teams.max_members`.

---

## Permissions (what each role can do)

Express enforces this today on **team member APIs**; mirror the same rules in Python for your own team-scoped routes.

| Action            | `owner` | `admin` | `member` |
| ----------------- | ------- | ------- | -------- |
| List team members | Yes     | Yes     | Yes      |
| Invite members    | Yes     | Yes     | No       |
| Remove members    | Yes     | Yes     | No       |

### Remove rules (extra)

- **Owner cannot be removed** (400) — compare target `user_id` to `atlas_teams.owner_user_id`.
- **Member** calling remove → **403** before target is checked.
- **Admin** can remove other **admins** and **members**, but **not** the owner.

Invites only allow roles `"admin"` or `"member"` — never `"owner"`.

---

## Suggested Python auth pattern

```python
ROLE_PERMISSIONS = {
    "owner": {"list_members", "invite_members", "remove_members"},
    "admin": {"list_members", "invite_members", "remove_members"},
    "member": {"list_members"},
}

def require_team_action(payload: dict, action: str, team_id: str | None = None):
    user_id = payload["user_id"]
    jwt_team_id = payload.get("team_id")
    jwt_role = payload.get("role")

    # Scope to JWT active team unless you explicitly pass another team_id
    tid = team_id or jwt_team_id
    if not tid:
        raise Forbidden("No team context")

    # Fast path: JWT role if team matches (optional)
    # Strict path: re-fetch from Mongo (recommended for remove / admin actions)
    role = get_user_role_for_team(db, user_id, tid)
    if role is None:
        raise Forbidden("Not a member of this team")
    if action not in ROLE_PERMISSIONS.get(role, set()):
        raise Forbidden(f"Role '{role}' cannot {action}")
    return {"user_id": user_id, "team_id": tid, "role": role}
```

**When to re-query MongoDB vs trust JWT:**

| Approach         | Use when                                                                                        |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| Trust JWT `role` | Low-risk reads, UI gating, same team as `team_id` in token                                      |
| Re-query MongoDB | Removes, admin actions, anything security-sensitive — role/removal may have changed since login |

---

## Multi-team users

Login response includes a `teams[]` array (each entry has `team_id`, `team_name`, `role`, `is_owner`). The session JWT stores **one** chosen team.

If your Python service receives a request for a **different** `team_id` than the JWT's `team_id`, do not trust JWT `role` — run `get_user_role_for_team(user_id, requested_team_id)`.

---

## Express API surface (for reference)

| Endpoint                                     | Auth                                    |
| -------------------------------------------- | --------------------------------------- |
| `GET /elysium-atlas/v1/team/members`         | Bearer session JWT — any member+        |
| `POST /elysium-atlas/v1/team/members/invite` | owner or admin                          |
| `POST /elysium-atlas/v1/team/members/remove` | owner or admin                          |
| Invite preview/respond                       | Public — invite JWT in body, no session |

Full frontend-oriented docs: [frontend-auth-guide.md](./frontend-auth-guide.md), [frontend-team-members-guide.md](./frontend-team-members-guide.md).

---

## Checklist for Python services

1. Decode session JWT with shared **`JWT_SECRET`**.
2. Read **`user_id`**, **`team_id`**, **`role`** from claims.
3. For team-scoped data, filter by **`team_id`** from the token (or validate user belongs to the team you're accessing).
4. Resolve role from **`atlas_teams`** + **`atlas_team_members`** when enforcing write/admin actions.
5. Treat **`owner`** separately — not in `atlas_team_members`, cannot be removed.
6. Team size limits: **`atlas_teams.max_members`** and **`member_count`** (owner counts as 1).
7. **`POST /elysium-atlas/v1/plan/info`** — team-scoped: plan + consumable limits from **team owner**, capacity from **session `team_id`**. Any team member may call it.
