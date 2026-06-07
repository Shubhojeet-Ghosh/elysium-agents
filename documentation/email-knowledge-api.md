# Email Knowledge API — Qdrant & Mongo Guide

How to create, list, and delete team knowledge for the email AI agent. Knowledge text is chunked, embedded, and stored in **Qdrant**. Metadata only lives in **MongoDB** — full text is never stored in Mongo.

For email agent setup (Gmail sync, threads), see [email-ai-agent-setup.md](./email-ai-agent-setup.md).

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
1. Create knowledge     →  POST /email-knowledge/v1/create
2. List team knowledge  →  POST /email-knowledge/v1/list-team-knowledge
3. Delete knowledge     →  POST /email-knowledge/v1/delete
4. Query knowledge      →  POST /email-knowledge/v1/query  (testing only)
```

Knowledge is scoped to **`team_id`** today. Later you will attach `knowledge_id` values to individual email AI agents. The email agent will call the **retrieval service** directly (not the query API) for RAG.

No `Authorization` header required (prototype).

---

## How indexing works

When you call **create**, the backend runs this pipeline:

```
knowledge_text
    ↓
chunk_text_content()     →  1500 char chunks, 200 char overlap (sentence-aware)
    ↓
text-embedding-3-small   →  1536-dimension vectors (OpenAI)
    ↓
Qdrant collection        →  email-knowledge  (one point per chunk)
    ↓
MongoDB collection       →  email-knowledge  (one metadata doc per knowledge_id)
```

**Chunking defaults** (same as Elysium Atlas):

| Setting | Value |
|---------|-------|
| `chunk_size` | 1500 characters |
| `chunk_overlap` | 200 characters (~13%) |
| Embedding model | `text-embedding-3-small` |
| Vector dimensions | 1536 |
| Distance metric | Cosine |

Text ≤ 1500 characters is stored as a **single chunk** (one Qdrant point).

---

## Data model (for reference)

### MongoDB collection: `email-knowledge`

Metadata only — **no full text**.

```json
{
  "_id": "674a1b2c3d4e5f6789012345",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "team_id": "team_123",
  "title": "Return Policy",
  "status": "indexed",
  "chunk_count": 2,
  "char_count": 1650,
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z"
}
```

| Field | Description |
|-------|-------------|
| `knowledge_id` | UUID returned by the create API — use this to delete or attach to an agent later |
| `title` | Human-readable label (e.g. "Return Policy") |
| `status` | `"indexed"` on success |
| `chunk_count` | Number of Qdrant points created |
| `char_count` | Original `knowledge_text` length |

**Indexes:** `team_id`, unique `knowledge_id`.

---

### Qdrant collection: `email-knowledge`

One **point per chunk**. Full text and vectors live here only.

**Point ID:** deterministic UUID5 from `{team_id}:email_knowledge:{knowledge_id}:{text_index}`

**Payload fields:**

| Field | Type | Description |
|-------|------|-------------|
| `team_id` | string | Team scope |
| `knowledge_id` | string | Links back to Mongo metadata |
| `text_index` | integer | Chunk order (0, 1, 2, …) |
| `text_content` | string | The actual chunk text |
| `created_at` | string (ISO) | Index timestamp |

**Payload indexes:** `team_id`, `knowledge_id`

---

### Example: short text chunked into 2 Qdrant points

Suppose `knowledge_text` is ~1650 characters (just over the 1500 limit).

**Mongo — 1 document:**

```json
{
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "team_id": "team_123",
  "title": "Return Policy",
  "status": "indexed",
  "chunk_count": 2,
  "char_count": 1650
}
```

**Qdrant — point 0 (`text_index: 0`):**

```json
{
  "id": "<uuid5>",
  "vector": [0.012, -0.034, "..."],
  "payload": {
    "team_id": "team_123",
    "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "text_index": 0,
    "text_content": "Our return policy allows customers to return unused products within 30 days... [~1500 chars]",
    "created_at": "2026-06-07T10:00:00Z"
  }
}
```

**Qdrant — point 1 (`text_index: 1`):**

```json
{
  "id": "<uuid5>",
  "vector": [0.008, 0.021, "..."],
  "payload": {
    "team_id": "team_123",
    "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "text_index": 1,
    "text_content": "...[last ~200 chars of chunk 0 overlap]...Final note: holiday purchases have an extended 45-day return window.",
    "created_at": "2026-06-07T10:00:00Z"
  }
}
```

Chunk 1 starts ~200 characters before chunk 0 ended so context is preserved across boundaries for future RAG search.

---

## 1. Create Knowledge

Chunks text, generates embeddings, stores in Qdrant, saves metadata in Mongo.

### Route

```
POST /elysium-agents/email-knowledge/v1/create
```

### Headers

```http
Content-Type: application/json
```

### Request body

```json
{
  "team_id": "team_123",
  "title": "Return Policy",
  "knowledge_text": "Our return policy allows customers to return unused products within 30 days of delivery..."
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `team_id` | string | Yes | Team this knowledge belongs to |
| `title` | string | Yes | Display name (1–256 chars) |
| `knowledge_text` | string | Yes | Full text to index (1–500,000 chars) |

### Success — `201 Created`

```json
{
  "success": true,
  "message": "Knowledge indexed successfully.",
  "knowledge": {
    "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "team_id": "team_123",
    "title": "Return Policy",
    "status": "indexed",
    "chunk_count": 2,
    "char_count": 1650,
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:00:00Z"
  }
}
```

**Frontend:** store `knowledge.knowledge_id` — you will attach it to email AI agents later.

### Error — empty text `400`

```json
{
  "success": false,
  "message": "knowledge_text cannot be empty."
}
```

### Error — validation `422`

Invalid or missing fields (e.g. empty title):

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "title"],
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
  "message": "Failed to create knowledge."
}
```

### Frontend example

```javascript
const BASE = "http://localhost:7000/elysium-agents";

