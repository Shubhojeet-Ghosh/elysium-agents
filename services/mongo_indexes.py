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
        await atlas_agents_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on atlas_agents.team_id")

        # Team RBAC lookup indexes (shared with Express Atlas API)
        atlas_team_members_collection = get_collection("atlas_team_members")
        await atlas_team_members_collection.create_index(
            [("team_id", 1), ("user_id", 1), ("status", 1)],
            name="team_id_user_id_status_1",
        )
        logger.info("Compound index created on atlas_team_members.team_id, user_id, status")

        from config.kb_item_constants import (
            AGENT_KB_ATTACHMENTS_COLLECTION,
            KB_CUSTOM_TEXTS_COLLECTION,
            KB_FILES_COLLECTION,
            KB_QA_PAIRS_COLLECTION,
            KB_URLS_COLLECTION,
        )

        atlas_kb_urls = get_collection(KB_URLS_COLLECTION)
        await atlas_kb_urls.create_index("team_id", name="team_id_1")
        await atlas_kb_urls.create_index("url", name="url_1")
        await atlas_kb_urls.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_1",
        )
        logger.info(f"Indexes created on {KB_URLS_COLLECTION}")

        atlas_kb_files = get_collection(KB_FILES_COLLECTION)
        await atlas_kb_files.create_index("team_id", name="team_id_1")
        await atlas_kb_files.create_index("file_key", name="file_key_1")
        await atlas_kb_files.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_1",
        )
        logger.info(f"Indexes created on {KB_FILES_COLLECTION}")

        atlas_kb_custom_texts = get_collection(KB_CUSTOM_TEXTS_COLLECTION)
        await atlas_kb_custom_texts.create_index("team_id", name="team_id_1")
        await atlas_kb_custom_texts.create_index(
            [("team_id", 1), ("custom_text_alias", 1)],
            name="team_id_custom_text_alias_1",
            unique=True,
        )
        await atlas_kb_custom_texts.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_1",
        )
        logger.info(f"Indexes created on {KB_CUSTOM_TEXTS_COLLECTION}")

        atlas_kb_qa_pairs = get_collection(KB_QA_PAIRS_COLLECTION)
        await atlas_kb_qa_pairs.create_index("team_id", name="team_id_1")
        await atlas_kb_qa_pairs.create_index(
            [("team_id", 1), ("qna_alias", 1)],
            name="team_id_qna_alias_1",
            unique=True,
        )
        await atlas_kb_qa_pairs.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_1",
        )
        logger.info(f"Indexes created on {KB_QA_PAIRS_COLLECTION}")

        atlas_agent_kb_attachments = get_collection(AGENT_KB_ATTACHMENTS_COLLECTION)
        await atlas_agent_kb_attachments.create_index(
            [("agent_id", 1), ("kb_id", 1)],
            name="agent_id_kb_id_1",
            unique=True,
        )
        await atlas_agent_kb_attachments.create_index("kb_id", name="kb_id_1")
        await atlas_agent_kb_attachments.create_index(
            [("agent_id", 1), ("attached_at", -1)],
            name="agent_id_attached_at_1",
        )
        await atlas_agent_kb_attachments.create_index(
            [("team_id", 1), ("agent_id", 1)],
            name="team_id_agent_id_1",
        )
        logger.info(f"Indexes created on {AGENT_KB_ATTACHMENTS_COLLECTION}")

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
        await atlas_chat_sessions_collection.create_index("team_member_ids", name="team_member_ids_index")
        logger.info("Index created on atlas_chat_sessions.team_member_ids")
        await atlas_chat_sessions_collection.create_index("last_message_at", name="last_message_at_index")
        logger.info("Index created on atlas_chat_sessions.last_message_at")
        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("last_message_at", -1), ("last_connected_at", -1), ("created_at", -1)],
            name="agent_id_last_message_at_index",
        )
        logger.info("Compound index created on atlas_chat_sessions.agent_id and last_message_at")
        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("status", 1), ("last_message_at", -1)],
            name="agent_id_status_last_message_at_index",
        )
        logger.info(
            "Compound index created on atlas_chat_sessions.agent_id, status, last_message_at"
        )
        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("in_conversation_with", 1)],
            name="agent_id_in_conversation_with_index",
        )
        logger.info(
            "Compound index created on atlas_chat_sessions.agent_id, in_conversation_with"
        )
        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("resolved_at", -1)],
            name="agent_id_resolved_at_index",
            partialFilterExpression={"status": "resolved"},
        )
        logger.info(
            "Partial index created on atlas_chat_sessions.agent_id, resolved_at "
            "(status=resolved only)"
        )

        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("visitor_online", 1)],
            name="agent_id_visitor_online_index",
        )
        logger.info("Compound index created on atlas_chat_sessions.agent_id and visitor_online")
        await atlas_chat_sessions_collection.create_index(
            [("agent_id", 1), ("handover.status", 1)],
            name="agent_id_handover_status_index",
        )
        logger.info(
            "Compound index created on atlas_chat_sessions.agent_id and handover.status"
        )

        atlas_team_member_presence_collection = get_collection("atlas_team_member_presence")
        await atlas_team_member_presence_collection.create_index(
            [("user_id", 1), ("team_id", 1)],
            name="user_team_presence_unique",
            unique=True,
        )
        logger.info(
            "Unique compound index created on atlas_team_member_presence (user_id, team_id)"
        )
        await atlas_team_member_presence_collection.create_index(
            [("active_agent_ids", 1), ("status", 1)],
            name="active_agent_ids_status_presence_index",
        )
        logger.info(
            "Compound index created on atlas_team_member_presence.active_agent_ids and status"
        )

        # Create indexes for atlas_chat_session_audits collection
        atlas_chat_session_audits_collection = get_collection("atlas_chat_session_audits")
        await atlas_chat_session_audits_collection.create_index(
            "audit_id",
            name="audit_id_unique_index",
            unique=True,
        )
        logger.info("Unique index created on atlas_chat_session_audits.audit_id")
        await atlas_chat_session_audits_collection.create_index(
            [("agent_id", 1), ("chat_session_id", 1), ("created_at", -1)],
            name="agent_id_chat_session_id_created_at_index",
        )
        logger.info(
            "Compound index created on atlas_chat_session_audits.agent_id, chat_session_id, created_at"
        )
        await atlas_chat_session_audits_collection.create_index(
            [("agent_id", 1), ("created_at", -1)],
            name="agent_id_created_at_index_audits",
        )
        logger.info("Compound index created on atlas_chat_session_audits.agent_id and created_at")
        await atlas_chat_session_audits_collection.create_index(
            [("agent_id", 1), ("event_type", 1), ("created_at", -1)],
            name="agent_id_event_type_created_at_index_audits",
        )
        logger.info(
            "Compound index created on atlas_chat_session_audits.agent_id, event_type, created_at"
        )
        await atlas_chat_session_audits_collection.create_index(
            [("agent_id", 1), ("actor_user_id", 1), ("created_at", -1)],
            name="agent_id_actor_user_id_created_at_index_audits",
            partialFilterExpression={"actor_user_id": {"$type": "string"}},
        )
        logger.info(
            "Partial compound index created on atlas_chat_session_audits.agent_id, "
            "actor_user_id, created_at"
        )
        await atlas_chat_session_audits_collection.create_index(
            [("chat_session_id", 1), ("created_at", -1)],
            name="chat_session_id_created_at_index_audits",
        )
        logger.info(
            "Compound index created on atlas_chat_session_audits.chat_session_id, created_at"
        )

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

        atlas_tools_collection = get_collection("atlas_tools")
        await atlas_tools_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on atlas_tools.team_id")
        await atlas_tools_collection.create_index(
            [("team_id", 1), ("name", 1)],
            name="team_id_name_1",
            unique=True,
        )
        logger.info("Unique compound index created on atlas_tools.team_id, name")
        await atlas_tools_collection.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_1",
        )
        logger.info("Compound index created on atlas_tools.team_id, updated_at, _id")

        atlas_support_tickets_collection = get_collection("atlas_support_tickets")
        await atlas_support_tickets_collection.create_index(
            "ticket_number",
            name="ticket_number_1",
            unique=True,
        )
        logger.info("Unique index created on atlas_support_tickets.ticket_number")
        await atlas_support_tickets_collection.create_index(
            [("team_id", 1), ("created_by_user_id", 1), ("last_activity_at", -1)],
            name="team_id_created_by_user_id_last_activity_at_1",
        )
        logger.info(
            "Compound index created on atlas_support_tickets.team_id, "
            "created_by_user_id, last_activity_at"
        )
        await atlas_support_tickets_collection.create_index(
            [("team_id", 1), ("created_by_user_id", 1), ("status", 1)],
            name="team_id_created_by_user_id_status_1",
        )
        logger.info(
            "Compound index created on atlas_support_tickets.team_id, "
            "created_by_user_id, status"
        )

        from config.lead_collection_constants import ATLAS_LEADS_COLLECTION

        atlas_leads_collection = get_collection(ATLAS_LEADS_COLLECTION)
        await atlas_leads_collection.create_index(
            [("agent_id", 1), ("chat_session_id", 1)],
            name="agent_id_chat_session_id_unique",
            unique=True,
        )
        logger.info(
            f"Unique compound index created on {ATLAS_LEADS_COLLECTION}.agent_id, chat_session_id"
        )
        await atlas_leads_collection.create_index(
            [("agent_id", 1), ("status", 1), ("completed_at", -1)],
            name="agent_id_status_completed_at_index",
        )
        logger.info(
            f"Compound index created on {ATLAS_LEADS_COLLECTION}.agent_id, status, completed_at"
        )
        await atlas_leads_collection.create_index(
            [("agent_id", 1), ("fields.email", 1)],
            name="agent_id_fields_email_index",
        )
        logger.info(
            f"Compound index created on {ATLAS_LEADS_COLLECTION}.agent_id, fields.email"
        )
        await atlas_leads_collection.create_index(
            [("team_id", 1), ("agent_id", 1), ("updated_at", -1)],
            name="team_id_agent_id_updated_at_index",
        )
        logger.info(
            f"Compound index created on {ATLAS_LEADS_COLLECTION}.team_id, agent_id, updated_at"
        )
        await atlas_leads_collection.create_index(
            [("team_id", 1), ("updated_at", -1), ("_id", -1)],
            name="team_id_updated_at_id_index",
        )
        logger.info(
            f"Compound index created on {ATLAS_LEADS_COLLECTION}.team_id, updated_at, _id"
        )

        logger.info("MongoDB indexes created / verified successfully.")

    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}")
        raise
