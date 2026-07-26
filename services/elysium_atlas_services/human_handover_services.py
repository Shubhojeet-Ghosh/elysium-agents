"""
Human handover runtime pipeline for visitor chat.

Detects visitor intent to speak with a human, persists session handover state,
emits widget events for contact capture, and injects acknowledgment-only prompts.
"""

from __future__ import annotations

import datetime
import re
from typing import Any

from config.human_handover_config import (
    ENABLE_HUMAN_HANDOVER_KEY,
    HANDOVER_TRIGGER_PROMPT_KEY,
    normalize_human_handover_config,
)
from config.human_handover_constants import (
    CONTACT_STATUS_DECLINED,
    CONTACT_STATUS_PENDING,
    CONTACT_STATUS_PROVIDED,
    ERR_HANDOVER_CONTACT_ALREADY_RESOLVED,
    ERR_HANDOVER_INVALID_EMAIL,
    ERR_HANDOVER_INVALID_NAME,
    ERR_HANDOVER_NOT_REQUESTED,
    ERR_HANDOVER_SESSION_NOT_FOUND,
    HANDOVER_CHAT_HISTORY_LIMIT,
    HANDOVER_STATUS_ASSIGNED,
    HANDOVER_STATUS_REQUESTED,
    HANDOVER_TRIGGER_MODEL,
    HANDOVER_WAITING_MESSAGE,
    MAX_HANDOVER_CONTACT_EMAIL_LENGTH,
    MAX_HANDOVER_CONTACT_NAME_LENGTH,
)
from config.structured_output_models import HandoverTriggerResult
from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_audit_services import (
    AUDIT_ACTOR_SYSTEM,
    AUDIT_ACTOR_TEAM_MEMBER,
    AUDIT_ACTOR_VISITOR,
    AUDIT_EVENT_HANDOVER_ASSIGNED,
    AUDIT_EVENT_HANDOVER_CONTACT_DECLINED,
    AUDIT_EVENT_HANDOVER_CONTACT_SUBMITTED,
    AUDIT_EVENT_HANDOVER_REQUESTED,
    record_chat_session_audit,
)
from services.elysium_atlas_services.atlas_chat_session_services import (
    format_utc_datetime_for_client,
    get_chat_messages_for_session,
    patch_chat_session,
)
from services.elysium_atlas_services.lead_collection_services import (
    _format_conversation_for_llm,
)
from services.mongo_services import get_collection
from services.open_ai_services import openai_structured_output

logger = get_logger()

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def init_handover_session_state() -> dict[str, Any]:
    return {
        "status": None,
        "requested_at": None,
        "reason": None,
        "contact": {"name": None, "email": None},
        "contact_status": None,
        "assigned_to": None,
    }


def get_handover_session_state(session_doc: dict[str, Any] | None) -> dict[str, Any]:
    state = init_handover_session_state()
    if not session_doc:
        return state

    embedded = session_doc.get("handover")
    if not isinstance(embedded, dict):
        return state

    contact = embedded.get("contact") if isinstance(embedded.get("contact"), dict) else {}
    state["status"] = embedded.get("status")
    state["requested_at"] = embedded.get("requested_at")
    state["reason"] = embedded.get("reason")
    state["contact"] = {
        "name": contact.get("name"),
        "email": contact.get("email"),
    }
    state["contact_status"] = embedded.get("contact_status")
    state["assigned_to"] = embedded.get("assigned_to")
    return state


def is_handover_waiting(state: dict[str, Any]) -> bool:
    return state.get("status") == HANDOVER_STATUS_REQUESTED


def should_skip_handover_trigger(state: dict[str, Any]) -> bool:
    return state.get("status") in {HANDOVER_STATUS_REQUESTED, HANDOVER_STATUS_ASSIGNED}


