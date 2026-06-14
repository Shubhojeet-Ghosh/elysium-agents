# Agent datasource APIs — frontend guide

Reference for paginated **agent knowledge source** lists: indexed URLs, uploaded files, custom texts, and QA pairs.

**Base path:** `/elysium-agents/elysium-atlas/agent`

**Auth:** `Authorization: Bearer <session_jwt>` on every request below.

Team RBAC applies — see [frontend-agents-rbac-guide.md](./frontend-agents-rbac-guide.md). All team members (`owner`, `admin`, `member`) may call these read endpoints.

---

## Pagination (shared)

All four list endpoints use the same **page-based** pagination model as live visitors and team chat sessions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_id` | `string` | **required** | Agent to load data for |
| `page` | `number` | `1` | 1-based page number |
| `limit` | `number` | `10` | Items per page (max `100`) |

### Response pagination fields

Every successful list response includes:

| Field | Type | Description |
|-------|------|-------------|
| `total` | `number` | Total items for this agent and datasource |
| `page` | `number` | Page returned (may differ from the request if out of range) |
| `limit` | `number` | Page size used |
| `total_pages` | `number` | `ceil(total / limit)`; `0` when `total` is `0` |
| `has_next` | `boolean` | `true` if another page exists after this one |
| `has_prev` | `boolean` | `true` if a previous page exists |

**Out-of-range pages:** If the requested `page` is greater than `total_pages`, the API **clamps** to the last valid page (same behavior as live visitors). Example: 25 items, `limit=10`, request `page=99` → response `page=3`.

**Sort order:** Newest first by `updated_at`, then `_id`.

---

## 1. Indexed URLs

`POST /v1/get-agent-urls`

### Request

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "page": 1,
  "limit": 10
}
```

### Success response (`200`)

```json
{
  "success": true,
  "message": "URLs fetched successfully.",
  "urls": [
    {
      "agent_id": "674a1b2c3d4e5f6789012345",
      "url": "https://example.com/pricing",
      "status": "indexed",
      "page_type": "content",
      "created_at": "2026-06-01T10:00:00+00:00",
      "updated_at": "2026-06-10T14:30:00+00:00"
    }
  ],
  "total": 42,
  "page": 1,
  "limit": 10,
  "total_pages": 5,
  "has_next": true,
  "has_prev": false
}
```

### Item fields (typical)

| Field | Description |
|-------|-------------|
| `url` | Indexed page URL |
| `status` | Indexing status (e.g. `indexing`, `indexed`, `failed`) |
| `page_type` | `product`, `content`, or empty while pending |
| `created_at` / `updated_at` | ISO 8601 timestamps |

---

## 2. Uploaded files

`POST /v1/get-agent-files`

### Request

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "page": 1,
  "limit": 10
}
```

### Success response (`200`)

```json
{
  "success": true,
  "message": "Files fetched successfully.",
  "files": [
    {
      "agent_id": "674a1b2c3d4e5f6789012345",
      "file_name": "product-catalog.pdf",
      "file_key": "agents/674a.../files/product-catalog.pdf",
      "cdn_url": "https://cdn.example.com/...",
      "file_source": "upload",
      "status": "indexed",
      "created_at": "2026-06-01T10:00:00+00:00",
      "updated_at": "2026-06-10T14:30:00+00:00"
    }
  ],
  "total": 8,
  "page": 1,
  "limit": 10,
  "total_pages": 1,
  "has_next": false,
  "has_prev": false
}
```

---

## 3. Custom texts

`POST /v1/get-agent-custom-texts`

Lists custom text **metadata** only. Full body text is loaded separately via `get-custom-text-content`.

### Request

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "page": 2,
  "limit": 10
}
```

### Success response (`200`)

```json
{
  "success": true,
  "message": "Custom texts fetched successfully.",
  "custom_texts": [
    {
      "agent_id": "674a1b2c3d4e5f6789012345",
      "custom_text_alias": "shipping-policy",
      "status": "indexed",
      "created_at": "2026-06-01T10:00:00+00:00",
      "updated_at": "2026-06-10T14:30:00+00:00"
    }
  ],
  "total": 15,
  "page": 2,
  "limit": 10,
  "total_pages": 2,
  "has_next": false,
  "has_prev": true
}
```

### Load full text

`POST /v1/get-custom-text-content`

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "custom_text_alias": "shipping-policy"
}
```

---

## 4. QA pairs

`POST /v1/get-agent-qa-pairs`

Lists QA pair **metadata** only. Question/answer content is loaded via `get-qa-pair-content`.

### Request

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "page": 1,
  "limit": 10
}
```

### Success response (`200`)

```json
{
  "success": true,
  "message": "QA pairs fetched successfully.",
  "qa_pairs": [
    {
      "agent_id": "674a1b2c3d4e5f6789012345",
      "qna_alias": "return-policy",
      "status": "indexed",
      "created_at": "2026-06-01T10:00:00+00:00",
      "updated_at": "2026-06-10T14:30:00+00:00"
    }
  ],
  "total": 3,
  "page": 1,
  "limit": 10,
  "total_pages": 1,
  "has_next": false,
  "has_prev": false
}
```

### Load full Q&A

`POST /v1/get-qa-pair-content`

```json
{
  "agent_id": "674a1b2c3d4e5f6789012345",
  "qna_alias": "return-policy"
}
```

---

## Frontend usage patterns

### Initial load (default page size)

Omit `page` and `limit` to get page 1 with 10 items:

```json
{ "agent_id": "674a1b2c3d4e5f6789012345" }
```

### Pagination controls

Use the response metadata directly:

```ts
const res = await fetch("/elysium-agents/elysium-atlas/agent/v1/get-agent-urls", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ agent_id, page, limit: 10 }),
}).then((r) => r.json());

// res.urls       — current page items
// res.total      — total count for pager label
// res.total_pages
// res.has_next   — enable "Next"
// res.has_prev   — enable "Previous"
```

### Tabs with independent pagination

URLs, files, custom texts, and QA pairs each maintain their own `page` / `total` state. Changing the URLs page does not affect the files tab.

### Agent details preview

`POST /v1/get-agent-details` embeds the **first page** (default `limit=10`) of each datasource under:

- `agent_details.links`
- `agent_details.files`
- `agent_details.custom_texts`
- `agent_details.qa_pairs`

Each block has the same shape as the dedicated list endpoint (`data`, `total`, `page`, `limit`, `total_pages`, `has_next`, `has_prev`). Use the dedicated list endpoints when the user opens a full datasource tab or paginates beyond page 1.

---

## Errors

| Status | When |
|--------|------|
| `401` | Missing or invalid JWT |
| `403` | No team context, or user is not a member of the agent's team |
| `404` | Agent not found (on content/detail endpoints) |
| `500` | Unexpected server error |

Error body shape:

```json
{
  "success": false,
  "message": "Human-readable message"
}
```

---

## Migration note (breaking change)

These endpoints previously used **cursor-based** pagination (`cursor`, `include_count`, nested `{ data, next_cursor, has_more }`).

They now use **page/limit** with flat pagination fields on the response root. Update any frontend code that:

- Passed `cursor` or `include_count`
- Read `urls.data`, `urls.has_more`, or `urls.next_cursor`

Replace with `page`, `limit`, and the root-level `total`, `total_pages`, `has_next`, and `has_prev` fields.
