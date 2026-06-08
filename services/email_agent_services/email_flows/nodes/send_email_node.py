from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import (
    DEFAULT_REPLY_ACTION,
    get_email_ai_agent_id_str,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    AI_REPLY_MODE_AUTO,
    FINAL_ACTION_TYPE_SENT,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_TYPE_SEND_EMAIL,
    REPLY_ACTION_MODE_AUTO_SEND,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    build_auto_sent_ai_action,
    build_auto_sent_ai_outcome,
    build_ai_reply,
    set_message_ai_outcome,
    tag_outbound_message_ai_reply,
    update_thread_ai_action,
)
from services.email_agent_services.email_flows.email_gmail_reply_services import (
    build_recipients_for_storage,
    build_reply_raw_mime,
    normalize_reply_action,
    persist_draft_fallback_reply,
    resolve_reply_recipients,
)
from services.email_agent_services.gmail_api_services import (
    _format_from_address,
    send_gmail_message,
)
from services.email_agent_services.gmail_token_services import (
    get_gmail_access_token_for_account,
)

logger = get_logger()

NODE_ID = "send_email"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_auto_send_min_confidence(reply_action: Dict[str, Any]) -> float:
    try:
        confidence = float(
            reply_action.get(
                "auto_send_min_confidence",
                DEFAULT_REPLY_ACTION["auto_send_min_confidence"],
            )
        )
    except (TypeError, ValueError):
        confidence = float(DEFAULT_REPLY_ACTION["auto_send_min_confidence"])
    return max(0.0, min(confidence, 1.0))