def build_handover_list_fields(handover_state: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "handover_status": None,
        "handover_requested_at": None,
        "handover_reason": None,
        "handover_contact_name": None,
        "handover_contact_email": None,
        "handover_contact_status": None,
    }
    if not handover_state:
        return empty

    contact = handover_state.get("contact") or {}
    contact_name = contact.get("name")
    contact_email = contact.get("email")
    contact_status = handover_state.get("contact_status")
    has_preserved_contact = bool(
        contact_name or contact_email or contact_status in {CONTACT_STATUS_PROVIDED, CONTACT_STATUS_DECLINED}
    )

    if not handover_state.get("status") and not has_preserved_contact:
        return empty

    requested_at = handover_state.get("requested_at")
    return {
        "handover_status": handover_state.get("status"),
        "handover_requested_at": format_utc_datetime_for_client(requested_at)
        if requested_at is not None
        else None,
        "handover_reason": handover_state.get("reason"),
        "handover_contact_name": contact_name,
        "handover_contact_email": contact_email,
        "handover_contact_status": contact_status,
    }


def build_handover_prompt_block(
    handover_state: dict[str, Any],
    *,
    newly_triggered: bool = False,
) -> str | None:
    if handover_state.get("status") != HANDOVER_STATUS_REQUESTED:
        return None

    if newly_triggered:
        return (
            "HUMAN HANDOVER (follow for this reply only):\n"
            "- The visitor has asked to speak with a human team member.\n"
            "- Acknowledge that their request has been registered and a team member will join as soon as possible.\n"
            "- Keep the reply brief, warm, and reassuring.\n"
            "- Do NOT answer their product or support question in detail in this reply.\n"
            "- Do NOT ask them to keep waiting repeatedly — one clear acknowledgment is enough."
        )

    return (
        "HUMAN HANDOVER — WAITING FOR TEAM MEMBER:\n"
        "- A human handover has already been requested for this chat.\n"
        "- Reply ONLY with a brief, polite acknowledgment that the request is registered "
        "and someone from the team will join as soon as possible.\n"
        "- Do NOT answer product, pricing, or support questions.\n"
        "- Do NOT start new topics or provide detailed help — redirect to waiting for a team member."
    )


async def _evaluate_handover_trigger(
    handover_config: dict[str, Any],
    conversation_text: str,
) -> dict[str, Any]:
    trigger_prompt = (handover_config.get(HANDOVER_TRIGGER_PROMPT_KEY) or "").strip()
    messages = [
        {
            "role": "system",
            "content": (
                "You decide whether the visitor wants to speak with a human representative "
                "based on the owner's rule and the conversation so far. Be conservative — only "
                "return should_request_handover=true when the visitor clearly asks for a human, "
                "live agent, or real person."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Owner rule:\n{trigger_prompt}\n\n"
                f"Conversation:\n{conversation_text}"
            ),
        },
    ]

    try:
        result = await openai_structured_output(
            model=HANDOVER_TRIGGER_MODEL,
            messages=messages,
            response_format=HandoverTriggerResult,
        )
        return {
            "should_request_handover": bool(result.get("should_request_handover")),
            "reason": (result.get("reason") or "").strip(),
        }
    except Exception as exc:
        logger.warning("Human handover trigger evaluation failed: %s", exc)
        return {"should_request_handover": False, "reason": ""}


async def persist_handover_state(
    agent_id: str,
    chat_session_id: str,
    handover_state: dict[str, Any],
) -> None:
    requested_at = handover_state.get("requested_at")
    if isinstance(requested_at, datetime.datetime):
        requested_at_value = requested_at
    else:
        requested_at_value = None

    await patch_chat_session(
        agent_id,
        chat_session_id,
        {
            "handover": {
                "status": handover_state.get("status"),
                "requested_at": requested_at_value,
                "reason": handover_state.get("reason"),
                "contact": {
                    "name": (handover_state.get("contact") or {}).get("name"),
                    "email": (handover_state.get("contact") or {}).get("email"),
                },
                "contact_status": handover_state.get("contact_status"),
                "assigned_to": handover_state.get("assigned_to"),
            },
        },
    )


async def emit_handover_requested_to_visitor(
    agent_id: str,
    chat_session_id: str,
    *,
    reason: str | None,
    contact_status: str | None,
) -> None:
    from services.elysium_atlas_services.atlas_visitor_socket_rooms import visitor_session_room
    from sockets import sio

    show_contact_form = contact_status == CONTACT_STATUS_PENDING
    await sio.emit(
        "handover_requested",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "reason": reason,
            "waiting_message": HANDOVER_WAITING_MESSAGE,
            "show_contact_form": show_contact_form,
            "contact_status": contact_status,
        },
        room=visitor_session_room(chat_session_id),
    )
    logger.info(
        "Emitted handover_requested chat_session_id=%s agent_id=%s show_contact_form=%s",
        chat_session_id,
        agent_id,
        show_contact_form,
    )


