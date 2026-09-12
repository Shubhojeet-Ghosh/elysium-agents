# Atlas Python plugins — architecture plan

**Status:** Not implemented. This document is the locked design for v1.

**Goal:** Let team owners/admins attach **custom Python plugins** to Atlas agents. Plugins look like custom tools to the LLM (name, description, typed inputs) but run user logic (SQL, Mongo, internal services) instead of an HTTP URL. Secret _names_ live in the plugin file; secret _values_ are entered in a separate UI and stored encrypted.

**Scope:** Team-scoped CRUD (`atlas_plugins`), agent attach via `plugin_ids`, same DeepSeek tool-calling loop as HTTP tools (`chat_with_agent_v1`). Frontend API guide will live in [frontend-plugins-api-guide.md](./frontend-plugins-api-guide.md) once routes exist.

**Related:** HTTP tools — [frontend-tools-api-guide.md](./frontend-tools-api-guide.md).

---

## Product decisions (locked)

| Decision          | Choice                                                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shape             | **1 plugin = 1 LLM function** (mirror tools). No multi-action packages in v1                                                                                        |
| Source of truth   | The **Python file** defines `PLUGIN_NAME`, `PLUGIN_DISPLAY_NAME`, `PLUGIN_DESCRIPTION`, `PluginInputs`, optional `PluginSecrets`, and `run`                         |
| Create/update API | Send `python_code` only (plus `is_active` on update). Server AST-parses metadata                                                                                    |
| Execution         | Sandboxed **subprocess**, not `exec` in the API process                                                                                                             |
| Secrets           | Declare names in `class PluginSecrets`; enter values in a **separate UI**. Encrypt at rest with `APPLICATION_PASSKEY`. Hardcoding keys in the file is still allowed |
| Tenant uniqueness | Only `name` and `display_name` per team. Identical `class PluginSecrets` / `def run` across files is fine                                                           |
| Orchestration     | Reuse agent `tool_calling_config`. Plugin calls count toward `max_executions_per_turn`                                                                              |
| Chat audit        | Same `role: "tool"` rows as HTTP tools, plus `execution_kind: "plugin"`                                                                                             |
| RBAC              | Same as tools: owner/admin mutate; member list/get                                                                                                                  |

---

## How this sits next to tools

Tools stay HTTP wrappers. Plugins are a **separate team resource** with the same LLM-facing shape, a different execution backend, and the same chat orchestrator.

```
Visitor message
  → RAG + prompts
  → if tool_ids or plugin_ids and tool_calling_config.enabled
       DeepSeek (name, description, JSON Schema inputs)
         → HTTP tool  (atlas_tools)
         → Python sandbox (atlas_plugins)
       results injected as plain-text assistant messages
  → agent's llm_model streams the visitor reply
```

| Surface           | Tools today                      | Plugins                                     |
| ----------------- | -------------------------------- | ------------------------------------------- |
| Team CRUD         | `atlas_tools`                    | `atlas_plugins`                             |
| Agent attach      | `tool_ids` (max 50)              | `plugin_ids` (max 20)                       |
| LLM function name | form field `name`                | parsed from `PLUGIN_NAME`                   |
| UI label          | form field `display_name`        | parsed from `PLUGIN_DISPLAY_NAME`           |
| Description       | form field `description`         | parsed from `PLUGIN_DESCRIPTION`            |
| Inputs            | form field `parameters`          | parsed from `class PluginInputs`            |
| Execution         | HTTP URL + auth                  | `def run(inputs, secrets)` in the same file |
| Orchestration     | DeepSeek + `tool_calling_config` | **same loop, same limits**                  |
| Chat audit        | `role: "tool"`                   | same role, plus `execution_kind: "plugin"`  |

Reuse `tool_calling_config`. Do not add a second config.

---

## Plugin document (`atlas_plugins`)

One plugin = one LLM function. Create/update send `python_code`; we AST-parse and denormalize onto the document for list UI and DeepSeek:

