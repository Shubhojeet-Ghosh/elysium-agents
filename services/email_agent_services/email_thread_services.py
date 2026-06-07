from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.email_agent_services.email_ai_agent_services import _format_datetime
from services.email_agent_services.email_flows.email_flow_constants import (
    AI_ACTION_STATUS_DRAFT_READY,
)
from services.email_agent_services.email_flows.email_flow_context import serialize_for_json
from services.email_agent_services.gmail_api_services import send_gmail_draft
from services.email_agent_services.gmail_token_services import (
    get_gmail_access_token_for_account,
)
from services.mongo_services import get_collection

EMAIL_THREADS_COLLECTION = "email-threads"
EMAIL_THREAD_MESSAGES_COLLECTION = "email-thread-messages"
DEFAULT_THREAD_DEPARTMENT_ID = ""
DEFAULT_THREAD_ASSIGNED_USER_ID = ""
ADMIN_ROLE = "admin"
MEMBER_ROLE = "member"


def _normalize_role(role: str) -> str:
    normalized_role = (role or "").strip().lower()
    return normalized_role if normalized_role in {ADMIN_ROLE, MEMBER_ROLE} else MEMBER_ROLE


def _thread_field_value(thread: Dict[str, Any], field: str) -> str:
    return (thread.get(field) or "").strip()


def _empty_field_filter(field: str) -> Dict[str, Any]:
    return {"$or": [{field: ""}, {field: {"$exists": False}}]}


def can_user_access_thread(
    *,
    role: str,
    user_id: str,
    user_department_id: str,
    thread: Dict[str, Any],
) -> bool:
    """
    Admin can access every thread in the team.

    Members:
    - no department_id on thread → hidden
    - department_id must match the member's department
    - assigned_user_id set to someone else → hidden (even if department matches)
    - assigned_user_id empty → visible to all members in that department
    - assigned_user_id set to this member → visible
    """
    if _normalize_role(role) == ADMIN_ROLE:
        return True

    assigned_user_id = _thread_field_value(thread, "assigned_user_id")
    department_id = _thread_field_value(thread, "department_id")
    normalized_user_id = (user_id or "").strip()
    normalized_user_department_id = (user_department_id or "").strip()

    if not department_id or not normalized_user_department_id:
        return False

    if department_id != normalized_user_department_id:
        return False

    if assigned_user_id:
        return normalized_user_id == assigned_user_id

    return True


def build_thread_access_filter(
    *,
    team_id: str,
    role: str,
    user_id: str,
    user_department_id: str,
) -> Dict[str, Any]:
    """Build a MongoDB filter for threads visible to the authenticated user."""
    normalized_team_id = team_id.strip()

    if _normalize_role(role) == ADMIN_ROLE:
        return {"team_id": normalized_team_id}

    normalized_user_id = (user_id or "").strip()
    normalized_user_department_id = (user_department_id or "").strip()

    if not normalized_user_department_id:
        return {"team_id": normalized_team_id, "department_id": "__no_match__"}

    return {
        "team_id": normalized_team_id,
        "department_id": normalized_user_department_id,
        "$or": [
            _empty_field_filter("assigned_user_id"),
            {"assigned_user_id": normalized_user_id},
        ],
    }


def _pagination_meta(total: int, page: int, limit: int) -> Dict[str, Any]:
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit if total > 0 else 0
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": (skip + limit) < total,
        "has_prev": page > 1,
    }