async def emit_handover_contact_saved_to_visitor(
    agent_id: str,
    chat_session_id: str,
    *,
    contact_status: str,
) -> None:
    from services.elysium_atlas_services.atlas_visitor_socket_rooms import visitor_session_room
    from sockets import sio

    await sio.emit(
        "handover_contact_saved",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "contact_status": contact_status,
        },
        room=visitor_session_room(chat_session_id),
    )


async def emit_handover_contact_declined_to_visitor(
    agent_id: str,
    chat_session_id: str,
) -> None:
    from services.elysium_atlas_services.atlas_visitor_socket_rooms import visitor_session_room
    from sockets import sio

    await sio.emit(
        "handover_contact_declined",
        {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "contact_status": CONTACT_STATUS_DECLINED,
        },
        room=visitor_session_room(chat_session_id),
    )


async def emit_chat_session_handover_updated(agent_id: str, chat_session_id: str) -> None:
    from services.elysium_atlas_services.atlas_chat_session_services import (
        build_chat_session_broadcast_row,
    )
    from sockets import sio

    row = await build_chat_session_broadcast_row(agent_id, chat_session_id)
    if not row:
        return

    payload = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "visitor": row,
        "handover_status": row.get("handover_status"),
        "handover_requested_at": row.get("handover_requested_at"),
        "handover_reason": row.get("handover_reason"),
        "handover_contact_name": row.get("handover_contact_name"),
        "handover_contact_email": row.get("handover_contact_email"),
        "handover_contact_status": row.get("handover_contact_status"),
    }

    await sio.emit("chat_session_handover_updated", payload, room=f"agent_{agent_id}_members")
    logger.info(
        "Emitted chat_session_handover_updated chat_session_id=%s agent_id=%s",
        chat_session_id,
        agent_id,
    )


async def maybe_emit_pending_handover_on_visitor_connect(
    agent_id: str,
    chat_session_id: str,
) -> None:
    """Re-emit contact form on reconnect when handover is requested and contact is still pending."""
    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"handover": 1},
    )
    if not session_doc:
        return

    handover_state = get_handover_session_state(session_doc)
    if handover_state.get("status") != HANDOVER_STATUS_REQUESTED:
        return
    if handover_state.get("contact_status") != CONTACT_STATUS_PENDING:
        return

    await emit_handover_requested_to_visitor(
        agent_id,
        chat_session_id,
        reason=handover_state.get("reason"),
        contact_status=CONTACT_STATUS_PENDING,
    )


