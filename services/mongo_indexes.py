from logging_config import get_logger
from services.mongo_services import get_collection
from config.settings import settings

logger = get_logger()

async def create_mongo_indexes():
    """
    Create MongoDB indexes.
    Safe to call multiple times (idempotent).
    """
    try:
        if not settings.CREATE_INDEXES:
            logger.info("Index creation is disabled in settings.")
            return
        
        # Create index for atlas_agents collection on owner_user_id
        atlas_agents_collection = get_collection("atlas_agents")
        await atlas_agents_collection.create_index("owner_user_id", name="owner_user_id_1")
        logger.info("Index created on atlas_agents.owner_user_id")

        # Create indexes for atlas_agent_urls collection
        atlas_agent_urls_collection = get_collection("atlas_agent_urls")
        await atlas_agent_urls_collection.create_index("agent_id", name="agent_id_index")
        logger.info("Index created on atlas_agent_urls.agent_id")
        await atlas_agent_urls_collection.create_index("url", name="url_index")
        logger.info("Index created on atlas_agent_urls.url")
        await atlas_agent_urls_collection.create_index([("agent_id", 1), ("updated_at", -1), ("_id", -1)], name="agent_id_updated_at_id_index")
        logger.info("Compound index created on atlas_agent_urls.agent_id, updated_at, _id for pagination")

        # Create indexes for atlas_agent_files collection
        atlas_agent_files_collection = get_collection("atlas_agent_files")
        await atlas_agent_files_collection.create_index("agent_id", name="agent_id_index_files")
        logger.info("Index created on atlas_agent_files.agent_id")
        await atlas_agent_files_collection.create_index("file_key", name="file_key_index")
        logger.info("Index created on atlas_agent_files.file_key")
        await atlas_agent_files_collection.create_index([("agent_id", 1), ("updated_at", -1), ("_id", -1)], name="agent_id_updated_at_id_index_files")
        logger.info("Compound index created on atlas_agent_files.agent_id, updated_at, _id for pagination")

        # Create indexes for atlas_custom_texts collection
        atlas_custom_texts_collection = get_collection("atlas_custom_texts")
        await atlas_custom_texts_collection.create_index("agent_id", name="agent_id_index_texts")
        logger.info("Index created on atlas_custom_texts.agent_id")
        await atlas_custom_texts_collection.create_index("custom_text_alias", name="custom_text_alias_index")
        logger.info("Index created on atlas_custom_texts.custom_text_alias")
        await atlas_custom_texts_collection.create_index([("agent_id", 1), ("updated_at", -1), ("_id", -1)], name="agent_id_updated_at_id_index_texts")
        logger.info("Compound index created on atlas_custom_texts.agent_id, updated_at, _id for pagination")

        # Create indexes for atlas_qa_pairs collection
        atlas_qa_pairs_collection = get_collection("atlas_qa_pairs")
        await atlas_qa_pairs_collection.create_index("agent_id", name="agent_id_index_qa")
        logger.info("Index created on atlas_qa_pairs.agent_id")
        await atlas_qa_pairs_collection.create_index("qna_alias", name="qna_alias_index")
        logger.info("Index created on atlas_qa_pairs.qna_alias")
        await atlas_qa_pairs_collection.create_index([("agent_id", 1), ("updated_at", -1), ("_id", -1)], name="agent_id_updated_at_id_index_qa")
        logger.info("Compound index created on atlas_qa_pairs.agent_id, updated_at, _id for pagination")

        # Create indexes for elysium_atlas_users collection
        elysium_atlas_users_collection = get_collection("elysium_atlas_users")
        await elysium_atlas_users_collection.create_index("email", name="email_1", unique=True)
        logger.info("Unique index created on elysium_atlas_users.email")

        # Create indexes for atlas_chat_sessions collection
        atlas_chat_sessions_collection = get_collection("atlas_chat_sessions")
        await atlas_chat_sessions_collection.create_index("chat_session_id", name="chat_session_id_index")
        logger.info("Index created on atlas_chat_sessions.chat_session_id")
        await atlas_chat_sessions_collection.create_index("agent_id", name="agent_id_index_chat_sessions")
        logger.info("Index created on atlas_chat_sessions.agent_id")
        await atlas_chat_sessions_collection.create_index([("chat_session_id", 1), ("agent_id", 1)], name="chat_session_id_agent_id_index")
        logger.info("Compound index created on atlas_chat_sessions.chat_session_id and agent_id")

        # Create indexes for atlas_chat_mesages collection
        atlas_chat_mesages_collection = get_collection("atlas_chat_mesages")
        await atlas_chat_mesages_collection.create_index("agent_id", name="agent_id_index_messages")
        logger.info("Index created on atlas_chat_mesages.agent_id")
        await atlas_chat_mesages_collection.create_index("chat_session_id", name="chat_session_id_index_messages")
        logger.info("Index created on atlas_chat_mesages.chat_session_id")
        await atlas_chat_mesages_collection.create_index("created_at", name="created_at_index_messages")
        logger.info("Index created on atlas_chat_mesages.created_at")
        await atlas_chat_mesages_collection.create_index([("agent_id", 1), ("chat_session_id", 1)], name="agent_id_chat_session_id_index_messages")
        logger.info("Compound index created on atlas_chat_mesages.agent_id and chat_session_id")

        logger.info("MongoDB indexes created / verified successfully.")

    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}")
        raise
