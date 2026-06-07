from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    AI_ACTION_TYPE_DRAFT,
    FINAL_ACTION_TYPE_DRAFT,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    REPLY_ACTION_MODE_DRAFT,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    build_draft_created_ai_outcome,
    build_draft_ready_ai_action,
    set_message_ai_outcome,
    update_thread_ai_action,
)
from services.email_agent_services.gmail_api_services import (
    _format_from_address,
    build_plain_text_reply_mime,
    create_gmail_draft,
)
from services.email_agent_services.gmail_token_services import (
    get_gmail_access_token_for_account,
)

logger = get_logger()

NODE_ID = "save_gmail_draft"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for value in values:
        normalized = (value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _resolve_reply_to_address(context: Dict[str, Any]) -> str:
    recipients = context.get("recipients") or {}
    to_addresses = recipients.get("to") or []
    if to_addresses:
        return (to_addresses[0] or "").strip()

    trigger_message = context.get("trigger_message") or {}
    reply_to = (trigger_message.get("reply_to") or "").strip()
    if reply_to:
        return reply_to

    latest_inbound = (context.get("thread") or {}).get("latest_inbound") or {}
    latest_reply_to = (latest_inbound.get("reply_to") or "").strip()
    if latest_reply_to:
        return latest_reply_to

    return (trigger_message.get("from") or latest_inbound.get("from") or "").strip()


def _resolve_draft_recipients(context: Dict[str, Any]) -> Dict[str, List[str]]:
    recipients = context.get("recipients") or {}
    reply_to = _resolve_reply_to_address(context)
    to_addresses = _dedupe_preserve_order(recipients.get("to") or [])
    if not to_addresses and reply_to:
        to_addresses = [reply_to]

    return {
        "to": to_addresses,
        "cc": _dedupe_preserve_order(recipients.get("cc") or []),
        "bcc": _dedupe_preserve_order(recipients.get("bcc") or []),
    }


def _build_references_header(context: Dict[str, Any], trigger_message: Dict[str, Any]) -> str:
    message_ids: List[str] = []
    thread_messages = (context.get("thread") or {}).get("messages") or []
    for message in thread_messages:
        header_value = (message.get("message_id_header") or "").strip()
        if header_value:
            message_ids.append(header_value)

    if not message_ids:
        trigger_header = (trigger_message.get("message_id_header") or "").strip()
        if trigger_header:
            message_ids.append(trigger_header)

    return " ".join(message_ids)


def _normalize_reply_action(agent: Dict[str, Any]) -> Dict[str, Any]:
    reply_action = agent.get("reply_action") or {}
    if not isinstance(reply_action, dict):
        return {"mode": REPLY_ACTION_MODE_DRAFT}
    return reply_action


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
    team_id = (context.get("team_id") or "").strip()
    run_id = (context.get("run_id") or "").strip()
    trigger_message_id = (context.get("trigger_message_id") or "").strip()
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    reply_action = _normalize_reply_action(agent)
    reply_mode = (reply_action.get("mode") or REPLY_ACTION_MODE_DRAFT).strip().lower()

    draft = context.get("draft") or {}
    recipients_snapshot = context.get("recipients") or {}
    resolved_recipients = _resolve_draft_recipients(context)
    trigger_message = context.get("trigger_message") or {}

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
        body_text = (draft.get("body_text") or "").strip()
        if not body_text:
            raise ValueError("draft.body_text is required to save a Gmail draft.")
        if not resolved_recipients["to"]:
            raise ValueError("At least one To recipient is required to save a Gmail draft.")

        token_result = await get_gmail_access_token_for_account(gmail_account_id)
        if not token_result.get("success"):
            raise ValueError(token_result.get("message", "Failed to obtain Gmail access token."))

        from_address = _format_from_address(
            token_result.get("email_address", ""),
            token_result.get("display_name", ""),
        )
        in_reply_to = (trigger_message.get("message_id_header") or "").strip()
        references = _build_references_header(context, trigger_message)
        raw_message = build_plain_text_reply_mime(
            to_addresses=resolved_recipients["to"],
            cc_addresses=resolved_recipients["cc"],
            bcc_addresses=resolved_recipients["bcc"],
            subject=(draft.get("subject") or "").strip(),
            body_text=body_text,
            from_address=from_address,
            in_reply_to=in_reply_to,
            references=references,
        )

        draft_result = await create_gmail_draft(
            token_result["access_token"],
            thread_id=thread_id,
            raw_message=raw_message,
        )
        if not draft_result.get("success"):
            raise ValueError(draft_result.get("message", "Gmail draft creation failed."))

        draft_data = draft_result.get("data") or {}
        gmail_draft_id = (draft_data.get("gmail_draft_id") or "").strip()
        gmail_draft_message_id = (draft_data.get("gmail_draft_message_id") or "").strip()
        confidence = draft.get("confidence", 0.0)

        context["final_action"] = {
            "type": FINAL_ACTION_TYPE_DRAFT,
            "gmail_draft_id": gmail_draft_id,
            "gmail_draft_message_id": gmail_draft_message_id,
            "recipients": {
                "to": resolved_recipients["to"],
                "cc": resolved_recipients["cc"],
                "bcc": resolved_recipients["bcc"],
            },
        }

        recipients_for_storage = {
            **recipients_snapshot,
            "to": resolved_recipients["to"],
            "cc": resolved_recipients["cc"],
            "bcc": resolved_recipients["bcc"],
        }

        ai_action = build_draft_ready_ai_action(
            flow_run_id=run_id,
            trigger_message_id=trigger_message_id,
            gmail_draft_id=gmail_draft_id,
            gmail_draft_message_id=gmail_draft_message_id,
            confidence=confidence,
            subject=(draft.get("subject") or "").strip(),
            body_text=body_text,
            recipients=recipients_for_storage,
            action_type=AI_ACTION_TYPE_DRAFT,
        )
        await update_thread_ai_action(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
            ai_action=ai_action,
        )

        if trigger_message_id:
            ai_outcome = build_draft_created_ai_outcome(
                flow_run_id=run_id,
                gmail_draft_id=gmail_draft_id,
                gmail_draft_message_id=gmail_draft_message_id,
                confidence=confidence,
                recipients=recipients_for_storage,
            )
            await set_message_ai_outcome(trigger_message_id, ai_outcome=ai_outcome)

        logger.info(
            f"save_gmail_draft_node completed thread_id={thread_id} "
            f"gmail_draft_id={gmail_draft_id} cc={len(resolved_recipients['cc'])} "
            f"bcc={len(resolved_recipients['bcc'])}"
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
                "final_action": context["final_action"],
                "ai_action": ai_action,
                "gmail_draft_id": gmail_draft_id,
                "recipients": resolved_recipients,
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