async def process_handover_turn(
    *,
    agent_id: str,
    chat_session_id: str,
    message: str,
    chat_session_data: dict[str, Any],
    chat_history: list[dict[str, Any]],
    handover_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Run human handover detection and waiting-state prompt injection for one visitor message.

    Returns:
        dict with keys:
            - prompt_block: str | None
            - handover_state: dict | None
            - newly_triggered: bool
    """
    normalized_config = normalize_human_handover_config(handover_config or {})
    if not normalized_config.get(ENABLE_HUMAN_HANDOVER_KEY):
        return {"prompt_block": None, "handover_state": None, "newly_triggered": False}

    handover_state = get_handover_session_state(chat_session_data)

    if is_handover_waiting(handover_state):
        return {
            "prompt_block": build_handover_prompt_block(handover_state, newly_triggered=False),
            "handover_state": handover_state,
            "newly_triggered": False,
        }

    if should_skip_handover_trigger(handover_state):
        return {"prompt_block": None, "handover_state": handover_state, "newly_triggered": False}

    conversation_id = chat_session_data.get("conversation_id")
    full_history = await get_chat_messages_for_session(
        agent_id,
        chat_session_id,
        limit=HANDOVER_CHAT_HISTORY_LIMIT,
        conversation_id=conversation_id,
    )
    conversation_text = _format_conversation_for_llm(full_history, message)
    trigger = await _evaluate_handover_trigger(normalized_config, conversation_text)

    if not trigger.get("should_request_handover"):
        return {"prompt_block": None, "handover_state": handover_state, "newly_triggered": False}

    now = _utc_now()
    existing_contact = handover_state.get("contact") or {}
    existing_contact_status = handover_state.get("contact_status")
    if existing_contact_status in {CONTACT_STATUS_PROVIDED, CONTACT_STATUS_DECLINED}:
        contact = {
            "name": existing_contact.get("name"),
            "email": existing_contact.get("email"),
        }
        contact_status = existing_contact_status
    else:
        contact = {"name": None, "email": None}
        contact_status = CONTACT_STATUS_PENDING

    handover_state = {
        "status": HANDOVER_STATUS_REQUESTED,
        "requested_at": now,
        "reason": trigger.get("reason") or "",
        "contact": contact,
        "contact_status": contact_status,
        "assigned_to": None,
    }

    await persist_handover_state(agent_id, chat_session_id, handover_state)
    await record_chat_session_audit(
        agent_id,
        chat_session_id,
        AUDIT_EVENT_HANDOVER_REQUESTED,
        actor_type=AUDIT_ACTOR_SYSTEM,
        metadata={"reason": handover_state.get("reason")},
        occurred_at=now,
    )

    await emit_handover_requested_to_visitor(
        agent_id,
        chat_session_id,
        reason=handover_state.get("reason"),
        contact_status=contact_status,
    )
    await emit_chat_session_handover_updated(agent_id, chat_session_id)

    return {
        "prompt_block": build_handover_prompt_block(handover_state, newly_triggered=True),
        "handover_state": handover_state,
        "newly_triggered": True,
    }


def _normalize_contact_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > MAX_HANDOVER_CONTACT_NAME_LENGTH:
        return None
    return normalized


def _normalize_contact_email(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized or len(normalized) > MAX_HANDOVER_CONTACT_EMAIL_LENGTH:
        return None
    if not _EMAIL_PATTERN.match(normalized):
        return None
    return normalized


def map_handover_contact_error(error_code: str) -> str:
    messages = {
        ERR_HANDOVER_SESSION_NOT_FOUND: "Chat session not found.",
        ERR_HANDOVER_NOT_REQUESTED: "Human handover is not active for this chat.",
        ERR_HANDOVER_CONTACT_ALREADY_RESOLVED: "Contact details were already submitted or declined.",
        ERR_HANDOVER_INVALID_NAME: "Please provide a valid name.",
        ERR_HANDOVER_INVALID_EMAIL: "Please provide a valid email address.",
    }
    return messages.get(error_code, "Unable to save contact details.")


async def submit_handover_contact(
    *,
    agent_id: str,
    chat_session_id: str,
    name: str | None,
    email: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Persist handover follow-up contact only on session.handover.contact.

    Intentionally does NOT write to lead_collection or atlas_leads — handover contact
    capture is independent of lead_collection_config.
    """
    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
    )
    if not session_doc:
        return None, ERR_HANDOVER_SESSION_NOT_FOUND

    handover_state = get_handover_session_state(session_doc)
    if handover_state.get("status") != HANDOVER_STATUS_REQUESTED:
        return None, ERR_HANDOVER_NOT_REQUESTED

    contact_status = handover_state.get("contact_status")
    if contact_status in {CONTACT_STATUS_PROVIDED, CONTACT_STATUS_DECLINED}:
        return None, ERR_HANDOVER_CONTACT_ALREADY_RESOLVED

    normalized_name = _normalize_contact_name(name)
    normalized_email = _normalize_contact_email(email)
    if not normalized_name:
        return None, ERR_HANDOVER_INVALID_NAME
    if not normalized_email:
        return None, ERR_HANDOVER_INVALID_EMAIL

    handover_state["contact"] = {
        "name": normalized_name,
        "email": normalized_email,
    }
    handover_state["contact_status"] = CONTACT_STATUS_PROVIDED

    await persist_handover_state(agent_id, chat_session_id, handover_state)
    await record_chat_session_audit(
        agent_id,
        chat_session_id,
        AUDIT_EVENT_HANDOVER_CONTACT_SUBMITTED,
        actor_type=AUDIT_ACTOR_VISITOR,
        metadata={"has_name": True, "has_email": True},
    )
    await emit_handover_contact_saved_to_visitor(
        agent_id,
        chat_session_id,
        contact_status=CONTACT_STATUS_PROVIDED,
    )
    await emit_chat_session_handover_updated(agent_id, chat_session_id)

    return {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "contact_status": CONTACT_STATUS_PROVIDED,
        "handover": build_handover_list_fields(handover_state),
    }, None