| In the file                 | Stored on the document                                            |
| --------------------------- | ----------------------------------------------------------------- |
| `PLUGIN_NAME`               | `name` (snake*case, same regex as tools: `^[a-z]a-z0-9*]{0,63}$`) |
| `PLUGIN_DISPLAY_NAME`       | `display_name`                                                    |
| `PLUGIN_DESCRIPTION`        | `description` (LLM-facing: when to call this)                     |
| `class PluginInputs`        | `parameters` OpenAI JSON Schema                                   |
| `class PluginSecrets`       | `secret_names`                                                    |
| `def run` / `async def run` | required entrypoint (code stored as-is)                           |

Also stored: `team_id`, `created_by_user_id`, `is_active`, timestamps, `python_code`, `secrets` (`{name: ciphertext}` — **never** returned).

Reads expose `secret_names` and `secrets_configured: { mongo_uri: true, api_key: false }`.

Missing `PLUGIN_NAME`, `PLUGIN_DISPLAY_NAME`, `PLUGIN_DESCRIPTION`, or `run` → `400`. `PluginInputs` may be empty (no arguments). `PluginSecrets` may be omitted (hardcoded-only).

### Tenant uniqueness (only these two)

- `(team_id, name)` unique — LLM action name, `409` if taken
- `(team_id, display_name)` unique after strip — UI label, `409` if taken

`name` must also not collide with an `atlas_tools.name` on the same team (and the reverse on tool create/update), so DeepSeek never sees two functions with the same name. `display_name` uniqueness is **plugins-only** (a tool may share a label).

**Not unique, by design:** class names, `def run`, helpers, `PluginSecrets` attribute names, import aliases. Two plugins on the same team may both contain `class PluginSecrets` and `def run`.

---

## Typical plugin file

The file **is** the tool. On save we parse name / description / inputs into the same OpenAI function schema tools use. At chat time DeepSeek sees that schema, extracts argument values from the conversation, and we call `run(inputs, secrets)` with those values.

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

`PluginInputs` value dicts use the same types as Atlas tools (`string`, `number`, `integer`, `boolean`, `enum` + `enum_values`, `array` + `items_type`, `object` + `properties`). Convert with existing `build_tool_parameters_schema` helpers.

Chat path:

1. DeepSeek is given `function.name = create_lead`, the description, and the JSON schema for `email`.
2. It fills `email` from the conversation (e.g. visitor said "I'm ada@example.com").
3. Sandbox runs `run({"email": "ada@example.com"}, secrets)` and POSTs to `secrets.api_url` with `secrets.api_key`.
4. JSON return is injected into the turn like a tool HTTP response.

`async def run` is also accepted. Return value must be JSON-serializable (`dict` / `list` / `str` / number / bool). Non-dict returns are wrapped as `{"result": ...}`.

Helpers in the same file are fine (`def _normalize_email(...)`) and may share names with helpers in other plugins.

---

## Isolation across plugin files

Each call runs **one plugin's source in a fresh subprocess**. We never import plugin A from plugin B, never concatenate files, and never keep a shared in-process module cache of user code.

Safe for one tenant:

- Plugin A and plugin B both define `class PluginSecrets` and `def run`
- Both define `def _connect()` or `class Client`
- Both declare a secret named `mongo_uri` (values are per-plugin documents)

Orchestration looks up by plugin `name`, then executes that document's `python_code` alone.

---

## Secrets: names in code, values in a separate UI

Hardcoding API keys in `python_code` is allowed. For users who do not want secrets sitting in the plugin file (which owners/admins can read, and which we store in Mongo), use the declared-secrets path.

### 1. Names live in the plugin file

Required class name: `PluginSecrets`. Assignments are placeholders only; values in the class body are ignored at runtime.

On create/update of `python_code`, AST-parse `PluginSecrets` and store `secret_names`. Attribute names must match the tool parameter name regex. Max 20 names. No class → empty `secret_names`.