async function createKnowledge(teamId, title, knowledgeText) {
  const res = await fetch(`${BASE}/email-knowledge/v1/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      team_id: teamId,
      title,
      knowledge_text: knowledgeText,
    }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to create knowledge");
  }

  return data.knowledge; // includes knowledge_id
}
```

---

## 2. List Team Knowledge

Returns metadata for all knowledge items on a team. Does **not** return chunk text (that lives in Qdrant).

### Route

```
POST /elysium-agents/email-knowledge/v1/list-team-knowledge
```

### Request body

```json
{
  "team_id": "team_123"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `team_id` | string | Yes | Team whose knowledge to list |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Team knowledge fetched successfully.",
  "team_id": "team_123",
  "count": 2,
  "knowledge_items": [
    {
      "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "team_id": "team_123",
      "title": "Return Policy",
      "status": "indexed",
      "chunk_count": 2,
      "char_count": 1650,
      "created_at": "2026-06-07T10:00:00Z",
      "updated_at": "2026-06-07T10:00:00Z"
    },
    {
      "knowledge_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "team_id": "team_123",
      "title": "Shipping FAQ",
      "status": "indexed",
      "chunk_count": 1,
      "char_count": 820,
      "created_at": "2026-06-06T14:30:00Z",
      "updated_at": "2026-06-06T14:30:00Z"
    }
  ]
}
```

### Frontend example

```javascript
async function listTeamKnowledge(teamId) {
  const res = await fetch(`${BASE}/email-knowledge/v1/list-team-knowledge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ team_id: teamId }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to list knowledge");
  }

  return data.knowledge_items;
}
```

---

## 3. Delete Knowledge

Removes all Qdrant chunks for the `knowledge_id` and deletes the Mongo metadata document.

### Route

```
POST /elysium-agents/email-knowledge/v1/delete
```

### Request body

```json
{
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `knowledge_id` | string | Yes | UUID from the create response |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Knowledge deleted successfully.",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "team_id": "team_123"
}
```

### Error — not found `404`

```json
{
  "success": false,
  "message": "Knowledge not found."
}
```

### Frontend example

```javascript
async function deleteKnowledge(knowledgeId) {
  const res = await fetch(`${BASE}/email-knowledge/v1/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to delete knowledge");
  }

  return data;
}
```

---

## 4. Query Knowledge (testing)

Retrieves the **5 most relevant text chunks** from Qdrant for a user query against a specific `knowledge_id`. Use this endpoint to test retrieval before wiring the agent.

The production email agent will call `retrieve_relevant_knowledge_chunks()` from `email_knowledge_query_services.py` directly — not this HTTP route.

### How retrieval works

```
user query
    ↓
embed query (text-embedding-3-small)
    ↓
Qdrant vector search  →  filter by knowledge_id, limit 5
    ↓
return chunks with text_content + relevance score
```

### Route

```
POST /elysium-agents/email-knowledge/v1/query
```

### Request body

```json
{
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "query": "What is the return window for holiday purchases?"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `knowledge_id` | string | Yes | UUID from the create response |
| `query` | string | Yes | User question to search against (1–10,000 chars) |

### Success — `200 OK`

```json
{
  "success": true,
  "message": "Relevant chunks retrieved successfully.",
  "knowledge_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "team_id": "team_123",
  "title": "Return Policy",
  "query": "What is the return window for holiday purchases?",
  "chunk_count": 2,
  "chunks": [
    {
      "text_index": 1,
      "text_content": "...holiday purchases have an extended 45-day return window through January 31.",
      "score": 0.87
    },
    {
      "text_index": 0,
      "text_content": "Our return policy allows customers to return unused products within 30 days...",
      "score": 0.72
    }
  ]
}
```

Chunks are sorted by **relevance score** (highest first). Up to **5** chunks are returned (`RELEVANT_CHUNKS_LIMIT`). If the knowledge has fewer than 5 chunks, all available chunks are returned.

| Chunk field | Description |
|-------------|-------------|
| `text_index` | Original chunk position in the indexed document |
| `text_content` | The chunk text to pass into the LLM context |
| `score` | Cosine similarity score from Qdrant (higher = more relevant) |

### Error — knowledge not found `404`

```json
{
  "success": false,
  "message": "Knowledge not found."
}
```

### Error — empty query `400`

```json
{
  "success": false,
  "message": "query cannot be empty."
}
```

### Testing example

```javascript
async function queryKnowledge(knowledgeId, query) {
  const res = await fetch(`${BASE}/email-knowledge/v1/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId, query }),
  });

  const data = await res.json();

  if (!res.ok || !data.success) {
    throw new Error(data.message || "Failed to query knowledge");
  }

  return data.chunks;
}
```

**Typical test flow:**

```
1. POST /v1/create        →  save knowledge_id
2. POST /v1/query         →  ask a question, inspect returned chunks
3. Verify chunks contain expected text before wiring the agent
```

---

## Code layout (for developers)

```
services/email_agent_services/email_knowledge/
├── email_knowledge_constants.py        # collection names, embedding config, chunk limit
├── email_knowledge_qdrant_services.py  # chunk, embed, upsert, search, delete in Qdrant
├── email_knowledge_mongo_services.py   # metadata CRUD (no full text)
├── email_knowledge_query_services.py   # RAG retrieval (used by agent later)
└── email_knowledge_services.py         # create / list / delete orchestration

routes/email_agent/email_knowledge_routes.py
config/email_knowledge_models.py
```

The Qdrant collection `email-knowledge` is ensured at application startup in `main.py`.

---

## RAG retrieval (for the email agent)

The main service for agent integration:

```python
from services.email_agent_services.email_knowledge.email_knowledge_query_services import (
    retrieve_relevant_knowledge_chunks,
)

result = await retrieve_relevant_knowledge_chunks(
    knowledge_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    query="What is your return policy?",
)

if result["success"]:
    chunks = result["data"]["chunks"]  # up to 5 items with text_content + score
```

When the agent replies to an email, it will call this service with the attached `knowledge_id` and the customer's question, then inject the returned `text_content` values into the LLM prompt.

---

## Related docs

- [email-ai-agent-setup.md](./email-ai-agent-setup.md) — Gmail agents and thread sync
- [email-tools-api.md](./email-tools-api.md) — agent tool APIs (ticket status lookup)
- [departments-api.md](./departments-api.md) — team departments
