# Postman collections

Import-ready **Postman Collection v2.1** JSON files for manual API testing.

## Collections

| File | Scope |
|------|--------|
| `elysium-atlas-kb-items.postman_collection.json` | Team knowledge library (`/elysium-agents/elysium-atlas/kb-items`) |

## Quick start

1. Postman → **Import** → select the `.json` file.
2. Open the collection → **Variables** tab:
   - `base_url` — API host (default `http://localhost:7000`)
   - `atlas_jwt_token` — session JWT with `user_id`, `team_id`, `role`
3. Send requests. Create endpoints auto-save IDs (e.g. `kb_id`) into collection variables for follow-up calls.

Auth is inherited on every request: `Authorization: Bearer {{atlas_jwt_token}}`.

---

## Conventions for new collections

When adding a new Postman JSON for this repo, follow this pattern.

### File & format

- **Location:** `postman/<feature-name>.postman_collection.json`
- **Schema:** `https://schema.getpostman.com/json/collection/v2.1.0/collection.json`
- **Naming:** Human-readable collection `name` in `info`; kebab-case filename.

### Auth (required)

Set **collection-level** Bearer auth — do not duplicate per request:

```json
"auth": {
  "type": "bearer",
  "bearer": [
    { "key": "token", "value": "{{atlas_jwt_token}}", "type": "string" }
  ]
}
```

Equivalent header: `Authorization: Bearer {{atlas_jwt_token}}`.

### Collection variables

| Variable | Purpose |
|----------|---------|
| `base_url` | Server root, no trailing slash (e.g. `http://localhost:7000`) |
| `atlas_jwt_token` | JWT for Atlas / team-scoped routes |
| *(feature-specific)* | IDs returned by create flows (`kb_id`, `agent_id`, etc.) |

Use `{{base_url}}` in URLs. Full paths include the app prefix: `/elysium-agents/...`.

### Request layout

- **Group by domain** in folders (e.g. URLs, Files, Custom Texts).
- **Method:** match FastAPI routes (mostly `POST` for this API).
- **Header:** `Content-Type: application/json` on body requests.
- **Body:** raw JSON with realistic example values from Pydantic models / frontend guides.
- **Description:** one line on what the endpoint does; note multi-step flows (e.g. file upload).

### Chaining with test scripts

On **create** requests, save IDs from the real response shape so later requests can use `{{kb_id}}`:

```javascript
const json = pm.response.json();
if (json.kb_id) {
  pm.collectionVariables.set('kb_id', json.kb_id);
}
```

Adjust field paths to match the controller response (`items[0].kb_id`, `presigned_urls[0].s3_key`, etc.).

### Source of truth

Derive endpoints and bodies from:

1. `routes/` — path and HTTP method  
2. `config/*_models.py` — request body fields  
3. `documentation/*-api-guide.md` — examples and flows  

### Checklist before committing

- [ ] Collection-level Bearer `{{atlas_jwt_token}}`
- [ ] `base_url` variable with local default (`7000` per `config/settings.py`)
- [ ] All endpoints for the feature included
- [ ] Example bodies match Pydantic validation (required fields, aliases, enums)
- [ ] Create → get/update/delete chain works via saved variables
- [ ] JSON validates (`python -c "import json; json.load(open('postman/....json'))"`)

---

## Related docs

- [frontend-kb-items-api-guide.md](../documentation/frontend-kb-items-api-guide.md)
- [team-knowledge-bases-plan.md](../documentation/team-knowledge-bases-plan.md)
