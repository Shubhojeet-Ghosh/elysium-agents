"""Mongo and Qdrant collection names for team knowledge items."""

KB_URLS_COLLECTION = "atlas_kb_urls"
KB_FILES_COLLECTION = "atlas_kb_files"
KB_CUSTOM_TEXTS_COLLECTION = "atlas_kb_custom_texts"
KB_QA_PAIRS_COLLECTION = "atlas_kb_qa_pairs"
AGENT_KB_ATTACHMENTS_COLLECTION = "atlas_agent_kb_attachments"

TEAM_KNOWLEDGE_BASE_COLLECTION = "team_knowledge_base"
KB_ITEM_CATALOG_COLLECTION = "kb_item_catalog"

SOURCE_TYPE_URL = "url"
SOURCE_TYPE_FILE = "file"
SOURCE_TYPE_CUSTOM_TEXT = "custom_text"
SOURCE_TYPE_QA_PAIR = "qa_pair"

KB_SOURCE_TYPES = (
    SOURCE_TYPE_URL,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_QA_PAIR,
)

KB_STATUS_DRAFT = "draft"
KB_STATUS_INDEXING = "indexing"
KB_STATUS_READY = "ready"
KB_STATUS_FAILED = "failed"

KB_STATUSES = (KB_STATUS_DRAFT, KB_STATUS_INDEXING, KB_STATUS_READY, KB_STATUS_FAILED)

COLLECTION_BY_SOURCE_TYPE: dict[str, str] = {
    SOURCE_TYPE_URL: KB_URLS_COLLECTION,
    SOURCE_TYPE_FILE: KB_FILES_COLLECTION,
    SOURCE_TYPE_CUSTOM_TEXT: KB_CUSTOM_TEXTS_COLLECTION,
    SOURCE_TYPE_QA_PAIR: KB_QA_PAIRS_COLLECTION,
}

MAX_KB_LIST_PAGE_SIZE = 100
DEFAULT_KB_LIST_PAGE_SIZE = 20
MAX_URLS_PER_CREATE = 50

# When True, index jobs call the LLM for kb_item_catalog summaries (embedded in Qdrant).
# When False, summary is stored as null in Qdrant/Mongo; chunks in team_knowledge_base still index.
KB_ITEM_CATALOG_SUMMARY_ENABLED = False
