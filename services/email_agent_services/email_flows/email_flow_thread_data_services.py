from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from services.email_agent_services.email_flows.email_flow_constants import (
    AI_ACTION_STATUS_DRAFT_READY,
    AI_ACTION_STATUS_RESOLVED,
    DEFAULT_THREAD_MESSAGE_LIMIT,
    MESSAGE_PROCESSING_STATUS_SKIPPED,
)
from services.email_agent_services.email_thread_services import (
    EMAIL_THREADS_COLLECTION,
    EMAIL_THREAD_MESSAGES_COLLECTION,
)
from services.mongo_services import get_collection


async def load_thread_messages_for_flow(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
    message_limit: int = DEFAULT_THREAD_MESSAGE_LIMIT,
) -> List[Dict[str, Any]]:
    """Load full thread messages from Mongo (oldest-first). Caps at message_limit for MVP."""
    normalized_thread_id = thread_id.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()
    normalized_limit = max(message_limit, 1)

    collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)

    # Try progressively broader queries (aligns with get-thread + sync storage)
    candidate_queries = [
        {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
            "gmail_account_id": normalized_gmail_account_id,
        },
        {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
        },
        {
            "gmail_account_id": normalized_gmail_account_id,
            "thread_id": normalized_thread_id,
        },
    ]

    query = candidate_queries[-1]
    total = 0
    for candidate in candidate_queries:
        total = await collection.count_documents(candidate)
        if total > 0:
            query = candidate
            break
    if total <= normalized_limit:
        cursor = collection.find(query).sort("received_at", 1)
    else:
        skip = total - normalized_limit
        cursor = (
            collection.find(query)
            .sort("received_at", 1)
            .skip(skip)
            .limit(normalized_limit)
        )

    messages: List[Dict[str, Any]] = []
    async for message in cursor:
        messages.append(message)

    return messages


async def get_thread_summary_for_flow(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
) -> Optional[Dict[str, Any]]:
    collection = get_collection(EMAIL_THREADS_COLLECTION)
    normalized_thread_id = thread_id.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()

    for query in (
        {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
            "gmail_account_id": normalized_gmail_account_id,
        },
        {"team_id": normalized_team_id, "thread_id": normalized_thread_id},
        {
            "gmail_account_id": normalized_gmail_account_id,
            "thread_id": normalized_thread_id,
        },
    ):
        thread = await collection.find_one(query)
        if thread:
            return thread

    return None


async def update_thread_department_id(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
    department_id: str,
) -> bool:
    """Persist routed department_id on email-threads when a match is resolved."""
    normalized_department_id = (department_id or "").strip()
    if not normalized_department_id:
        return False

    collection = get_collection(EMAIL_THREADS_COLLECTION)
    normalized_thread_id = thread_id.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()

    for query in (
        {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
            "gmail_account_id": normalized_gmail_account_id,
        },
        {"team_id": normalized_team_id, "thread_id": normalized_thread_id},
        {
            "gmail_account_id": normalized_gmail_account_id,
            "thread_id": normalized_thread_id,
        },
    ):
        result = await collection.update_one(
            query,
            {"$set": {"department_id": normalized_department_id}},
        )
        if result.matched_count > 0:
            return True

    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _thread_lookup_queries(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
) -> List[Dict[str, Any]]:
    normalized_thread_id = thread_id.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()
    return [
        {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
            "gmail_account_id": normalized_gmail_account_id,
        },
        {"team_id": normalized_team_id, "thread_id": normalized_thread_id},
        {
            "gmail_account_id": normalized_gmail_account_id,
            "thread_id": normalized_thread_id,
        },
    ]


async def update_thread_ai_action(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
    ai_action: Dict[str, Any],
) -> bool:
    """Persist denormalized AI action state on email-threads for inbox badges."""
    collection = get_collection(EMAIL_THREADS_COLLECTION)
    now = _utc_now()
    payload = dict(ai_action)
    payload["updated_at"] = now

    for query in _thread_lookup_queries(
        thread_id=thread_id,
        team_id=team_id,
        gmail_account_id=gmail_account_id,
    ):
        result = await collection.update_one(
            query,
            {"$set": {"ai_action": payload, "updated_at": now}},
        )
        if result.matched_count > 0:
            return True

    return False


async def set_message_ai_outcome(
    message_id: str,
    *,
    ai_outcome: Dict[str, Any],
) -> bool:
    """Attach AI outcome metadata to the trigger inbound message document."""
    try:
        object_id = ObjectId(message_id.strip())
    except InvalidId:
        return False

    collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
    now = _utc_now()
    result = await collection.update_one(
        {"_id": object_id},
        {"$set": {"ai_outcome": ai_outcome, "updated_at": now}},
    )
    return result.matched_count > 0


async def resolve_thread_ai_action(
    *,
    thread_id: str,
    team_id: str,
    gmail_account_id: str,
    status: str = AI_ACTION_STATUS_RESOLVED,
) -> bool:
    """Mark thread ai_action as resolved after the user sends or dismisses the draft."""
    collection = get_collection(EMAIL_THREADS_COLLECTION)
    now = _utc_now()

    for query in _thread_lookup_queries(
        thread_id=thread_id,
        team_id=team_id,
        gmail_account_id=gmail_account_id,
    ):
        thread = await collection.find_one(query)
        if not thread:
            continue

        ai_action = dict(thread.get("ai_action") or {})
        if not ai_action:
            return False

        ai_action["status"] = status
        ai_action["resolved_at"] = now
        ai_action["updated_at"] = now

        await collection.update_one(
            query,
            {"$set": {"ai_action": ai_action, "updated_at": now}},
        )
        return True

    return False