def _format_ai_action(ai_action: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not ai_action or not isinstance(ai_action, dict):
        return None

    status = (ai_action.get("status") or "").strip()
    if not status:
        return None

    formatted = serialize_for_json(ai_action)
    if isinstance(formatted.get("created_at"), datetime):
        formatted["created_at"] = _format_datetime(formatted.get("created_at"))
    if isinstance(formatted.get("resolved_at"), datetime):
        formatted["resolved_at"] = _format_datetime(formatted.get("resolved_at"))
    if isinstance(formatted.get("updated_at"), datetime):
        formatted["updated_at"] = _format_datetime(formatted.get("updated_at"))
    return formatted


def _action_required(ai_action: Optional[Dict[str, Any]]) -> bool:
    if not ai_action or not isinstance(ai_action, dict):
        return False
    return (ai_action.get("status") or "").strip() == AI_ACTION_STATUS_DRAFT_READY


def _format_thread_summary(thread: Dict[str, Any]) -> Dict[str, Any]:
    ai_action = _format_ai_action(thread.get("ai_action"))
    return {
        "thread_id": thread.get("thread_id", ""),
        "agent_id": thread.get("agent_id", ""),
        "gmail_account_id": thread.get("gmail_account_id", ""),
        "team_id": thread.get("team_id", ""),
        "subject": thread.get("subject", ""),
        "snippet": thread.get("snippet", ""),
        "latest_from": thread.get("latest_from", ""),
        "participants": thread.get("participants", []),
        "last_message_at": _format_datetime(thread.get("last_message_at")),
        "message_count": thread.get("message_count", 0),
        "has_unread": thread.get("has_unread", False),
        "department_id": thread.get("department_id", DEFAULT_THREAD_DEPARTMENT_ID),
        "assigned_user_id": thread.get("assigned_user_id", DEFAULT_THREAD_ASSIGNED_USER_ID),
        "action_required": _action_required(ai_action),
        "ai_action": ai_action,
        "updated_at": _format_datetime(thread.get("updated_at")),
    }


def _format_thread_message(message: Dict[str, Any]) -> Dict[str, Any]:
    ai_outcome = message.get("ai_outcome")
    formatted_ai_outcome = (
        serialize_for_json(ai_outcome) if isinstance(ai_outcome, dict) else None
    )
    ai_reply = message.get("ai_reply")
    formatted_ai_reply = (
        serialize_for_json(ai_reply) if isinstance(ai_reply, dict) else None
    )
    return {
        "message_id": str(message["_id"]),
        "gmail_message_id": message.get("gmail_message_id", ""),
        "thread_id": message.get("thread_id", ""),
        "agent_id": message.get("agent_id", ""),
        "direction": message.get("direction", "inbound"),
        "from": message.get("from", ""),
        "to": message.get("to", []),
        "cc": message.get("cc", []),
        "bcc": message.get("bcc", []),
        "reply_to": message.get("reply_to", ""),
        "subject": message.get("subject", ""),
        "snippet": message.get("snippet", ""),
        "body_text": message.get("body_text", ""),
        "body_html": message.get("body_html", ""),
        "received_at": _format_datetime(message.get("received_at")),
        "is_unread": message.get("is_unread", False),
        "label_ids": message.get("label_ids", []),
        "processing_status": message.get("processing_status", ""),
        "flow_run_id": message.get("flow_run_id", ""),
        "processed_at": _format_datetime(message.get("processed_at")),
        "ai_outcome": formatted_ai_outcome,
        "ai_reply": formatted_ai_reply,
        "created_at": _format_datetime(message.get("created_at")),
    }


async def refresh_thread_summary(
    *,
    thread_id: str,
    team_id: str,
    agent_id: str,
    gmail_account_id: str,
) -> None:
    """Rebuild thread summary from stored messages."""
    messages_collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
    threads_collection = get_collection(EMAIL_THREADS_COLLECTION)
    now = datetime.now(timezone.utc)

    cursor = messages_collection.find({
        "gmail_account_id": gmail_account_id,
        "thread_id": thread_id,
    }).sort("received_at", 1)

    messages: List[Dict[str, Any]] = []
    async for message in cursor:
        messages.append(message)

    if not messages:
        return

    latest = messages[-1]
    subject = ""
    for message in messages:
        if message.get("subject"):
            subject = message["subject"]
            break

    participants: List[str] = []
    seen = set()
    for message in messages:
        for value in [message.get("from", "")] + message.get("to", []) + message.get("cc", []):
            if value and value not in seen:
                seen.add(value)
                participants.append(value)

    summary = {
        "thread_id": thread_id,
        "team_id": team_id,
        "agent_id": agent_id,
        "gmail_account_id": gmail_account_id,
        "subject": subject,
        "snippet": latest.get("snippet", ""),
        "latest_from": latest.get("from", ""),
        "participants": participants,
        "last_message_at": latest.get("received_at"),
        "message_count": len(messages),
        "has_unread": any(message.get("is_unread") for message in messages),
        "updated_at": now,
    }

    await threads_collection.update_one(
        {"gmail_account_id": gmail_account_id, "thread_id": thread_id},
        {
            "$set": summary,
            "$setOnInsert": {
                "created_at": now,
                "department_id": DEFAULT_THREAD_DEPARTMENT_ID,
                "assigned_user_id": DEFAULT_THREAD_ASSIGNED_USER_ID,
            },
        },
        upsert=True,
    )


async def list_team_email_threads(
    team_id: str,
    page: int = 1,
    limit: int = 20,
    *,
    role: str,
    user_id: str,
    user_department_id: str = "",
) -> Dict[str, Any]:
    """List thread summaries for a team (snippet only, no bodies)."""
    normalized_team_id = team_id.strip()
    normalized_page = max(page, 1)
    normalized_limit = max(min(limit, 100), 1)
    skip = (normalized_page - 1) * normalized_limit

    try:
        collection = get_collection(EMAIL_THREADS_COLLECTION)
        query = build_thread_access_filter(
            team_id=normalized_team_id,
            role=role,
            user_id=user_id,
            user_department_id=user_department_id,
        )
        total = await collection.count_documents(query)

        cursor = (
            collection.find(query)
            .sort("last_message_at", -1)
            .skip(skip)
            .limit(normalized_limit)
        )

        threads = []
        async for thread in cursor:
            threads.append(_format_thread_summary(thread))

        pagination = _pagination_meta(total, normalized_page, normalized_limit)

        return {
            "success": True,
            "status_code": 200,
            "message": "Email threads fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(threads),
                "threads": threads,
                "pagination": pagination,
            },
        }

    except Exception as e:
        from logging_config import get_logger

        get_logger().error(f"Failed to list threads for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch email threads.",
        }


