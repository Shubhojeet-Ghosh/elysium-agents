from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import (
    EMAIL_AI_AGENTS_COLLECTION,
    get_email_ai_agent_by_id,
    get_email_ai_agent_id_str,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    DEFAULT_THREAD_MESSAGE_LIMIT,
    MESSAGE_PROCESSING_STATUS_PENDING,
    MESSAGE_PROCESSING_STATUS_SKIPPED,
)
from services.email_agent_services.email_flows.email_flow_trigger_services import (
    SyncThreadFlowTrigger,
    run_sync_flows_for_threads,
)
from services.email_agent_services.email_thread_services import (
    EMAIL_THREAD_MESSAGES_COLLECTION,
    refresh_thread_summary,
)
from services.email_agent_services.gmail_api_services import (
    SYNC_BATCH_SIZE,
    get_gmail_thread,
    is_message_after_cutoff,
    list_thread_ids,
    parse_gmail_message,
    refresh_access_token,
)
from services.email_agent_services.gmail_oauth_services import get_gmail_account_by_id
from services.mongo_services import get_collection

logger = get_logger()


class _NewInboundThread(TypedDict):
    thread_id: str
    trigger_message_id: str
    received_at: datetime


def _track_new_inbound_thread(
    threads_with_new_inbound: Dict[str, _NewInboundThread],
    *,
    thread_id: str,
    gmail_message_id: str,
    received_at: datetime | None,
) -> None:
    """Keep the newest inbound insert per thread for a single sync-triggered flow run."""
    normalized_thread_id = thread_id.strip()
    if not normalized_thread_id or not gmail_message_id.strip():
        return

    if received_at is not None and received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    elif received_at is not None:
        received_at = received_at.astimezone(timezone.utc)
    else:
        received_at = datetime.min.replace(tzinfo=timezone.utc)

    existing = threads_with_new_inbound.get(normalized_thread_id)
    if existing is None or received_at >= existing["received_at"]:
        threads_with_new_inbound[normalized_thread_id] = {
            "thread_id": normalized_thread_id,
            "trigger_message_id": gmail_message_id.strip(),
            "received_at": received_at,
        }


def _get_sync_cutoff(agent: Dict[str, Any]) -> datetime:
    last_synced_at = agent.get("last_synced_at")
    activated_at = agent.get("activated_at")
    cutoff = last_synced_at or activated_at
    if cutoff is None:
        return datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        return cutoff.replace(tzinfo=timezone.utc)
    return cutoff.astimezone(timezone.utc)


async def _set_agent_sync_state(
    agent_id: str,
    *,
    sync_status: str,
    last_synced_at: datetime | None = None,
    last_sync_error: str | None = None,
    clear_error: bool = False,
) -> None:
    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    update_fields: Dict[str, Any] = {
        "sync_status": sync_status,
        "updated_at": datetime.now(timezone.utc),
    }

    if last_synced_at is not None:
        update_fields["last_synced_at"] = last_synced_at

    if clear_error:
        update_fields["last_sync_error"] = None
    elif last_sync_error is not None:
        update_fields["last_sync_error"] = last_sync_error

    await collection.update_one(
        {"_id": ObjectId(agent_id)},
        {"$set": update_fields},
    )


