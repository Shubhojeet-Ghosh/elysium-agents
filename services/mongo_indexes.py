from logging_config import get_logger
from services.mongo_services import get_collection
from config.settings import settings

logger = get_logger()

EMAIL_USERS_COLLECTION = "email-users"
EMAIL_THREADS_COLLECTION = "email-threads"
EMAIL_DEPARTMENTS_COLLECTION = "email-departments"


async def backfill_email_user_roles() -> None:
    """Set role=admin on legacy email-users documents that do not have a role field."""
    try:
        email_users_collection = get_collection(EMAIL_USERS_COLLECTION)
        backfill_result = await email_users_collection.update_many(
            {"role": {"$exists": False}},
            {"$set": {"role": "admin"}},
        )
        if backfill_result.modified_count:
            logger.info(
                f"Backfilled role=admin on {backfill_result.modified_count} email-users document(s)"
            )
    except Exception as e:
        logger.error(f"Failed to backfill email user roles: {e}")
        raise


async def backfill_email_thread_assignment_fields() -> None:
    """Set empty department_id and assigned_user_id on legacy email-threads documents."""
    try:
        email_threads_collection = get_collection(EMAIL_THREADS_COLLECTION)

        department_backfill = await email_threads_collection.update_many(
            {"department_id": {"$exists": False}},
            {"$set": {"department_id": ""}},
        )
        if department_backfill.modified_count:
            logger.info(
                "Backfilled department_id on "
                f"{department_backfill.modified_count} email-threads document(s)"
            )

        assigned_user_backfill = await email_threads_collection.update_many(
            {"assigned_user_id": {"$exists": False}},
            {"$set": {"assigned_user_id": ""}},
        )
        if assigned_user_backfill.modified_count:
            logger.info(
                "Backfilled assigned_user_id on "
                f"{assigned_user_backfill.modified_count} email-threads document(s)"
            )
    except Exception as e:
        logger.error(f"Failed to backfill email thread assignment fields: {e}")
        raise


async def backfill_department_team_ids() -> None:
    """Infer team_id on legacy email-departments documents from linked email-users."""
    try:
        departments_collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)
        users_collection = get_collection(EMAIL_USERS_COLLECTION)
        backfilled_count = 0

        async for department in departments_collection.find({"team_id": {"$exists": False}}):
            department_id = str(department["_id"])
            user = await users_collection.find_one({"department_id": department_id})
            team_id = (user or {}).get("team_id", "").strip()
            if not team_id:
                continue

            await departments_collection.update_one(
                {"_id": department["_id"]},
                {"$set": {"team_id": team_id}},
            )
            backfilled_count += 1

        if backfilled_count:
            logger.info(
                f"Backfilled team_id on {backfilled_count} email-departments document(s)"
            )
    except Exception as e:
        logger.error(f"Failed to backfill department team_id values: {e}")
        raise


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
        await atlas_chat_sessions_collection.create_index("team_member_ids", name="team_member_ids_index")
        logger.info("Index created on atlas_chat_sessions.team_member_ids")
        await atlas_chat_sessions_collection.create_index("last_message_at", name="last_message_at_index")
        logger.info("Index created on atlas_chat_sessions.last_message_at")

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

        # Create indexes for email-users collection
        email_users_collection = get_collection("email-users")
        await email_users_collection.create_index("email", name="email_1", unique=True)
        logger.info("Unique index created on email-users.email")
        await email_users_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-users.team_id")
        await email_users_collection.create_index("department_id", name="department_id_1")
        logger.info("Index created on email-users.department_id")

        # Create indexes for email-departments collection
        email_departments_collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)
        await email_departments_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-departments.team_id")

        # Create indexes for email-gmail_accounts collection
        email_gmail_accounts_collection = get_collection("email-gmail_accounts")
        await email_gmail_accounts_collection.create_index(
            [("user_id", 1), ("email_address", 1)],
            name="user_id_email_address_1",
            unique=True,
        )
        logger.info("Unique compound index created on email-gmail_accounts.user_id + email_address")
        await email_gmail_accounts_collection.create_index("user_id", name="user_id_1")
        logger.info("Index created on email-gmail_accounts.user_id")
        await email_gmail_accounts_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-gmail_accounts.team_id")

        # Create indexes for email-ai-agents collection
        email_ai_agents_collection = get_collection("email-ai-agents")
        await email_ai_agents_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-ai-agents.team_id")
        await email_ai_agents_collection.create_index("gmail_account_id", name="gmail_account_id_1")
        logger.info("Index created on email-ai-agents.gmail_account_id")
        await email_ai_agents_collection.create_index("user_id", name="user_id_1")
        logger.info("Index created on email-ai-agents.user_id")
        await email_ai_agents_collection.create_index("sync_status", name="sync_status_1")
        logger.info("Index created on email-ai-agents.sync_status")

        # Create indexes for email-thread-messages collection
        email_thread_messages_collection = get_collection("email-thread-messages")
        await email_thread_messages_collection.create_index(
            [("gmail_account_id", 1), ("gmail_message_id", 1)],
            name="gmail_account_id_gmail_message_id_1",
            unique=True,
        )
        logger.info("Unique compound index created on email-thread-messages.gmail_account_id + gmail_message_id")
        await email_thread_messages_collection.create_index("thread_id", name="thread_id_1")
        logger.info("Index created on email-thread-messages.thread_id")
        await email_thread_messages_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-thread-messages.team_id")
        await email_thread_messages_collection.create_index(
            [("team_id", 1), ("thread_id", 1), ("received_at", 1)],
            name="team_id_thread_id_received_at_1",
        )
        logger.info("Compound index created on email-thread-messages.team_id + thread_id + received_at")

        # Create indexes for email-threads collection
        email_threads_collection = get_collection("email-threads")
        await email_threads_collection.create_index(
            [("gmail_account_id", 1), ("thread_id", 1)],
            name="gmail_account_id_thread_id_1",
            unique=True,
        )
        logger.info("Unique compound index created on email-threads.gmail_account_id + thread_id")
        await email_threads_collection.create_index("team_id", name="team_id_1")
        logger.info("Index created on email-threads.team_id")
        await email_threads_collection.create_index(
            [("team_id", 1), ("last_message_at", -1)],
            name="team_id_last_message_at_1",
        )
        logger.info("Compound index created on email-threads.team_id + last_message_at")

        # Create indexes for email-user-department-mapping collection
        email_user_department_mapping_collection = get_collection("email-user-department-mapping")
        await email_user_department_mapping_collection.create_index("user_id", name="user_id_1", unique=True)
        logger.info("Unique index created on email-user-department-mapping.user_id")
        await email_user_department_mapping_collection.create_index("department_id", name="department_id_1")
        logger.info("Index created on email-user-department-mapping.department_id")

        logger.info("MongoDB indexes created / verified successfully.")

    except Exception as e:
        logger.error(f"Failed to create MongoDB indexes: {e}")
        raise