async def decline_handover_contact(
    *,
    agent_id: str,
    chat_session_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
    )
    if not session_doc:
        return None, ERR_HANDOVER_SESSION_NOT_FOUND

    handover_state = get_handover_session_state(session_doc)
    if handover_state.get("status") != HANDOVER_STATUS_REQUESTED:
        return None, ERR_HANDOVER_NOT_REQUESTED

    contact_status = handover_state.get("contact_status")
    if contact_status in {CONTACT_STATUS_PROVIDED, CONTACT_STATUS_DECLINED}:
        return None, ERR_HANDOVER_CONTACT_ALREADY_RESOLVED

    handover_state["contact_status"] = CONTACT_STATUS_DECLINED

    await persist_handover_state(agent_id, chat_session_id, handover_state)
    await record_chat_session_audit(
        agent_id,
        chat_session_id,
        AUDIT_EVENT_HANDOVER_CONTACT_DECLINED,
        actor_type=AUDIT_ACTOR_VISITOR,
    )
    await emit_handover_contact_declined_to_visitor(agent_id, chat_session_id)
    await emit_chat_session_handover_updated(agent_id, chat_session_id)

    return {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "contact_status": CONTACT_STATUS_DECLINED,
        "handover": build_handover_list_fields(handover_state),
    }, None


async def assign_handover_on_takeover(
    agent_id: str,
    chat_session_id: str,
    handler_user_id: str,
) -> bool:
    """
    When a team member takes over, mark a pending handover request as assigned.

    Returns True when handover status was updated from requested → assigned.
    """
    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"handover": 1},
    )
    if not session_doc:
        return False

    handover_state = get_handover_session_state(session_doc)
    if handover_state.get("status") != HANDOVER_STATUS_REQUESTED:
        return False

    handover_state["status"] = HANDOVER_STATUS_ASSIGNED
    handover_state["assigned_to"] = handler_user_id

    await persist_handover_state(agent_id, chat_session_id, handover_state)
    await record_chat_session_audit(
        agent_id,
        chat_session_id,
        AUDIT_EVENT_HANDOVER_ASSIGNED,
        actor_type=AUDIT_ACTOR_TEAM_MEMBER,
        actor_user_id=handler_user_id,
        metadata={
            "assigned_to": handler_user_id,
            "in_conversation_with": handler_user_id,
        },
    )
    return True


async def reset_handover_after_takeover_release(
    agent_id: str,
    chat_session_id: str,
) -> bool:
    """
    End the active handover request after human takeover is released or session resolved.

    Clears queue/assignment fields (status, reason, assigned_to) but preserves visitor
    contact details when already provided or declined so the form is not shown again.
    """
    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"handover": 1},
    )
    if not session_doc:
        return False

    handover_state = get_handover_session_state(session_doc)
    if not handover_state.get("status"):
        return False

    contact = handover_state.get("contact") or {}
    contact_status = handover_state.get("contact_status")
    has_preserved_contact = bool(
        contact.get("name")
        or contact.get("email")
        or contact_status in {CONTACT_STATUS_PROVIDED, CONTACT_STATUS_DECLINED}
    )

    if not has_preserved_contact:
        result = await sessions.update_one(
            {"agent_id": agent_id, "chat_session_id": chat_session_id},
            {"$unset": {"handover": ""}},
        )
        cleared = bool(result.matched_count)
    else:
        reset_state = {
            "status": None,
            "requested_at": None,
            "reason": None,
            "contact": {
                "name": contact.get("name"),
                "email": contact.get("email"),
            },
            "contact_status": contact_status,
            "assigned_to": None,
        }
        await persist_handover_state(agent_id, chat_session_id, reset_state)
        cleared = True

    if cleared:
        logger.info(
            "Reset handover after release chat_session_id=%s agent_id=%s preserved_contact=%s",
            chat_session_id,
            agent_id,
            has_preserved_contact,
        )
    return cleared