async def get_email_thread_detail(
    team_id: str,
    thread_id: str,
    page: int = 1,
    limit: int = 20,
    *,
    role: str,
    user_id: str,
    user_department_id: str = "",
) -> Dict[str, Any]:
    """Return a paginated email thread with complete message bodies."""
    normalized_team_id = team_id.strip()
    normalized_thread_id = thread_id.strip()
    normalized_page = max(page, 1)
    normalized_limit = max(min(limit, 100), 1)
    skip = (normalized_page - 1) * normalized_limit

    try:
        threads_collection = get_collection(EMAIL_THREADS_COLLECTION)
        thread = await threads_collection.find_one({
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
        })

        if not thread:
            return {
                "success": False,
                "status_code": 404,
                "message": "Email thread not found.",
            }

        if not can_user_access_thread(
            role=role,
            user_id=user_id,
            user_department_id=user_department_id,
            thread=thread,
        ):
            return {
                "success": False,
                "status_code": 403,
                "message": "You do not have access to this email thread.",
            }

        messages_collection = get_collection(EMAIL_THREAD_MESSAGES_COLLECTION)
        query = {
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
        }
        total = await messages_collection.count_documents(query)

        cursor = (
            messages_collection.find(query)
            .sort("received_at", 1)
            .skip(skip)
            .limit(normalized_limit)
        )

        messages = []
        async for message in cursor:
            messages.append(_format_thread_message(message))

        pagination = _pagination_meta(total, normalized_page, normalized_limit)

        return {
            "success": True,
            "status_code": 200,
            "message": "Email thread fetched successfully.",
            "data": {
                "thread": _format_thread_summary(thread),
                "count": len(messages),
                "messages": messages,
                "pagination": pagination,
            },
        }

    except Exception as e:
        from logging_config import get_logger

        get_logger().error(
            f"Failed to get thread {normalized_thread_id} for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch email thread.",
        }


