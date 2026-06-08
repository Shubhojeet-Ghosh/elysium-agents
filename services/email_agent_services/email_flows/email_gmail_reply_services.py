import re
from typing import Any, Dict, List, Set, Tuple

from services.email_agent_services.email_flows.email_flow_constants import (
    AI_ACTION_TYPE_DRAFT,
    AI_ACTION_TYPE_DRAFT_FALLBACK,
    AI_OUTCOME_DRAFT_CREATED,
    FALLBACK_REASON_CONFIDENCE_BELOW_THRESHOLD,
    FINAL_ACTION_TYPE_DRAFT,
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


def normalize_reply_action(agent: Dict[str, Any]) -> Dict[str, Any]:
    reply_action = agent.get("reply_action") or {}
    if not isinstance(reply_action, dict):
        return {"mode": REPLY_ACTION_MODE_DRAFT}
    return reply_action


def _extract_bare_email(address: str) -> str:
    normalized = (address or "").strip()
    if not normalized:
        return ""
    match = re.search(r"<([^>]+)>", normalized)
    if match:
        return match.group(1).strip().lower()
    return normalized.lower()


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


def _dedupe_recipients_preserve_order(
    addresses: List[str],
    *,
    exclude_bare_emails: Set[str] | None = None,
) -> List[str]:
    seen: Set[str] = set()
    deduped: List[str] = []
    exclude = exclude_bare_emails or set()

    for address in addresses:
        normalized = (address or "").strip()
        if not normalized:
            continue
        bare_email = _extract_bare_email(normalized)
        if not bare_email or bare_email in exclude or bare_email in seen:
            continue
        seen.add(bare_email)
        deduped.append(normalized)

    return deduped


def _recipient_list_from_message_field(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(address).strip() for address in value if str(address).strip()]


def extract_inbound_cc_bcc(context: Dict[str, Any]) -> Dict[str, List[str]]:
    """CC/BCC from the inbound message we are replying to."""
    trigger_message = context.get("trigger_message") or {}
    latest_inbound = (context.get("thread") or {}).get("latest_inbound") or {}
    source = trigger_message or latest_inbound

    return {
        "cc": _dedupe_recipients_preserve_order(
            _recipient_list_from_message_field(source.get("cc"))
        ),
        "bcc": _dedupe_recipients_preserve_order(
            _recipient_list_from_message_field(source.get("bcc"))
        ),
    }


def merge_reply_cc_bcc(
    *,
    inbound_cc: List[str],
    inbound_bcc: List[str],
    rule_cc: List[str],
    rule_bcc: List[str],
    to_addresses: List[str],
    exclude_addresses: List[str] | None = None,
) -> Dict[str, List[str]]:
    """Merge inbound CC/BCC with rule CC/BCC, dedupe overlaps, and drop To duplicates."""
    exclude_bare_emails = {
        bare_email
        for address in (to_addresses + (exclude_addresses or []))
        for bare_email in [_extract_bare_email(address)]
        if bare_email
    }

    merged_cc = _dedupe_recipients_preserve_order(
        inbound_cc + rule_cc,
        exclude_bare_emails=exclude_bare_emails,
    )
    cc_bare_emails = {_extract_bare_email(address) for address in merged_cc}
    merged_bcc = _dedupe_recipients_preserve_order(
        inbound_bcc + rule_bcc,
        exclude_bare_emails=exclude_bare_emails | cc_bare_emails,
    )

    return {"cc": merged_cc, "bcc": merged_bcc}


def apply_base_reply_recipients(
    context: Dict[str, Any],
    *,
    rule_cc: List[str] | None = None,
    rule_bcc: List[str] | None = None,
) -> Dict[str, List[str]]:
    """Resolve To and merge inbound CC/BCC with optional rule CC/BCC."""
    recipients = context.get("recipients") or {}
    reply_to = resolve_reply_to_address(context)
    to_addresses = _dedupe_preserve_order(recipients.get("to") or [])
    if not to_addresses and reply_to:
        to_addresses = [reply_to]

    inbound = extract_inbound_cc_bcc(context)
    merged = merge_reply_cc_bcc(
        inbound_cc=inbound["cc"],
        inbound_bcc=inbound["bcc"],
        rule_cc=rule_cc or [],
        rule_bcc=rule_bcc or [],
        to_addresses=to_addresses,
    )

    return {
        "to": to_addresses,
        "cc": merged["cc"],
        "bcc": merged["bcc"],
    }


def resolve_reply_to_address(context: Dict[str, Any]) -> str:
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


def resolve_reply_recipients(context: Dict[str, Any]) -> Dict[str, List[str]]:
    recipients = context.get("recipients") or {}
    return apply_base_reply_recipients(
        context,
        rule_cc=recipients.get("cc") or [],
        rule_bcc=recipients.get("bcc") or [],
    )


def build_reply_references_header(
    context: Dict[str, Any],
    trigger_message: Dict[str, Any],
) -> str:
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


async def build_reply_raw_mime(
    *,
    context: Dict[str, Any],
    draft: Dict[str, Any],
    gmail_account_id: str,
    resolved_recipients: Dict[str, List[str]],
    trigger_message: Dict[str, Any],
) -> Tuple[str, str]:
    """Return (access_token, base64url raw MIME) for draft or direct send."""
    body_text = (draft.get("body_text") or "").strip()
    if not body_text:
        raise ValueError("draft.body_text is required.")
    if not resolved_recipients["to"]:
        raise ValueError("At least one To recipient is required.")

    token_result = await get_gmail_access_token_for_account(gmail_account_id)
    if not token_result.get("success"):
        raise ValueError(token_result.get("message", "Failed to obtain Gmail access token."))

    from_address = _format_from_address(
        token_result.get("email_address", ""),
        token_result.get("display_name", ""),
    )
    in_reply_to = (trigger_message.get("message_id_header") or "").strip()
    references = build_reply_references_header(context, trigger_message)
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
    return token_result["access_token"], raw_message


def build_recipients_for_storage(
    context: Dict[str, Any],
    resolved_recipients: Dict[str, List[str]],
) -> Dict[str, Any]:
    recipients_snapshot = context.get("recipients") or {}
    return {
        **recipients_snapshot,
        "to": resolved_recipients["to"],
        "cc": resolved_recipients["cc"],
        "bcc": resolved_recipients["bcc"],
    }


async def persist_gmail_draft_reply(
    *,
    context: Dict[str, Any],
    agent: Dict[str, Any],
    action_type: str = AI_ACTION_TYPE_DRAFT,
    fallback_reason: str = "",
    auto_send_min_confidence: float | None = None,
    threshold_met: bool | None = None,
) -> Dict[str, Any]:
    """
    Create a Gmail draft and persist ai_action / ai_outcome on Mongo.

    Used by save_gmail_draft_node and send_email_node (confidence fallback).
    """
    thread_id = (context.get("thread_id") or "").strip()
    team_id = (context.get("team_id") or "").strip()
    run_id = (context.get("run_id") or "").strip()
    trigger_message_id = (context.get("trigger_message_id") or "").strip()
    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    draft = context.get("draft") or {}
    trigger_message = context.get("trigger_message") or {}
    resolved_recipients = resolve_reply_recipients(context)
    body_text = (draft.get("body_text") or "").strip()
    confidence = float(draft.get("confidence") or 0.0)

    access_token, raw_message = await build_reply_raw_mime(
        context=context,
        draft=draft,
        gmail_account_id=gmail_account_id,
        resolved_recipients=resolved_recipients,
        trigger_message=trigger_message,
    )

    draft_result = await create_gmail_draft(
        access_token,
        thread_id=thread_id,
        raw_message=raw_message,
    )
    if not draft_result.get("success"):
        raise ValueError(draft_result.get("message", "Gmail draft creation failed."))

    draft_data = draft_result.get("data") or {}
    gmail_draft_id = (draft_data.get("gmail_draft_id") or "").strip()
    gmail_draft_message_id = (draft_data.get("gmail_draft_message_id") or "").strip()
    recipients_for_storage = build_recipients_for_storage(context, resolved_recipients)

    final_action: Dict[str, Any] = {
        "type": FINAL_ACTION_TYPE_DRAFT,
        "gmail_draft_id": gmail_draft_id,
        "gmail_draft_message_id": gmail_draft_message_id,
        "recipients": {
            "to": resolved_recipients["to"],
            "cc": resolved_recipients["cc"],
            "bcc": resolved_recipients["bcc"],
        },
    }
    if fallback_reason:
        final_action["fallback_reason"] = fallback_reason

    context["final_action"] = final_action

    ai_action = build_draft_ready_ai_action(
        flow_run_id=run_id,
        trigger_message_id=trigger_message_id,
        gmail_draft_id=gmail_draft_id,
        gmail_draft_message_id=gmail_draft_message_id,
        confidence=confidence,
        subject=(draft.get("subject") or "").strip(),
        body_text=body_text,
        recipients=recipients_for_storage,
        action_type=action_type,
        fallback_reason=fallback_reason,
        auto_send_min_confidence=auto_send_min_confidence,
        threshold_met=threshold_met,
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
            fallback_reason=fallback_reason,
            auto_send_min_confidence=auto_send_min_confidence,
            threshold_met=threshold_met,
        )
        await set_message_ai_outcome(trigger_message_id, ai_outcome=ai_outcome)

    return {
        "final_action": final_action,
        "ai_action": ai_action,
        "gmail_draft_id": gmail_draft_id,
        "gmail_draft_message_id": gmail_draft_message_id,
        "resolved_recipients": resolved_recipients,
        "recipients_for_storage": recipients_for_storage,
        "confidence": confidence,
        "body_text": body_text,
    }


async def persist_draft_fallback_reply(
    *,
    context: Dict[str, Any],
    agent: Dict[str, Any],
    auto_send_min_confidence: float,
) -> Dict[str, Any]:
    """Save draft when auto-send confidence is below threshold."""
    return await persist_gmail_draft_reply(
        context=context,
        agent=agent,
        action_type=AI_ACTION_TYPE_DRAFT_FALLBACK,
        fallback_reason=FALLBACK_REASON_CONFIDENCE_BELOW_THRESHOLD,
        auto_send_min_confidence=auto_send_min_confidence,
        threshold_met=False,
    )
