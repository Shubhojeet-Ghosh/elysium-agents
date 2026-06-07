import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from services.email_agent_services.email_flows.email_flow_constants import (
    COMPRESSED_QUERY_MAX_CHARS,
    MESSAGE_PROCESSING_STATUS_PENDING,
)

_QUOTE_LINE_PATTERN = re.compile(r"^>+\s?", re.MULTILINE)


def get_stored_message_id(message: Dict[str, Any]) -> str:
    return str(message.get("_id", ""))


def _format_datetime(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def serialize_for_json(value: Any) -> Any:
    """Recursively convert Mongo/Python types to JSON-safe values."""
    if isinstance(value, dict):
        return {key: serialize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serialize_for_json(item) for item in value]
    if isinstance(value, (datetime, ObjectId)):
        return str(value) if isinstance(value, ObjectId) else _format_datetime(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _normalize_body_text(body_text: str) -> str:
    if not body_text:
        return ""

    lines = body_text.splitlines()
    trimmed_lines: List[str] = []
    for line in lines:
        if _QUOTE_LINE_PATTERN.match(line):
            break
        trimmed_lines.append(line)

    return "\n".join(trimmed_lines).strip()


def trim_message_for_llm(message: Dict[str, Any]) -> Dict[str, Any]:
    body_text = _normalize_body_text(message.get("body_text", "") or "")
    snippet = (message.get("snippet", "") or "").strip()

    return {
        "message_id": get_stored_message_id(message),
        "gmail_message_id": message.get("gmail_message_id", ""),
        "direction": message.get("direction", "inbound"),
        "from": message.get("from", ""),
        "to": message.get("to", []),
        "cc": message.get("cc", []),
        "reply_to": message.get("reply_to", ""),
        "message_id_header": message.get("message_id_header", ""),
        "subject": message.get("subject", ""),
        "snippet": snippet,
        "body_text": body_text,
        "received_at": _format_datetime(message.get("received_at")),
        "is_new": message.get("is_new", False),
        "is_trigger": message.get("is_trigger", False),
    }


def is_message_pending_for_flow(message: Dict[str, Any]) -> bool:
    if message.get("direction") != "inbound":
        return False
    return message.get("processing_status") == MESSAGE_PROCESSING_STATUS_PENDING


def annotate_messages_for_flow(
    messages: List[Dict[str, Any]],
    *,
    trigger_message_id: str = "",
) -> List[Dict[str, Any]]:
    normalized_trigger = trigger_message_id.strip()
    annotated: List[Dict[str, Any]] = []

    for message in messages:
        message_copy = dict(message)
        stored_id = get_stored_message_id(message)
        gmail_message_id = (message.get("gmail_message_id") or "").strip()

        is_trigger = bool(
            normalized_trigger
            and normalized_trigger in {stored_id, gmail_message_id}
        )
        is_new = is_message_pending_for_flow(message)

        message_copy["is_trigger"] = is_trigger
        message_copy["is_new"] = is_new
        annotated.append(message_copy)

    return annotated


def find_message_by_reference(
    messages: List[Dict[str, Any]],
    message_reference: str,
) -> Optional[Dict[str, Any]]:
    normalized_reference = message_reference.strip()
    if not normalized_reference:
        return None

    for message in messages:
        stored_id = get_stored_message_id(message)
        gmail_message_id = (message.get("gmail_message_id") or "").strip()
        if normalized_reference in {stored_id, gmail_message_id}:
            return message

    return None


def find_latest_pending_inbound(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pending_inbound = [
        message
        for message in messages
        if is_message_pending_for_flow(message)
    ]
    if not pending_inbound:
        return None
    return pending_inbound[-1]


def find_latest_inbound(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    inbound_messages = [
        message for message in messages if message.get("direction") == "inbound"
    ]
    if not inbound_messages:
        return None
    return inbound_messages[-1]


def build_compressed_query(
    *,
    subject: str,
    latest_inbound: Dict[str, Any],
    max_chars: int = COMPRESSED_QUERY_MAX_CHARS,
) -> str:
    subject_text = (subject or latest_inbound.get("subject", "")).strip()
    snippet = (latest_inbound.get("snippet", "") or "").strip()
    body_text = _normalize_body_text(latest_inbound.get("body_text", "") or "")

    parts: List[str] = []
    if subject_text:
        parts.append(subject_text)
    if snippet:
        parts.append(snippet)
    if body_text:
        parts.append(body_text)

    combined = " ".join(part for part in parts if part).strip()
    if len(combined) <= max_chars:
        return combined

    if subject_text and snippet:
        head = f"{subject_text} {snippet}".strip()
        if len(head) >= max_chars:
            return head[:max_chars].strip()

    return combined[:max_chars].strip()


def build_initial_flow_context(
    *,
    agent_id: str,
    team_id: str,
    thread_id: str,
    trigger_message_id: str,
    system_prompt: str = "",
    email_format_template: str = "",
    run_id: str = "",
) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "team_id": team_id,
        "thread_id": thread_id,
        "trigger_message_id": trigger_message_id,
        "system_prompt": system_prompt,
        "email_format_template": email_format_template,
        "compressed_query": "",
        "compressed_query_meta": {},
        "thread": {},
        "kb_chunks": [],
        "kb_title": "",
        "kb_knowledge_id": "",
        "registered_tools": [],
        "tool_results": [],
        "tools_planned": [],
        "routing": {
            "department_id": "",
            "routing_rule_id": "",
            "rule_name": "",
            "decision_source": "",
            "reason": "",
        },
        "recipients": {},
        "draft": {},
        "external_actions": [],
        "final_action": {},
        "errors": [],
        "node_logs": [],
    }