async def send_thread_ai_draft(
    team_id: str,
    thread_id: str,
    *,
    role: str,
    user_id: str,
    user_department_id: str = "",
) -> Dict[str, Any]:
    """Send the pending AI Gmail draft for a thread and mark ai_action resolved."""
    normalized_team_id = team_id.strip()
    normalized_thread_id = thread_id.strip()

    try:
        threads_collection = get_collection(EMAIL_THREADS_COLLECTION)
        thread = await threads_collection.find_one({
            "team_id": normalized_team_id,
            "thread_id": normalized_thread_id,
        })

        if not thread:
            return {
                "success": False,
                "status_code": 404,
                "message": "Email thread not found.",
            }

        if not can_user_access_thread(
            role=role,
            user_id=user_id,
            user_department_id=user_department_id,
            thread=thread,
        ):
            return {
                "success": False,
                "status_code": 403,
                "message": "You do not have access to this email thread.",
            }

        ai_action = thread.get("ai_action") or {}
        if (ai_action.get("status") or "").strip() != AI_ACTION_STATUS_DRAFT_READY:
            return {
                "success": False,
                "status_code": 409,
                "message": "No pending AI draft is ready to send on this thread.",
            }

        gmail_draft_id = (ai_action.get("gmail_draft_id") or "").strip()
        if not gmail_draft_id:
            return {
                "success": False,
                "status_code": 400,
                "message": "Thread ai_action is missing gmail_draft_id.",
            }

        gmail_account_id = (thread.get("gmail_account_id") or "").strip()
        if not gmail_account_id:
            return {
                "success": False,
                "status_code": 400,
                "message": "Thread is missing gmail_account_id.",
            }

        token_result = await get_gmail_access_token_for_account(gmail_account_id)
        if not token_result.get("success"):
            return {
                "success": False,
                "status_code": 400,
                "message": token_result.get("message", "Failed to obtain Gmail access token."),
            }

        send_result = await send_gmail_draft(
            token_result["access_token"],
            gmail_draft_id=gmail_draft_id,
        )
        if not send_result.get("success"):
            return {
                "success": False,
                "status_code": 400,
                "message": send_result.get("message", "Failed to send Gmail draft."),
            }

        from services.email_agent_services.gmail_api_services import (
            _format_from_address,
        )
        from services.email_agent_services.email_flows.email_flow_constants import (
            AI_REPLY_MODE_REVIEWED,
        )
        from services.email_agent_services.email_flows.email_flow_thread_data_services import (
            build_ai_reply,
            resolve_thread_ai_action,
            tag_outbound_message_ai_reply,
        )

        sent_data = send_result.get("data") or {}
        gmail_message_id = (sent_data.get("gmail_message_id") or "").strip()
        agent_id = (thread.get("agent_id") or "").strip()
        sender_email = (token_result.get("email_address") or "").strip()
        sender_name = (token_result.get("display_name") or "").strip()
        from_address = _format_from_address(sender_email, sender_name)
        ai_reply_payload = None

        if gmail_message_id:
            ai_reply_payload = build_ai_reply(
                mode=AI_REPLY_MODE_REVIEWED,
                flow_run_id=(ai_action.get("flow_run_id") or "").strip(),
                agent_id=agent_id,
                confidence=float(ai_action.get("confidence") or 0.0),
                gmail_draft_id=gmail_draft_id,
                sender_email=sender_email,
                sender_name=sender_name,
            )
            await tag_outbound_message_ai_reply(
                gmail_message_id=gmail_message_id,
                gmail_account_id=gmail_account_id,
                thread_id=normalized_thread_id,
                team_id=normalized_team_id,
                agent_id=agent_id,
                ai_reply=ai_reply_payload,
                ai_action=ai_action,
                from_address=from_address,
                label_ids=sent_data.get("label_ids") or ["SENT"],
            )

        await resolve_thread_ai_action(
            thread_id=normalized_thread_id,
            team_id=normalized_team_id,
            gmail_account_id=gmail_account_id,
        )

        return {
            "success": True,
            "status_code": 200,
            "message": "AI draft sent successfully.",
            "data": {
                "thread_id": normalized_thread_id,
                "gmail_draft_id": gmail_draft_id,
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": sent_data.get("thread_id", normalized_thread_id),
                "label_ids": sent_data.get("label_ids", []),
                "ai_action_status": "resolved",
                "ai_reply": ai_reply_payload,
            },
        }

    except Exception as e:
        from logging_config import get_logger

        get_logger().error(
            f"Failed to send AI draft for thread {normalized_thread_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to send AI draft.",
        }