Removing a name from the class drops that ciphertext on save. Adding a name shows as `secrets_configured[name] = false` until the Secrets panel is filled.

### 2. Values live on a dedicated endpoint

Do **not** send secret values on create/update-plugin.

`POST /elysium-agents/elysium-atlas/plugins/v1/set-plugin-secrets`

```json
{
  "plugin_id": "...",
  "secrets": {
    "api_url": "https://api.example.com/leads",
    "api_key": "your-lead-api-key"
  }
}
```

- Keys must be in `secret_names`. Unknown keys → `400`.
- Omit a key to keep the existing ciphertext.
- Send `null` (or `""`) to clear that secret.
- Response never echoes values — only `secrets_configured`.

At runtime the runner wraps the dict so user code can use `secrets.mongo_uri` or `secrets["mongo_uri"]`. Missing configured values are empty strings.

### 3. Encrypt, do not hash

Hashing is one-way — we could not inject the real DB URL into `run()`. Store **ciphertext** in Mongo. Decrypt only in the parent process at execute/test time, pass into sandbox stdin, never log.

Key material: `settings.APPLICATION_PASSKEY` (not `JWT_SECRET`, unlike current tool tokens), via `encrypt_plugin_secret` / `decrypt_plugin_secret`. JWT rotation must not break plugin secrets.

Honest limit: anyone with `APPLICATION_PASSKEY` **and** DB access can decrypt. That is unavoidable for reversible secrets. Guarantees: plaintext never in API responses, never in `python_code` (unless the user hardcoded it), never in logs.

---

## Sandbox

Do **not** `exec` plugin code in the API process. That would expose JWT, Mongo, and other tenants.

Child process: `sys.executable -I` running `services/elysium_atlas_services/atlas_plugin_sandbox_runner.py`.

| Guard                   | v1 behavior                                                                                                                                                                                     |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Environment             | Stripped — do not inherit `JWT_SECRET`, Mongo URIs, Redis, AWS keys. Minimal `PATH` / `SYSTEMROOT` so Python can start                                                                          |
| Timeout                 | 20s; kill the process group on expiry                                                                                                                                                           |
| I/O                     | stdin JSON `{inputs, secrets}`; stdout a single JSON result; user `print`s go to stderr and are **not** sent to the LLM                                                                         |
| AST gate (save and run) | Require `PLUGIN_NAME`, `PLUGIN_DISPLAY_NAME`, `PLUGIN_DESCRIPTION`, top-level `run`; reject `eval` / `exec` / `compile` / `__import__` / `open` / `input`                                       |
| Allowed imports         | Curated stdlib (`json`, `datetime`, `re`, `math`, `decimal`, `typing`, `collections`, `itertools`, `functools`, `hashlib`, `base64`, `uuid`, `urllib.parse`) plus `httpx`, `pymongo`, `pymysql` |
| Caps                    | Max code 64 KB; max 20 secrets; result truncated with existing tool LLM/observability caps                                                                                                      |
| Unix extra              | `resource.setrlimit` memory cap. Windows: timeout + kill only                                                                                                                                   |

This is process isolation, not a VM. Allowed `httpx` / `pymongo` / `pymysql` can still reach the network (that is the product). They cannot read app secrets or other tenants' Mongo from our process. Private-IP egress filtering is a later hardening step.

Timeout / crash / non-JSON maps to `{"error": true, "message": "..."}` like HTTP tools.

---

## APIs (planned)

Base path: `/elysium-agents/elysium-atlas/plugins`

All routes require `Authorization: Bearer <session_jwt>` with `user_id`, `team_id`, and `role`.