async def execute_send_email_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Auto-send tail node when reply_action.mode is auto_send.

    Sends directly via Gmail when draft.confidence >= auto_send_min_confidence;
    otherwise falls back to saving a Gmail draft (draft_fallback).
    """
    started_at = _utc_now()
    thread_id = (context.get("thread_id") or "").strip()
    team_id = (context.get("team_id") or "").strip()
    run_id = (context.get("run_id") or "").strip()
    trigger_message_id = (context.get("trigger_message_id") or "").strip()
    agent_id = get_email_ai_agent_id_str(agent)
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    reply_action = normalize_reply_action(agent)
    reply_mode = (reply_action.get("mode") or REPLY_ACTION_MODE_AUTO_SEND).strip().lower()
    auto_send_min_confidence = _resolve_auto_send_min_confidence(reply_action)

    draft = context.get("draft") or {}
    confidence = float(draft.get("confidence") or 0.0)
    resolved_recipients = resolve_reply_recipients(context)
    trigger_message = context.get("trigger_message") or {}

    input_summary = {
        "thread_id": thread_id,
        "reply_action_mode": reply_mode,
        "confidence": confidence,
        "auto_send_min_confidence": auto_send_min_confidence,
        "draft_subject": (draft.get("subject") or "").strip(),
        "draft_body_chars": len((draft.get("body_text") or "").strip()),
        "to_count": len(resolved_recipients["to"]),
        "cc_count": len(resolved_recipients["cc"]),
        "bcc_count": len(resolved_recipients["bcc"]),
        "trigger_message_id": trigger_message_id,
    }

    logger.info(
        f"send_email_node started thread_id={thread_id} confidence={confidence} "
        f"threshold={auto_send_min_confidence}"
    )

    if reply_mode != REPLY_ACTION_MODE_AUTO_SEND:
        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_SEND_EMAIL,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "skipped": True,
                "skip_reason": (
                    f"reply_action.mode is '{reply_mode}', not '{REPLY_ACTION_MODE_AUTO_SEND}'."
                ),
            },
        }
        return context, node_log

    try:
        if confidence < auto_send_min_confidence:
            logger.info(
                f"send_email_node draft fallback thread_id={thread_id} "
                f"confidence={confidence} threshold={auto_send_min_confidence}"
            )
            persist_result = await persist_draft_fallback_reply(
                context=context,
                agent=agent,
                auto_send_min_confidence=auto_send_min_confidence,
            )
            completed_at = _utc_now()
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            node_log = {
                "node_id": NODE_ID,
                "node_type": NODE_TYPE_SEND_EMAIL,
                "status": NODE_LOG_STATUS_OK,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": duration_ms,
                "input_summary": input_summary,
                "output": {
                    "path": "draft_fallback",
                    "threshold_met": False,
                    "final_action": persist_result["final_action"],
                    "ai_action": persist_result["ai_action"],
                    "gmail_draft_id": persist_result["gmail_draft_id"],
                    "recipients": persist_result["resolved_recipients"],
                },
            }
            return context, node_log

        access_token, raw_message = await build_reply_raw_mime(
            context=context,
            draft=draft,
            gmail_account_id=gmail_account_id,
            resolved_recipients=resolved_recipients,
            trigger_message=trigger_message,
        )

        send_result = await send_gmail_message(
            access_token,
            thread_id=thread_id,
            raw_message=raw_message,
        )
        if not send_result.get("success"):
            raise ValueError(send_result.get("message", "Gmail message send failed."))

        sent_data = send_result.get("data") or {}
        gmail_message_id = (sent_data.get("gmail_message_id") or "").strip()
        body_text = (draft.get("body_text") or "").strip()
        recipients_for_storage = build_recipients_for_storage(context, resolved_recipients)

        context["final_action"] = {
            "type": FINAL_ACTION_TYPE_SENT,
            "gmail_message_id": gmail_message_id,
            "confidence": confidence,
            "auto_send_min_confidence": auto_send_min_confidence,
            "threshold_met": True,
            "recipients": {
                "to": resolved_recipients["to"],
                "cc": resolved_recipients["cc"],
                "bcc": resolved_recipients["bcc"],
            },
        }

        ai_action = build_auto_sent_ai_action(
            flow_run_id=run_id,
            trigger_message_id=trigger_message_id,
            gmail_message_id=gmail_message_id,
            confidence=confidence,
            auto_send_min_confidence=auto_send_min_confidence,
            subject=(draft.get("subject") or "").strip(),
            body_text=body_text,
            recipients=recipients_for_storage,
        )
        await update_thread_ai_action(
            thread_id=thread_id,
            team_id=team_id,
            gmail_account_id=gmail_account_id,
            ai_action=ai_action,
        )

        if trigger_message_id:
            ai_outcome = build_auto_sent_ai_outcome(
                flow_run_id=run_id,
                gmail_message_id=gmail_message_id,
                confidence=confidence,
                auto_send_min_confidence=auto_send_min_confidence,
                recipients=recipients_for_storage,
            )
            await set_message_ai_outcome(trigger_message_id, ai_outcome=ai_outcome)

        if gmail_message_id:
            token_result = await get_gmail_access_token_for_account(gmail_account_id)
            sender_email = (token_result.get("email_address") or "").strip()
            sender_name = (token_result.get("display_name") or "").strip()
            from_address = _format_from_address(sender_email, sender_name)
            ai_reply_payload = build_ai_reply(
                mode=AI_REPLY_MODE_AUTO,
                flow_run_id=run_id,
                agent_id=agent_id,
                confidence=confidence,
                sender_email=sender_email,
                sender_name=sender_name,
            )
            await tag_outbound_message_ai_reply(
                gmail_message_id=gmail_message_id,
                gmail_account_id=gmail_account_id,
                thread_id=thread_id,
                team_id=team_id,
                agent_id=agent_id,
                ai_reply=ai_reply_payload,
                ai_action=ai_action,
                from_address=from_address,
                label_ids=sent_data.get("label_ids") or ["SENT"],
            )

        logger.info(
            f"send_email_node auto-sent thread_id={thread_id} "
            f"gmail_message_id={gmail_message_id} confidence={confidence}"
        )

        completed_at = _utc_now()
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        node_log = {
            "node_id": NODE_ID,
            "node_type": NODE_TYPE_SEND_EMAIL,
            "status": NODE_LOG_STATUS_OK,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {
                "path": "auto_send",
                "threshold_met": True,
                "final_action": context["final_action"],
                "ai_action": ai_action,
                "gmail_message_id": gmail_message_id,
                "recipients": resolved_recipients,
            },
        }
        return context, node_log

    except Exception as exc:
        logger.error(
            f"send_email_node failed thread_id={thread_id}: {exc}",
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
            "node_type": NODE_TYPE_SEND_EMAIL,
            "status": NODE_LOG_STATUS_FAILED,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration_ms,
            "input_summary": input_summary,
            "output": {"context": context},
            "error": str(exc),
        }
        return context, node_log
