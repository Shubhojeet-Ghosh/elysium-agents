from qdrant_client.models import Distance, VectorParams
from logging_config import get_logger
from services.qdrant_services import get_qdrant_client_instance

logger = get_logger()

# Collection constants
AGENT_KNOWLEDGE_BASE_COLLECTION_NAME = "agent_knowledge_base"
# Embedding dimension for text-embedding-3-small
EMBEDDING_DIM = 1536
EMBEDDING_MODEL = "text-embedding-3-small"

# Reference dictionary for point structure in agent_knowledge_base collection
# This is for developer reference only - documents the complete structure of points
AGENT_KNOWLEDGE_BASE_POINT_PAYLOAD_KEYS = {
    "vector": {
        "required": True,
        "type": "list[float]",
        "dimension": EMBEDDING_DIM,
        "model": EMBEDDING_MODEL,
        "source_key": "text_content",
        "description": f"Vector embeddings of the text_content field. Generated using {EMBEDDING_MODEL} model with dimension {EMBEDDING_DIM}. The vector represents the semantic meaning of the text_content."
    },
    "payload": {
        "agent_id": {
            "required": True,
            "type": "string",
            "description": "The ID of the agent that owns this knowledge chunk"
        },
        "knowledge_source": {
            "required": True,
            "type": "string",
            "description": "The source identifier for this knowledge chunk (e.g., URL for web content, file path for files, etc.)"
        },
        "text_index": {
            "required": True,
            "type": "integer",
            "description": "The index of this text chunk within the original document (0, 1, 2, ...) to maintain order"
        },
        "text_content": {
            "required": True,
            "type": "string",
            "description": "The actual text content chunk that was indexed. This is the source text from which the vector embeddings were generated."
        },
        "knowledge_type": {
            "required": False,
            "type": "string",
            "description": "The type of knowledge this chunk represents"
        },
        "created_at": {
            "required": False,
            "type": "string (ISO format)",
            "description": "Timestamp when this point was created"
        }
    }
}

# Track if collection has been ensured
_collection_ensured = False


async def ensure_agent_knowledge_base_collection_exists():
    """
    Ensure the Qdrant collection 'agent_knowledge_base' exists, create it if it doesn't.
    Also ensures payload indexes exist for agent_id and knowledge_source fields.
    This function is idempotent and can be called multiple times safely.
    """
    global _collection_ensured
    
    # If already ensured, return early
    if _collection_ensured:
        return
    
    try:
        client = get_qdrant_client_instance()
        
        # Check if collection exists
        collections = await client.get_collections()
        collection_names = [col.name for col in collections.collections]
        
        collection_created = False
        if AGENT_KNOWLEDGE_BASE_COLLECTION_NAME not in collection_names:
            # Create collection with embedding vector config
            await client.create_collection(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"Created Qdrant collection: {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME} with dimension {EMBEDDING_DIM}")
            collection_created = True
        
        # Create payload indexes for agent_id and knowledge_source if they don't exist
        # These indexes are required for filtering
        try:
            # Create index for agent_id (keyword type for exact matching)
            await client.create_payload_index(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                field_name="agent_id",
                field_schema="keyword"
            )
            # logger.info(f"Created payload index for 'agent_id' in collection {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME}")
        except Exception as e:
            # Index might already exist, which is fine
            error_msg = str(e).lower()
            if "already exists" not in error_msg and "index already" not in error_msg:
                # logger.debug(f"Payload index for 'agent_id' may already exist: {e}")
                pass
        
        try:
            # Create index for knowledge_source (keyword type for exact matching)
            await client.create_payload_index(
                collection_name=AGENT_KNOWLEDGE_BASE_COLLECTION_NAME,
                field_name="knowledge_source",
                field_schema="keyword"
            )
            # logger.info(f"Created payload index for 'knowledge_source' in collection {AGENT_KNOWLEDGE_BASE_COLLECTION_NAME}")
        except Exception as e:
            # Index might already exist, which is fine
            error_msg = str(e).lower()
            if "already exists" not in error_msg and "index already" not in error_msg:
                # logger.debug(f"Payload index for 'knowledge_source' may already exist: {e}")
                pass
        
        # Mark as ensured after successful completion
        _collection_ensured = True
            
    except Exception as e:
        logger.error(f"Error ensuring agent knowledge base collection exists: {e}")
        raise


# Note: Collection is automatically ensured during application startup in main.py
# The ensure_agent_knowledge_base_collection_exists() function is idempotent
# and can be called multiple times safely

