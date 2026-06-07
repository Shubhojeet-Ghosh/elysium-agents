from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
)
from services.email_agent_services.email_flows.email_flow_context import (
    annotate_messages_for_flow,
    find_latest_inbound,
    find_latest_pending_inbound,
    find_message_by_reference,
    get_stored_message_id,
    trim_message_for_llm,
)
from services.email_agent_services.email_flows.email_thread_compress_llm_services import (
    compress_thread_query_with_llm,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    get_thread_summary_for_flow,
    load_thread_messages_for_flow,
)

logger = get_logger()

NODE_ID = "load_thread_context"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_trigger_message(
    messages: list[Dict[str, Any]],
    trigger_message_id: str,
) -> Dict[str, Any] | None:
    if trigger_message_id.strip():
        trigger_message = find_message_by_reference(messages, trigger_message_id)
        if trigger_message:
            return trigger_message

    trigger_message = find_latest_pending_inbound(messages)
    if trigger_message:
        return trigger_message

    return find_latest_inbound(messages)


async def execute_load_thread_context_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Load the full thread from Mongo, flag new inbound messages, and build compressed_query.

    Returns (updated_context, node_log_output).
    """
    started_at = _utc_now()
    thread_id = (context.get("thread_id") or "").strip()
    team_id = (context.get("team_id") or agent.get("team_id") or "").strip()
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    trigger_message_id = (context.get("trigger_message_id") or "").strip()
    message_limit = int(config.get("message_limit") or 10)

    input_summary = {
        "thread_id": thread_id,
        "team_id": team_id,
        "gmail_account_id": gmail_account_id,
        "trigger_message_id": trigger_message_id,
        "message_limit": message_limit,
    }

    try:
        if not thread_id or not team_id or not gmail_account_id:
            raise ValueError("thread_id, team_id, and gmail_account_id are required.")

        raw_messages = await load_thread_messages_for_flow(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
            message_limit=message_limit,
        )
        if not raw_messages:
            raise ValueError("No messages found for this thread.")

        trigger_message = _resolve_trigger_message(raw_messages, trigger_message_id)
        if not trigger_message:
            raise ValueError("Could not resolve a trigger inbound message for this thread.")

        resolved_trigger_id = get_stored_message_id(trigger_message)
        annotated_messages = annotate_messages_for_flow(
            raw_messages,
            trigger_message_id=resolved_trigger_id,
        )

        thread_summary = await get_thread_summary_for_flow(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
        )

        subject = ""
        participants: list[str] = []
        department_id = ""
        assigned_user_id = ""

        if thread_summary:
            subject = thread_summary.get("subject", "") or ""
            participants = thread_summary.get("participants", []) or []
            department_id = thread_summary.get("department_id", "") or ""
            assigned_user_id = thread_summary.get("assigned_user_id", "") or ""
        else:
            for message in annotated_messages:
                if message.get("subject"):
                    subject = message["subject"]
                    break

        trimmed_messages = [trim_message_for_llm(message) for message in annotated_messages]
        latest_inbound_trimmed = trim_message_for_llm(trigger_message)

        compress_result = await compress_thread_query_with_llm(
            subject=subject,
            messages=annotated_messages,
            trigger_message=trigger_message,
        )
        compressed_query = compress_result["compressed_query"]

        new_message_count = sum(1 for message in trimmed_messages if message.get("is_new"))
        total_stored_count = len(raw_messages)

        context["trigger_message_id"] = resolved_trigger_id
        context["trigger_message"] = latest_inbound_trimmed
        context["compressed_query"] = compressed_query
        context["compressed_query_meta"] = {
            "source": compress_result.get("source"),
            "model": compress_result.get("model"),
            "attempts": compress_result.get("attempts"),
        }
        context["thread"] = {
            "thread_id": thread_id,
            "subject": subject,
            "participants": participants,
            "message_count": total_stored_count,
            "messages_loaded": len(trimmed_messages),
            "messages": trimmed_messages,
            "latest_inbound": latest_inbound_trimmed,
            "department_id": department_id,
            "assigned_user_id": assigned_user_id,
            "new_message_count": new_message_count,
        }

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_LOAD_THREAD_CONTEXT,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "context": context,
                "thread_summary": {
                    "thread_id": thread_id,
                    "subject": subject,
                    "message_count": total_stored_count,
                    "messages_loaded": len(trimmed_messages),
                    "new_message_count": new_message_count,
                    "trigger_message_id": resolved_trigger_id,
                },
                "compressed_query": compressed_query,
                "compressed_query_meta": context["compressed_query_meta"],
                "llm_input_preview": compress_result.get("llm_input_preview", ""),
                "downstream_hints": {
                    "read_kb": {
                        "uses": ["compressed_query", "agent.knowledge_id"],
                        "compressed_query_preview": compressed_query,
                    },
                    "generate_email": {
                        "uses": ["thread", "system_prompt", "kb_chunks"],
                    },
                },
            },
            "error": None,
        }
        return context, node_log

    except Exception as exc:
        logger.error(f"load_thread_context_node failed for thread {thread_id}: {exc}", exc_info=True)
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })

        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_LOAD_THREAD_CONTEXT,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
