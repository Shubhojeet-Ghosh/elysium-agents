from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import get_email_ai_agent_id_str
from services.email_agent_services.email_flows.email_flow_constants import (
    MESSAGE_PROCESSING_STATUS_PENDING,
    MESSAGE_PROCESSING_STATUS_PROCESSING,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    NODE_TYPE_START,
)
from services.email_agent_services.email_flows.email_flow_context import (
    find_latest_inbound,
    find_latest_pending_inbound,
    find_message_by_reference,
    get_stored_message_id,
    trim_message_for_llm,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    load_thread_messages_for_flow,
    mark_thread_ai_processing,
)
from services.email_agent_services.email_thread_services import EMAIL_THREAD_MESSAGES_COLLECTION
from services.mongo_services import get_collection

logger = get_logger()

NODE_ID = "start"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def set_trigger_message_processing(
    message_id: str,
    *,
    flow_run_id: str,
    processing_status: str,
) -> None:
    try:
        object_id = ObjectId(message_id.strip())
    except InvalidId:
        return

    collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
    update_fields: Dict[str, Any] = {
        "processing_status": processing_status,
        "flow_run_id": flow_run_id,
        "updated_at": _utc_now(),
    }
    if processing_status == MESSAGE_PROCESSING_STATUS_PROCESSING:
        update_fields["processed_at"] = None
    else:
        update_fields["processed_at"] = _utc_now()

    await collection.update_one({"_id": object_id}, {"$set": update_fields})


def _resolve_trigger_message(
    messages: list[Dict[str, Any]],
    trigger_message_id: str,
    *,
    prefer_pending: bool,
) -> Dict[str, Any] | None:
    if trigger_message_id.strip():
        trigger_message = find_message_by_reference(messages, trigger_message_id)
        if trigger_message:
            return trigger_message

    if prefer_pending:
        trigger_message = find_latest_pending_inbound(messages)
        if trigger_message:
            return trigger_message

    return find_latest_inbound(messages)


async def execute_start_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Validate run, resolve trigger inbound message, seed FlowContext.

    config.force_reprocess (default False): skip pending-only idempotency — for manual reprocess.
    """
    started_at = _utc_now()
    thread_id = (context.get("thread_id") or "").strip()
    team_id = (context.get("team_id") or agent.get("team_id") or "").strip()
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    trigger_message_id = (context.get("trigger_message_id") or "").strip()
    run_id = (context.get("run_id") or "").strip()
    force_reprocess = bool(config.get("force_reprocess", False))

    input_summary = {
        "thread_id": thread_id,
        "team_id": team_id,
        "agent_id": get_email_ai_agent_id_str(agent),
        "trigger_message_id": trigger_message_id,
        "force_reprocess": force_reprocess,
    }

    try:
        if agent.get("status") != "active":
            raise ValueError("Agent is not active.")

        if not thread_id or not team_id or not gmail_account_id:
            raise ValueError("thread_id, team_id, and gmail_account_id are required.")

        if not run_id:
            raise ValueError("run_id must be set on context before Start runs.")

        raw_messages = await load_thread_messages_for_flow(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
            message_limit=int(config.get("message_limit") or 50),
        )
        if not raw_messages:
            raise ValueError("No messages found for this thread.")

        trigger_message = _resolve_trigger_message(
            raw_messages,
            trigger_message_id,
            prefer_pending=not force_reprocess,
        )
        if not trigger_message:
            raise ValueError("Could not resolve a trigger inbound message for this thread.")

        if trigger_message.get("direction") != "inbound":
            raise ValueError("Trigger message must be inbound.")

        resolved_trigger_id = get_stored_message_id(trigger_message)
        processing_status = trigger_message.get("processing_status", "")
        existing_flow_run_id = trigger_message.get("flow_run_id")

        if not force_reprocess:
            if processing_status != MESSAGE_PROCESSING_STATUS_PENDING:
                completed_at = _utc_now()
                node_log = {
                    "node_id": NODE_ID,
                    "node_type": NODE_TYPE_START,
                    "status": NODE_LOG_STATUS_SKIPPED,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_ms": 0,
                    "input_summary": input_summary,
                    "output": {
                        "context": context,
                        "skip_reason": f"processing_status is '{processing_status}', expected 'pending'.",
                    },
                    "error": None,
                }
                return context, node_log

            if existing_flow_run_id:
                completed_at = _utc_now()
                node_log = {
                    "node_id": NODE_ID,
                    "node_type": NODE_TYPE_START,
                    "status": NODE_LOG_STATUS_SKIPPED,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_ms": 0,
                    "input_summary": input_summary,
                    "output": {
                        "context": context,
                        "skip_reason": "Trigger message already has a flow_run_id.",
                    },
                    "error": None,
                }
                return context, node_log

        context["agent_id"] = get_email_ai_agent_id_str(agent)
        context["team_id"] = team_id
        context["thread_id"] = thread_id
        context["trigger_message_id"] = resolved_trigger_id
        context["system_prompt"] = agent.get("system_prompt", "") or ""
        context["email_format_template"] = agent.get("email_format_template", "") or ""
        context["trigger_message"] = trim_message_for_llm(trigger_message)

        await set_trigger_message_processing(
            resolved_trigger_id,
            flow_run_id=run_id,
            processing_status=MESSAGE_PROCESSING_STATUS_PROCESSING,
        )

        await mark_thread_ai_processing(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
            flow_run_id=run_id,
            trigger_message_id=resolved_trigger_id,
        )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_START,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "context": context,
                "trigger_message_id": resolved_trigger_id,
                "force_reprocess": force_reprocess,
            },
            "error": None,
        }
        return context, node_log

    except Exception as exc:
        logger.error(f"start_node failed for thread {thread_id}: {exc}", exc_info=True)
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_START,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