async def _store_thread_message(
    agent: Dict[str, Any],
    parsed_message: Dict[str, Any],
) -> bool:
    """Store a thread message if new. Returns True when inserted."""
    collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
    gmail_message_id = parsed_message["gmail_message_id"]
    gmail_account_id = agent.get("gmail_account_id", "")
    now = datetime.now(timezone.utc)

    existing = await collection.find_one({
        "gmail_account_id": gmail_account_id,
        "gmail_message_id": gmail_message_id,
    })
    if existing:
        now = datetime.now(timezone.utc)
        await collection.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "subject": parsed_message.get("subject", ""),
                    "from": parsed_message.get("from", ""),
                    "to": parsed_message.get("to", []),
                    "cc": parsed_message.get("cc", []),
                    "bcc": parsed_message.get("bcc", []),
                    "reply_to": parsed_message.get("reply_to", ""),
                    "message_id_header": parsed_message.get("message_id_header", ""),
                    "snippet": parsed_message.get("snippet", ""),
                    "body_text": parsed_message.get("body_text", ""),
                    "body_html": parsed_message.get("body_html", ""),
                    "received_at": parsed_message.get("received_at"),
                    "label_ids": parsed_message.get("label_ids", []),
                    "is_unread": parsed_message.get("is_unread", False),
                    "metadata": parsed_message.get("metadata", {}),
                    "direction": parsed_message.get("direction", "inbound"),
                    "updated_at": now,
                }
            },
        )
        return False

    direction = parsed_message.get("direction", "inbound")
    processing_status = (
        MESSAGE_PROCESSING_STATUS_PENDING
        if direction == "inbound"
        else MESSAGE_PROCESSING_STATUS_SKIPPED
    )

    document = {
        "agent_id": get_email_ai_agent_id_str(agent),
        "gmail_account_id": gmail_account_id,
        "team_id": agent.get("team_id", ""),
        "gmail_message_id": gmail_message_id,
        "thread_id": parsed_message.get("thread_id", ""),
        "direction": direction,
        "subject": parsed_message.get("subject", ""),
        "from": parsed_message.get("from", ""),
        "to": parsed_message.get("to", []),
        "cc": parsed_message.get("cc", []),
        "bcc": parsed_message.get("bcc", []),
        "reply_to": parsed_message.get("reply_to", ""),
        "message_id_header": parsed_message.get("message_id_header", ""),
        "snippet": parsed_message.get("snippet", ""),
        "body_text": parsed_message.get("body_text", ""),
        "body_html": parsed_message.get("body_html", ""),
        "received_at": parsed_message.get("received_at"),
        "label_ids": parsed_message.get("label_ids", []),
        "is_unread": parsed_message.get("is_unread", False),
        "metadata": parsed_message.get("metadata", {}),
        "status": "stored",
        "processing_status": processing_status,
        "flow_run_id": None,
        "processed_at": None,
        "created_at": now,
        "updated_at": now,
    }

    await collection.insert_one(document)
    return True