| Method | Path                     | Who          | Description                                                                   |
| ------ | ------------------------ | ------------ | ----------------------------------------------------------------------------- |
| POST   | `/v1/create-plugin`      | owner, admin | Body: `{ "python_code": "..." }`                                              |
| POST   | `/v1/list-plugins`       | all members  | Paginated list for active team                                                |
| POST   | `/v1/get-plugin`         | all members  | `{ "plugin_id": "..." }` — includes `python_code`, never secret values        |
| POST   | `/v1/update-plugin`      | owner, admin | `{ "plugin_id", "python_code"?, "is_active"? }`                               |
| POST   | `/v1/delete-plugin`      | owner, admin | Hard delete                                                                   |
| POST   | `/v1/set-plugin-secrets` | owner, admin | Write-only values for names declared in `PluginSecrets`                       |
| POST   | `/v1/test-plugin`        | owner, admin | `{ "plugin_id", "inputs" }` — sandbox run; decrypts secrets for that run only |

Layering (same as tools):

| Layer          | Location                                                                 |
| -------------- | ------------------------------------------------------------------------ |
| Config         | `config/atlas_plugin_models.py`, `config/atlas_plugin_config.py`         |
| Routes         | `routes/elysium_atlas/atlas_plugin_routes.py`                            |
| Controllers    | `controllers/elysium_atlas_controller_files/atlas_plugin_controllers.py` |
| CRUD           | `services/elysium_atlas_services/atlas_plugin_services.py`               |
| Sandbox runner | `services/elysium_atlas_services/atlas_plugin_sandbox_runner.py`         |
| Execution      | `services/elysium_atlas_services/atlas_plugin_execution_services.py`     |

Indexes on `atlas_plugins`: `team_id`; unique `(team_id, name)`; unique `(team_id, display_name)`; `(team_id, updated_at, _id)`.

---

## Agent linking (`plugin_ids`)

Agents store `plugin_ids: string[]` (Mongo `_id` values from `atlas_plugins`).

| Rule       | Detail                                                                     |
| ---------- | -------------------------------------------------------------------------- |
| Default    | `[]` on new agents                                                         |
| Max        | 20 plugin IDs per agent                                                    |
| Validation | Every ID must exist and belong to the **same team** as the agent           |
| Duplicates | Removed automatically (order preserved)                                    |
| Name clash | Reject if any attached plugin `name` collides with an attached tool `name` |

Accepted on the same agent endpoints as `tool_ids`: `pre-build-agent-operations`, `build-agent`, `update-agent`. Send `"plugin_ids": []` to detach all plugins.

---

## Chat runtime

Extend `run_agent_tool_calling_round`:

1. Load active tools **and** plugins.
2. Merge OpenAI function definitions (same shape as `build_openai_tools_definitions`).
3. Dispatch by function name: HTTP vs sandbox.
4. Gate in `agent_chat_services.py` becomes `(tool_ids or plugin_ids) and tool_calling_config.enabled`.

Keep monitor/history as `role: "tool"` so Atlas UI that already toggles tool calls keeps working. Add `execution_kind: "plugin"` on the observability record.

---

## Frontend (v1)

1. **Code editor** — stub is the typical plugin file above. After save, show parsed `name` / `display_name` / parameter list as read-only chips (what the LLM will see). No separate parameter form — inputs live in the file.
2. **Secrets panel (separate)** — one password field per `secret_names` entry; badge if not configured; never pre-fill values (“leave blank to keep”).
3. **Test** — after secrets are configured.

```
Code editor
  → save python_code
  → AST extract name, description, inputs, secret names
  → Mongo (parsed schema + ciphertext)
  → Secrets panel (set-plugin-secrets)
  → DeepSeek tool schema
  → extracted inputs + decrypted secrets → sandbox run
```

---

## Out of scope for this pass

- Multi-action plugin packages
- Firecracker / gVisor
- Blocking private-IP egress
- Extra DB drivers beyond pymongo + pymysql
- Renaming `tool_calling_config`
- Frontend API guide file (follows once routes exist): [frontend-plugins-api-guide.md](./frontend-plugins-api-guide.md)