def build_draft_ready_ai_action(
    *,
    flow_run_id: str,
    trigger_message_id: str,
    gmail_draft_id: str,
    gmail_draft_message_id: str,
    confidence: float,
    subject: str,
    body_text: str,
    recipients: Dict[str, Any],
    action_type: str = "draft",
) -> Dict[str, Any]:
    now = _utc_now()
    normalized_body = (body_text or "").strip()
    return {
        "status": AI_ACTION_STATUS_DRAFT_READY,
        "type": action_type,
        "flow_run_id": flow_run_id,
        "trigger_message_id": trigger_message_id,
        "gmail_draft_id": gmail_draft_id,
        "gmail_draft_message_id": gmail_draft_message_id,
        "confidence": confidence,
        "subject": subject,
        "body_text": normalized_body,
        "recipients": {
            "to": recipients.get("to") or [],
            "cc": recipients.get("cc") or [],
            "bcc": recipients.get("bcc") or [],
            "cc_users": recipients.get("cc_users") or [],
            "bcc_users": recipients.get("bcc_users") or [],
            "matched_recipient_rules": recipients.get("matched_recipient_rules") or [],
        },
        "created_at": now,
        "resolved_at": None,
    }


def build_draft_created_ai_outcome(
    *,
    flow_run_id: str,
    gmail_draft_id: str,
    gmail_draft_message_id: str,
    confidence: float,
    recipients: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "type": "draft_created",
        "flow_run_id": flow_run_id,
        "gmail_draft_id": gmail_draft_id,
        "gmail_draft_message_id": gmail_draft_message_id,
        "confidence": confidence,
        "recipients": {
            "to": recipients.get("to") or [],
            "cc": recipients.get("cc") or [],
            "bcc": recipients.get("bcc") or [],
            "cc_users": recipients.get("cc_users") or [],
            "bcc_users": recipients.get("bcc_users") or [],
            "matched_recipient_rules": recipients.get("matched_recipient_rules") or [],
        },
    }


def build_ai_reply(
    *,
    mode: str,
    flow_run_id: str,
    agent_id: str,
    confidence: float = 0.0,
    gmail_draft_id: str = "",
    sender_email: str = "",
    sender_name: str = "",
) -> Dict[str, Any]:
    """Metadata for outbound messages drafted/sent by the AI flow."""
    return {
        "assisted": True,
        "mode": mode,
        "flow_run_id": (flow_run_id or "").strip(),
        "agent_id": (agent_id or "").strip(),
        "confidence": confidence,
        "gmail_draft_id": (gmail_draft_id or "").strip(),
        "sender_email": (sender_email or "").strip(),
        "sender_name": (sender_name or "").strip(),
    }


async def tag_outbound_message_ai_reply(
    *,
    gmail_message_id: str,
    gmail_account_id: str,
    thread_id: str,
    team_id: str,
    agent_id: str,
    ai_reply: Dict[str, Any],
    ai_action: Dict[str, Any],
    from_address: str = "",
    label_ids: List[str] | None = None,
) -> bool:
    """
    Tag a sent outbound message with ai_reply.

    Inserts a stub row if sync has not stored the message yet; sync later merges bodies.
    """
    normalized_gmail_message_id = (gmail_message_id or "").strip()
    if not normalized_gmail_message_id:
        return False

    collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
    now = _utc_now()
    recipients = ai_action.get("recipients") or {}
    body_text = (ai_action.get("body_text") or "").strip()
    subject = (ai_action.get("subject") or "").strip()
    snippet = body_text[:200] if body_text else ""
    normalized_from = (from_address or "").strip()

    existing = await collection.find_one({
        "gmail_account_id": (gmail_account_id or "").strip(),
        "gmail_message_id": normalized_gmail_message_id,
    })

    update_fields: Dict[str, Any] = {
        "direction": "outbound",
        "ai_reply": ai_reply,
        "updated_at": now,
    }
    if normalized_from:
        update_fields["from"] = normalized_from

    if existing:
        await collection.update_one(
            {"_id": existing["_id"]},
            {"$set": update_fields},
        )
        return True

    document = {
        "agent_id": (agent_id or "").strip(),
        "gmail_account_id": (gmail_account_id or "").strip(),
        "team_id": (team_id or "").strip(),
        "gmail_message_id": normalized_gmail_message_id,
        "thread_id": (thread_id or "").strip(),
        "direction": "outbound",
        "subject": subject,
        "from": normalized_from,
        "to": recipients.get("to") or [],
        "cc": recipients.get("cc") or [],
        "bcc": recipients.get("bcc") or [],
        "reply_to": "",
        "message_id_header": "",
        "snippet": snippet,
        "body_text": body_text,
        "body_html": "",
        "received_at": now,
        "label_ids": label_ids or ["SENT"],
        "is_unread": False,
        "metadata": {"ai_reply_stub": True},
        "status": "stored",
        "processing_status": MESSAGE_PROCESSING_STATUS_SKIPPED,
        "flow_run_id": (ai_reply.get("flow_run_id") or "").strip() or None,
        "processed_at": None,
        "ai_reply": ai_reply,
        "created_at": now,
        "updated_at": now,
    }
    await collection.insert_one(document)
    return True
