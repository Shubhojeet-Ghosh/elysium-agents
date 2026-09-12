# Custom Plugins APIs — frontend guide

Reference for building the **team custom plugins** UI in Elysium Atlas. Plugins are Python functions the LLM can call like tools. The **plugin file** is the source of truth for name, description, and typed inputs. At chat runtime, attached plugins share DeepSeek orchestration with HTTP tools, then results are passed to the agent’s main LLM.

**Architecture plan:** [atlas-plugins-plan.md](./atlas-plugins-plan.md)

**Base path:** `/elysium-agents/elysium-atlas/plugins`

All routes require `Authorization: Bearer <session_jwt>`. The JWT must include `user_id`, `team_id`, and `role`.

---

## Overview

| Concept | Detail |
|---------|--------|
| Scope | **Team-level** — plugins belong to the JWT `team_id` |
| Plugin ID | Mongo `_id`, returned as `plugin_id` |
| Storage | `atlas_plugins` |
| Uniqueness | Unique per team: `name` (`PLUGIN_NAME`) and `display_name` (`PLUGIN_DISPLAY_NAME`). `name` also cannot match a team tool `name` |
| Source of truth | `python_code` — parsed on save. Do not send name/description/parameters as separate form fields |
| Secrets | Names in `class PluginSecrets`. Values via `set-plugin-secrets`. **Never returned** |
| Agent linking | `plugin_ids` on `atlas_agents` (max 20) |
| Orchestration | Same `tool_calling_config` as tools |
| Chat audit | `role: "tool"` plus `execution_kind: "plugin"` |

Class names like `PluginSecrets` / `def run` may be identical across plugins. Each file runs in its own subprocess.

---

## Typical plugin file (editor stub)

Use this as the default code in the create-plugin editor. The LLM fills `email` from the conversation. The lead API URL and API key stay in the Secrets page — they are not in the file.

```python
import httpx

PLUGIN_NAME = "create_lead"
PLUGIN_DISPLAY_NAME = "Create Lead"
PLUGIN_DESCRIPTION = (
    "Use when the visitor wants to be contacted, requests a callback or demo, "
    "or shares an email so you can create a lead. Requires the visitor email."
)


class PluginInputs:
    email = {
        "type": "string",
        "description": "Visitor email address to create a lead for",
        "required": True,
    }


class PluginSecrets:
    api_url = ""
    api_key = ""


def run(inputs: dict, secrets):
    email = (inputs.get("email") or "").strip().lower()
    if not email:
        return {"error": True, "message": "email is required."}

    api_url = (secrets.api_url or "").strip()
    api_key = (secrets.api_key or "").strip()
    if not api_url or not api_key:
        return {"error": True, "message": "Lead API URL or API key is not configured."}

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            api_url,
            json={"email": email},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    try:
        body = response.json()
    except Exception:
        body = response.text or ""

    if response.status_code >= 400:
        return {
            "error": True,
            "status_code": response.status_code,
            "body": body,
        }

    return body if isinstance(body, dict) else {"result": body}
```

After save, the Secrets page should show `api_url` and `api_key` (password fields). Example values (never stored in the file):

- `api_url` — `https://api.example.com/leads`
- `api_key` — the Bearer token for that API

The lead API is expected to accept `POST` JSON `{ "email": "ada@example.com" }`.

Required in every file: `PLUGIN_NAME`, `PLUGIN_DISPLAY_NAME`, `PLUGIN_DESCRIPTION`, `def run` (or `async def run`). `PluginInputs` and `PluginSecrets` are optional.

`PLUGIN_NAME` must be snake_case: `^[a-z][a-z0-9_]{0,63}$`.

`PluginInputs` types match tools: `string`, `number`, `integer`, `boolean`, `enum` (+ `enum_values`), `array` (+ `items_type`), `object` (+ `properties`).

Allowed imports (v1): curated stdlib plus `httpx`, `pymongo`, `bson`, `pymysql`. `eval` / `exec` / `open` / `os` are rejected.

Hardcoding secrets in the file is allowed. Prefer `PluginSecrets` + the Secrets page.