async def run_agent_inbox_sync(agent_id: str) -> None:
    """Background task: sync Gmail threads (inbound + outbound) and store missing messages."""
    try:
        agent = await get_email_ai_agent_by_id(agent_id)
        if not agent:
            logger.error(f"Sync failed: agent {agent_id} not found")
            return

        gmail_account = await get_gmail_account_by_id(agent.get("gmail_account_id", ""))
        if not gmail_account or gmail_account.get("status") == "revoked":
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error="Gmail inbox is missing or disconnected.",
            )
            return

        refresh_token = gmail_account.get("refresh_token")
        if not refresh_token:
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error="Gmail refresh token is missing.",
            )
            return

        token_result = await refresh_access_token(refresh_token)
        if not token_result.get("success"):
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error=token_result.get("message", "Failed to refresh access token."),
            )
            return

        access_token = token_result["data"].get("access_token")
        if not access_token:
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error="Google did not return an access token.",
            )
            return

        cutoff = _get_sync_cutoff(agent)
        is_first_sync = agent.get("last_synced_at") is None
        list_result = await list_thread_ids(
            access_token=access_token,
            cutoff=cutoff,
            max_results=SYNC_BATCH_SIZE,
        )
        if not list_result.get("success"):
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error=list_result.get("message", "Failed to list Gmail threads."),
            )
            return

        thread_ids: List[str] = list_result["data"]["thread_ids"]
        inserted_count = 0
        skipped_count = 0
        threads_processed = 0
        latest_received_at: datetime | None = None
        threads_with_new_inbound: Dict[str, _NewInboundThread] = {}

        agent_id_str = get_email_ai_agent_id_str(agent)
        gmail_account_id = agent.get("gmail_account_id", "")
        team_id = agent.get("team_id", "")

        for thread_id in thread_ids:
            thread_result = await get_gmail_thread(access_token, thread_id)
            if not thread_result.get("success"):
                await _set_agent_sync_state(
                    agent_id,
                    sync_status="error",
                    last_sync_error=thread_result.get("message", "Failed to fetch Gmail thread."),
                )
                return

            raw_messages = thread_result["data"].get("messages", []) or []
            thread_inserted = 0

            for raw_message in raw_messages:
                if not is_first_sync and not is_message_after_cutoff(raw_message, cutoff):
                    skipped_count += 1
                    continue

                parsed_message = parse_gmail_message(raw_message)
                inserted = await _store_thread_message(agent, parsed_message)
                if inserted:
                    inserted_count += 1
                    thread_inserted += 1
                    received_at = parsed_message.get("received_at")
                    if isinstance(received_at, datetime):
                        if received_at.tzinfo is None:
                            received_at = received_at.replace(tzinfo=timezone.utc)
                        if latest_received_at is None or received_at > latest_received_at:
                            latest_received_at = received_at
                    if parsed_message.get("direction") == "inbound":
                        _track_new_inbound_thread(
                            threads_with_new_inbound,
                            thread_id=thread_id,
                            gmail_message_id=parsed_message.get("gmail_message_id", ""),
                            received_at=received_at if isinstance(received_at, datetime) else None,
                        )
                else:
                    skipped_count += 1

            if thread_inserted > 0:
                await refresh_thread_summary(
                    thread_id=thread_id,
                    team_id=team_id,
                    agent_id=agent_id_str,
                    gmail_account_id=gmail_account_id,
                )
                threads_processed += 1

        flow_summary: Dict[str, Any] | None = None
        thread_triggers: List[SyncThreadFlowTrigger] = [
            {
                "thread_id": item["thread_id"],
                "trigger_message_id": item["trigger_message_id"],
            }
            for item in threads_with_new_inbound.values()
        ]

        if thread_triggers:
            logger.info(
                f"Agent {agent_id} running sync-triggered flows for "
                f"{len(thread_triggers)} thread(s)"
            )
            flow_summary = await run_sync_flows_for_threads(
                agent_id=agent_id,
                thread_triggers=thread_triggers,
                message_limit=DEFAULT_THREAD_MESSAGE_LIMIT,
            )

        new_synced_at = latest_received_at or datetime.now(timezone.utc)
        await _set_agent_sync_state(
            agent_id,
            sync_status="idle",
            last_synced_at=new_synced_at,
            clear_error=True,
        )

        flow_log = ""
        if flow_summary is not None:
            flow_log = (
                f", flows={{total={flow_summary['threads_processed']}, "
                f"completed={flow_summary['completed']}, "
                f"failed={flow_summary['failed']}, "
                f"skipped={flow_summary['skipped']}}}"
            )

        logger.info(
            f"Agent {agent_id} thread sync complete: threads={threads_processed}, "
            f"inserted={inserted_count}, skipped={skipped_count}{flow_log}"
        )

    except Exception as e:
        logger.error(f"Agent {agent_id} sync failed: {e}", exc_info=True)
        try:
            await _set_agent_sync_state(
                agent_id,
                sync_status="error",
                last_sync_error="Unexpected error during inbox sync.",
            )
        except Exception as state_error:
            logger.error(f"Failed to update sync error state for agent {agent_id}: {state_error}")


async def start_agent_inbox_sync(
    agent_id: str,
    user_id: str,
    team_id: str,
) -> Dict[str, Any]:
    """Validate agent and mark sync as started. Background task does the fetch."""
    normalized_agent_id = agent_id.strip()

    try:
        try:
            ObjectId(normalized_agent_id)
        except InvalidId:
            return {
                "success": False,
                "status_code": 400,
                "message": "Invalid agent_id.",
            }

        agent = await get_email_ai_agent_by_id(normalized_agent_id)
        if not agent:
            return {
                "success": False,
                "status_code": 404,
                "message": "Email AI agent not found.",
            }

        if agent.get("team_id") != team_id.strip():
            return {
                "success": False,
                "status_code": 403,
                "message": "Agent does not belong to your team.",
            }

        if agent.get("status") != "active":
            return {
                "success": False,
                "status_code": 400,
                "message": "Agent is not active.",
            }

        if agent.get("sync_status") == "syncing":
            return {
                "success": False,
                "status_code": 409,
                "message": "Sync is already in progress for this agent.",
            }

        await _set_agent_sync_state(normalized_agent_id, sync_status="syncing", clear_error=True)

        return {
            "success": True,
            "status_code": 202,
            "message": "Inbox sync started.",
            "data": {
                "agent_id": normalized_agent_id,
                "sync_status": "syncing",
            },
        }

    except Exception as e:
        logger.error(f"Failed to start sync for agent {normalized_agent_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to start inbox sync.",
        }
