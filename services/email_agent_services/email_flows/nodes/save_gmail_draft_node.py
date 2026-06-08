from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    AI_ACTION_TYPE_DRAFT,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    REPLY_ACTION_MODE_DRAFT,
)
from services.email_agent_services.email_flows.email_gmail_reply_services import (
    normalize_reply_action,
    persist_gmail_draft_reply,
    resolve_reply_recipients,
)

logger = get_logger()

NODE_ID = "save_gmail_draft"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def execute_save_gmail_draft_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Save the generated reply as a Gmail draft on the thread when reply_action.mode is draft.

    Writes context.final_action and persists ai_action on email-threads plus ai_outcome
    on the trigger inbound message.
    """
    started_at = _utc_now()
    thread_id = (context.get("thread_id") or "").strip()
    reply_action = normalize_reply_action(agent)
    reply_mode = (reply_action.get("mode") or REPLY_ACTION_MODE_DRAFT).strip().lower()

    draft = context.get("draft") or {}
    resolved_recipients = resolve_reply_recipients(context)
    trigger_message_id = (context.get("trigger_message_id") or "").strip()

    input_summary = {
        "thread_id": thread_id,
        "reply_action_mode": reply_mode,
        "draft_subject": (draft.get("subject") or "").strip(),
        "draft_body_chars": len((draft.get("body_text") or "").strip()),
        "to_count": len(resolved_recipients["to"]),
        "cc_count": len(resolved_recipients["cc"]),
        "bcc_count": len(resolved_recipients["bcc"]),
        "trigger_message_id": trigger_message_id,
    }

    logger.info(
        f"save_gmail_draft_node started thread_id={thread_id} reply_mode={reply_mode}"
    )

    if reply_mode != REPLY_ACTION_MODE_DRAFT:
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_SAVE_GMAIL_DRAFT,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "skipped": True,
                "skip_reason": f"reply_action.mode is '{reply_mode}', not '{REPLY_ACTION_MODE_DRAFT}'.",
            },
        }
        return context, node_log

    try:
        persist_result = await persist_gmail_draft_reply(
            context=context,
            agent=agent,
            action_type=AI_ACTION_TYPE_DRAFT,
        )

        logger.info(
            f"save_gmail_draft_node completed thread_id={thread_id} "
            f"gmail_draft_id={persist_result['gmail_draft_id']} "
            f"cc={len(persist_result['resolved_recipients']['cc'])} "
            f"bcc={len(persist_result['resolved_recipients']['bcc'])}"
        )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_SAVE_GMAIL_DRAFT,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "final_action": persist_result["final_action"],
                "ai_action": persist_result["ai_action"],
                "gmail_draft_id": persist_result["gmail_draft_id"],
                "recipients": persist_result["resolved_recipients"],
            },
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"save_gmail_draft_node failed thread_id={thread_id}: {exc}",
            exc_info=True,
        )
        context.setdefault("errors", []).append({
            "node_id": NODE_ID,
            "message": str(exc),
        })
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_SAVE_GMAIL_DRAFT,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