Use `secrets.api_url` or `secrets["api_url"]`.

---

## Agent linking (`plugin_ids`)

Same endpoints as `tool_ids`: `pre-build-agent-operations`, `build-agent`, `update-agent`.

| Rule | Detail |
|------|--------|
| Default | `[]` |
| Max | 20 |
| Validation | Same team as the agent |
| Clash | Plugin `name` cannot match an attached tool `name` |

Send `"plugin_ids": []` to detach all plugins.

`tool_calling_config` already covers plugins (max rounds, max executions, parallel). Show those controls when tools **or** plugins are selected.

---

## Roles

| Role | Access |
|------|--------|
| `owner` / `admin` | Create, update, delete, set secrets, test, list, get |
| `member` | List and get only |

---

## Endpoints

| Method | Path | Who | Description |
|--------|------|-----|-------------|
| POST | `/v1/create-plugin` | owner, admin | `{ "python_code": "..." }` |
| POST | `/v1/list-plugins` | all members | Paginated list |
| POST | `/v1/get-plugin` | all members | `{ "plugin_id": "..." }` |
| POST | `/v1/update-plugin` | owner, admin | `{ "plugin_id", "python_code"?, "is_active"? }` |
| POST | `/v1/delete-plugin` | owner, admin | Hard delete |
| POST | `/v1/set-plugin-secrets` | owner, admin | Write-only secret values |
| POST | `/v1/test-plugin` | owner, admin | `{ "plugin_id", "inputs": {} }` |

---

## Response shape (`plugin`)

```json
{
  "plugin_id": "674a1b2c3d4e5f6789012345",
  "team_id": "...",
  "created_by_user_id": "...",
  "name": "create_lead",
  "display_name": "Create Lead",
  "description": "Use when the visitor wants to be contacted, requests a callback or demo, or shares an email so you can create a lead. Requires the visitor email.",
  "parameters": {
    "type": "object",
    "properties": {
      "email": { "type": "string", "description": "Visitor email address to create a lead for" }
    },
    "required": ["email"]
  },
  "python_code": "...",
  "secret_names": ["api_url", "api_key"],
  "secrets_configured": { "api_url": true, "api_key": false },
  "is_active": true,
  "created_at": "...",
  "updated_at": "..."
}
```

Secret **values are never returned**. After save, show parsed `name` / `display_name` / parameters as read-only chips so authors see what the LLM will get.

---

## Set secrets

`POST /v1/set-plugin-secrets`

```json
{
  "plugin_id": "...",
  "secrets": {
    "api_url": "https://api.example.com/leads",
    "api_key": "your-lead-api-key"
  }
}
```

- Keys must be in `secret_names`.
- Omit a key to keep the existing value.
- `null` or `""` clears that secret.
- Response is the plugin object with updated `secrets_configured` only.

UI: separate Secrets panel, password fields, never pre-fill, “leave blank to keep”.

---

## Test

`POST /v1/test-plugin`

```json
{
  "plugin_id": "...",
  "inputs": { "email": "ada@example.com" }
}
```

Runs the sandbox with stored code and decrypted secrets. `{ "success": true, "result": { ... } }` or `success: false` when the plugin returned `{ "error": true }`.

---

## Errors

| Status | When |
|--------|------|
| `400` | Parse error (missing constants, bad `PluginInputs`, banned import) |
| `403` | No team / member mutating / not on team |
| `404` | Plugin not found |
| `409` | Duplicate `PLUGIN_NAME` or `PLUGIN_DISPLAY_NAME` on the team (or name taken by a tool) |

---

## Frontend checklist

1. Code editor with the typical `create_lead` file as the stub (`httpx` POST, `email` input, `api_url` + `api_key` secrets).
2. After save, chips for parsed name, display name, and input list.
3. Secrets panel from `secret_names` + `secrets_configured`.
4. Test button with a JSON inputs editor.
5. Agent builder: multi-select plugins into `plugin_ids`; reuse tool-calling config controls.

For HTTP tools (API URL integrations), see [frontend-tools-api-guide.md](./frontend-tools-api-guide.md).
