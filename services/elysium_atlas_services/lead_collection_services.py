"""
Lead collection runtime pipeline for visitor chat (Phase 1b).

Handles passive extraction, trigger evaluation, session lead state, atlas_leads upsert,
and prompt injection for the main chat LLM.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Type

from pydantic import BaseModel, Field, create_model

from config.lead_collection_config import (
    ALLOWED_LEAD_FIELD_KEYS,
    COLLECTION_TRIGGER_PROMPT_KEY,
    ENABLE_LEAD_CAPTURING_KEY,
    FIELDS_KEY,
    LEAD_FIELD_CATALOG,
    MIN_MESSAGES_BEFORE_ASK_KEY,
    normalize_lead_collection_config,
)
from config.lead_collection_constants import (
    ATLAS_LEADS_COLLECTION,
    DEFAULT_LEADS_LIST_PAGE_SIZE,
    LEAD_CHAT_HISTORY_LIMIT,
    LEAD_DOCUMENT_STATUS_COMPLETE,
    LEAD_DOCUMENT_STATUS_PARTIAL,
    LEAD_EXTRACTION_MODEL,
    LEAD_STATUS_COLLECTING,
    LEAD_STATUS_COMPLETE,
    LEAD_STATUS_NOT_STARTED,
    LEAD_STATUS_PARTIAL,
    LEAD_TRIGGER_MODEL,
    MAX_LEADS_LIST_PAGE_SIZE,
)
from config.structured_output_models import LeadCollectionTriggerResult
from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_services import (
    format_utc_datetime_for_client,
    get_chat_messages_for_session,
    patch_chat_session,
)
from services.mongo_services import get_collection
from services.open_ai_services import openai_structured_output

logger = get_logger()

_FIELD_LABELS: dict[str, str] = {
    item["key"]: item["label"] for item in LEAD_FIELD_CATALOG
}

ERR_SESSION_NOT_FOUND = "SESSION_NOT_FOUND"

_FIELD_EXTRACTION_HINTS: dict[str, str] = {
    "email": "Return only the bare email address (e.g. user@example.com). No filler words or surrounding text.",
    "name": (
        "Return only the person's full name in natural casing (e.g. Shubhojeet Ghosh). "
        "Recognize patterns like 'I am X', 'I'm X', 'my name is X', 'call me X'. "
        "No filler like 'my name is' or 'it's'."
    ),
    "phone": "Return only the phone number (digits with optional leading +). No filler or surrounding text.",
    "company": "Return only the company or organization name. No filler or surrounding text.",
    "interest": "Return a concise phrase summarizing their interest. No filler or surrounding text.",
}


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _empty_fields_map(configured_keys: list[str]) -> dict[str, str | None]:
    return {key: None for key in configured_keys}


def init_lead_session_state(configured_keys: list[str]) -> dict[str, Any]:
    return {
        "status": LEAD_STATUS_NOT_STARTED,
        "triggered_at_message": None,
        "trigger_reason": None,
        "fields": _empty_fields_map(configured_keys),
        "next_field": None,
        "skipped_fields": [],
        "declined_fields": [],
        "completed_at": None,
    }


def get_lead_session_state(
    session_doc: dict[str, Any] | None,
    configured_keys: list[str],
) -> dict[str, Any]:
    """Return normalized lead_collection state from a chat session document."""
    state = init_lead_session_state(configured_keys)
    if not session_doc:
        return state

    embedded = session_doc.get("lead_collection")
    if not isinstance(embedded, dict):
        return state

    if embedded.get("status") in {
        LEAD_STATUS_NOT_STARTED,
        LEAD_STATUS_COLLECTING,
        LEAD_STATUS_PARTIAL,
        LEAD_STATUS_COMPLETE,
    }:
        state["status"] = embedded["status"]

    for key in ("triggered_at_message", "trigger_reason", "next_field", "completed_at"):
        if key in embedded:
            state[key] = embedded[key]

    stored_fields = embedded.get("fields")
    if isinstance(stored_fields, dict):
        for field_key in configured_keys:
            value = stored_fields.get(field_key)
            if isinstance(value, str) and value.strip():
                state["fields"][field_key] = value.strip()

    skipped = embedded.get("skipped_fields")
    if isinstance(skipped, list):
        state["skipped_fields"] = [
            key for key in skipped if key in configured_keys
        ]

    declined = embedded.get("declined_fields")
    if isinstance(declined, list):
        state["declined_fields"] = [
            key for key in declined if key in configured_keys
        ]

    return state


def _configured_field_keys(lead_config: dict[str, Any]) -> list[str]:
    fields = lead_config.get(FIELDS_KEY) or []
    keys: list[str] = []
    for item in fields:
        if isinstance(item, dict):
            key = item.get("key")
            if key in ALLOWED_LEAD_FIELD_KEYS and key not in keys:
                keys.append(key)
    return keys


def _field_required(lead_config: dict[str, Any], field_key: str) -> bool:
    for item in lead_config.get(FIELDS_KEY) or []:
        if isinstance(item, dict) and item.get("key") == field_key:
            return bool(item.get("required"))
    return False


def _ordered_field_keys(lead_config: dict[str, Any]) -> list[str]:
    fields = [
        item for item in (lead_config.get(FIELDS_KEY) or [])
        if isinstance(item, dict) and item.get("key") in ALLOWED_LEAD_FIELD_KEYS
    ]
    return [item["key"] for item in sorted(fields, key=lambda row: int(row.get("order") or 0))]


def count_visitor_messages(
    messages: list[dict[str, Any]],
    *,
    include_current: bool = False,
) -> int:
    count = sum(1 for msg in messages if msg.get("role") == "user")
    if include_current:
        count += 1
    return count


def _format_conversation_for_llm(
    messages: list[dict[str, Any]],
    current_message: str,
) -> str:
    """Full conversation with speaker labels (for trigger evaluation)."""
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        speaker = "Visitor" if role == "user" else "Agent"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{speaker}: {content}")
    current = (current_message or "").strip()
    if current:
        lines.append(f"Visitor: {current}")
    return "\n".join(lines)


def _format_visitor_messages_for_extraction(
    messages: list[dict[str, Any]],
    current_message: str,
) -> str:
    """Visitor-only transcript for lead field extraction (Agent messages excluded)."""
    lines: list[str] = []
    seen: set[str] = set()

    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if content and content not in seen:
            lines.append(f"Visitor: {content}")
            seen.add(content)

    current = (current_message or "").strip()
    if current and current not in seen:
        lines.append(f"Visitor: {current}")

    return "\n".join(lines)


def _build_lead_extraction_model(
    field_keys: list[str],
    *,
    include_refusal: bool,
) -> Type[BaseModel]:
    field_defs: dict[str, Any] = {}
    for key in field_keys:
        label = _FIELD_LABELS.get(key, key)
        format_hint = _FIELD_EXTRACTION_HINTS.get(key, "Return only the exact value. No filler or surrounding text.")
        field_defs[key] = (
            str | None,
            Field(
                default=None,
                description=(
                    f"Extract {label} only if the Visitor explicitly provided it in their own "
                    "messages. Must be null if only the Agent mentioned it or if not provided. "
                    f"{format_hint}"
                ),
            ),
        )
    if include_refusal:
        field_defs["refused_field"] = (
            str | None,
            Field(
                default=None,
                description=(
                    "If the visitor explicitly declines to provide the field currently being "
                    "asked for, set this to that field key; otherwise null."
                ),
            ),
        )
    return create_model("LeadFieldsExtraction", **field_defs)


def _merge_extracted_fields(
    lead_state: dict[str, Any],
    extracted: dict[str, Any],
    configured_keys: list[str],
) -> None:
    fields = lead_state.setdefault("fields", _empty_fields_map(configured_keys))
    for key in configured_keys:
        value = extracted.get(key)
        if isinstance(value, str) and value.strip():
            fields[key] = value.strip()
            declined = lead_state.get("declined_fields") or []
            if key in declined:
                lead_state["declined_fields"] = [item for item in declined if item != key]


def _has_any_captured_field(lead_state: dict[str, Any]) -> bool:
    fields = lead_state.get("fields") or {}
    return any(isinstance(value, str) and value.strip() for value in fields.values())


def _all_required_fields_captured(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
) -> bool:
    fields = lead_state.get("fields") or {}
    skipped = set(lead_state.get("skipped_fields") or [])
    for item in lead_config.get(FIELDS_KEY) or []:
        if not isinstance(item, dict) or not item.get("required"):
            continue
        key = item.get("key")
        if key in skipped:
            continue
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip():
            return False
    return True


def _missing_field_keys(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
) -> list[str]:
    fields = lead_state.get("fields") or {}
    return [
        key
        for key in _ordered_field_keys(lead_config)
        if not isinstance(fields.get(key), str) or not fields[key].strip()
    ]


def _compute_next_field(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
) -> str | None:
    fields = lead_state.get("fields") or {}
    skipped = set(lead_state.get("skipped_fields") or [])
    declined = set(lead_state.get("declined_fields") or [])
    for key in _ordered_field_keys(lead_config):
        if key in skipped or key in declined:
            continue
        value = fields.get(key)
        if not isinstance(value, str) or not value.strip():
            return key
    return None


def _recompute_lead_status(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
) -> None:
    if lead_state.get("status") == LEAD_STATUS_COMPLETE:
        return

    if _all_required_fields_captured(lead_config, lead_state):
        lead_state["status"] = LEAD_STATUS_COMPLETE
        lead_state["next_field"] = None
        if not lead_state.get("completed_at"):
            lead_state["completed_at"] = _utc_now()
        return

    next_field = _compute_next_field(lead_config, lead_state)
    lead_state["next_field"] = next_field

    if lead_state.get("status") == LEAD_STATUS_NOT_STARTED:
        # Passive capture only — next_field tracks what's missing but no proactive ask yet.
        return

    if lead_state.get("status") in {LEAD_STATUS_COLLECTING, LEAD_STATUS_PARTIAL}:
        if next_field:
            lead_state["status"] = (
                LEAD_STATUS_PARTIAL if _has_any_captured_field(lead_state) else LEAD_STATUS_COLLECTING
            )
        elif _has_any_captured_field(lead_state):
            lead_state["status"] = LEAD_STATUS_PARTIAL


def derive_lead_list_status(lead_state: dict[str, Any] | None) -> str | None:
    """Map session lead state to dashboard badge: null | partial | complete."""
    if not lead_state:
        return None

    status = lead_state.get("status")
    if status == LEAD_STATUS_COMPLETE:
        return LEAD_DOCUMENT_STATUS_COMPLETE
    if status in {LEAD_STATUS_COLLECTING, LEAD_STATUS_PARTIAL}:
        return LEAD_DOCUMENT_STATUS_PARTIAL
    if status == LEAD_STATUS_NOT_STARTED and _has_any_captured_field(lead_state):
        return LEAD_DOCUMENT_STATUS_PARTIAL
    return None


def _serialize_lead_datetime_for_client(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return format_utc_datetime_for_client(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def get_updatable_lead_field_keys(lead_config: dict[str, Any]) -> list[str]:
    """Keys a team member may set manually — configured fields, or full catalog if unset."""
    configured = _ordered_field_keys(lead_config)
    if configured:
        return configured
    return sorted(ALLOWED_LEAD_FIELD_KEYS)


def _build_field_rows_for_client(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
    field_keys: list[str],
) -> list[dict[str, Any]]:
    config_fields = [
        item for item in (lead_config.get(FIELDS_KEY) or [])
        if isinstance(item, dict) and item.get("key") in ALLOWED_LEAD_FIELD_KEYS
    ]
    config_by_key = {item["key"]: item for item in config_fields}
    stored_fields = lead_state.get("fields") or {}

    rows: list[dict[str, Any]] = []
    if config_fields:
        ordered_items = sorted(config_fields, key=lambda row: int(row.get("order") or 0))
    else:
        ordered_items = [
            {"key": key, "required": False, "order": index}
            for index, key in enumerate(field_keys, start=1)
        ]

    for item in ordered_items:
        key = item["key"]
        raw_value = stored_fields.get(key)
        value = raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None
        rows.append(
            {
                "key": key,
                "label": _FIELD_LABELS.get(key, key),
                "required": bool(config_by_key.get(key, item).get("required")),
                "order": int(config_by_key.get(key, item).get("order") or item.get("order") or 0),
                "value": value,
                "captured": value is not None,
            }
        )
    return rows


def build_lead_collection_client_summary(
    lead_config: dict[str, Any] | None,
    session_lead: dict[str, Any] | None,
) -> dict[str, Any]:
    """Shape lead collection state for socket list rows and HTTP API responses."""
    normalized_config = normalize_lead_collection_config(lead_config or {})
    enabled = bool(normalized_config.get(ENABLE_LEAD_CAPTURING_KEY))
    field_keys = get_updatable_lead_field_keys(normalized_config)

    lead_state = get_lead_session_state(
        {"lead_collection": session_lead} if isinstance(session_lead, dict) else None,
        field_keys,
    )
    field_rows = _build_field_rows_for_client(normalized_config, lead_state, field_keys)

    return {
        "enabled": enabled,
        "list_status": derive_lead_list_status(lead_state),
        "status": lead_state.get("status"),
        "trigger_reason": lead_state.get("trigger_reason"),
        "triggered_at_message": lead_state.get("triggered_at_message"),
        "completed_at": _serialize_lead_datetime_for_client(lead_state.get("completed_at")),
        "next_field": lead_state.get("next_field"),
        "declined_fields": list(lead_state.get("declined_fields") or []),
        "skipped_fields": list(lead_state.get("skipped_fields") or []),
        "fields": field_rows,
    }


def build_session_lead_update_user_message(
    summary: dict[str, Any],
    updated_keys: list[str],
) -> str:
    """Human-friendly confirmation for team members after saving contact details."""
    labels = [_FIELD_LABELS.get(key, key.replace("_", " ").title()) for key in updated_keys]
    if len(labels) == 1:
        saved_part = f"{labels[0]} saved"
    elif len(labels) == 2:
        saved_part = f"{labels[0]} and {labels[1]} saved"
    elif len(labels) > 2:
        saved_part = "Contact details saved"
    else:
        saved_part = "Contact details saved"

    if summary.get("list_status") == LEAD_DOCUMENT_STATUS_COMPLETE:
        return f"{saved_part}. This lead is complete."

    missing_required = [
        field["label"]
        for field in summary.get("fields", [])
        if field.get("required") and not field.get("captured")
    ]
    if missing_required:
        if len(missing_required) == 1:
            return f"{saved_part}. Still needed: {missing_required[0]}."
        return f"{saved_part}. Still needed: {', '.join(missing_required)}."

    return f"{saved_part}."


def map_session_lead_update_error(error_code: str) -> str:
    """Map internal error codes to user-facing copy."""
    messages = {
        ERR_SESSION_NOT_FOUND: "This conversation couldn't be found. Refresh the page and try again.",
        "NO_FIELDS": "Add at least one contact field to save.",
        "INVALID_FIELD": "That contact field isn't available for this agent.",
        "INVALID_VALUE": "Please check the contact details and try again.",
        "VALUE_TOO_LONG": "Contact details are too long. Please shorten and try again.",
    }
    return messages.get(error_code, "Something went wrong while saving contact details. Please try again.")


def apply_lead_field_updates(
    lead_state: dict[str, Any],
    field_updates: dict[str, str | None],
    *,
    allowed_keys: list[str],
) -> str | None:
    """Merge manual field updates into lead state. Returns error code or None."""
    if not field_updates:
        return "NO_FIELDS"

    unknown = [key for key in field_updates if key not in allowed_keys]
    if unknown:
        return "INVALID_FIELD"

    fields = lead_state.setdefault("fields", {})
    for key, raw_value in field_updates.items():
        if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
            fields[key] = None
            continue
        if not isinstance(raw_value, str):
            return "INVALID_VALUE"
        normalized = raw_value.strip()
        if len(normalized) > 500:
            return "VALUE_TOO_LONG"
        fields[key] = normalized
        declined = lead_state.get("declined_fields") or []
        if key in declined:
            lead_state["declined_fields"] = [item for item in declined if item != key]
        skipped = lead_state.get("skipped_fields") or []
        if key in skipped:
            lead_state["skipped_fields"] = [item for item in skipped if item != key]

    return None


async def update_session_lead_by_team_member(
    *,
    agent_id: str,
    chat_session_id: str,
    field_updates: dict[str, str | None],
    agent_data: dict[str, Any] | None = None,
    lead_config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Apply partial lead field updates for a chat session (human agent manual edit).

    Returns:
        (response_payload, error_message)
    """
    from services.elysium_atlas_services.lead_collection_config_services import (
        get_lead_collection_config_for_agent,
    )

    normalized_config = normalize_lead_collection_config(
        lead_config if lead_config is not None else (await get_lead_collection_config_for_agent(agent_id)) or {}
    )
    allowed_keys = get_updatable_lead_field_keys(normalized_config)

    sessions = get_collection("atlas_chat_sessions")
    session_doc = await sessions.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
    )
    if not session_doc:
        return None, ERR_SESSION_NOT_FOUND

    lead_state = get_lead_session_state(session_doc, allowed_keys)
    error_code = apply_lead_field_updates(
        lead_state,
        field_updates,
        allowed_keys=allowed_keys,
    )
    if error_code:
        return None, error_code

    if lead_state.get("status") == LEAD_STATUS_NOT_STARTED and _has_any_captured_field(lead_state):
        lead_state["status"] = LEAD_STATUS_PARTIAL

    _recompute_lead_status(normalized_config, lead_state)

    team_id = (agent_data or {}).get("team_id")
    if team_id is not None:
        team_id = str(team_id)

    await persist_lead_collection_state(agent_id, chat_session_id, lead_state)
    await upsert_atlas_lead(
        agent_id=agent_id,
        chat_session_id=chat_session_id,
        team_id=team_id,
        lead_state=lead_state,
    )

    summary = build_lead_collection_client_summary(normalized_config, lead_state)
    return {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "message": build_session_lead_update_user_message(summary, list(field_updates.keys())),
        "lead_collection": summary,
        "lead_status": summary.get("list_status"),
        "lead_email": next(
            (row["value"] for row in summary.get("fields", []) if row.get("key") == "email" and row.get("captured")),
            None,
        ),
        "lead_name": next(
            (row["value"] for row in summary.get("fields", []) if row.get("key") == "name" and row.get("captured")),
            None,
        ),
    }, None


def build_lead_prompt_block(
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
) -> str | None:
    status = lead_state.get("status")
    next_field = lead_state.get("next_field")
    declined = set(lead_state.get("declined_fields") or [])
    if status not in {LEAD_STATUS_COLLECTING, LEAD_STATUS_PARTIAL} or not next_field:
        return None
    if next_field in declined:
        return None

    label = _FIELD_LABELS.get(next_field, next_field)
    required = _field_required(lead_config, next_field)
    captured_lines: list[str] = []
    for key, value in (lead_state.get("fields") or {}).items():
        if isinstance(value, str) and value.strip():
            captured_lines.append(f"- {_FIELD_LABELS.get(key, key)}: {value.strip()}")

    captured_block = "\n".join(captured_lines) if captured_lines else "- None yet"

    requirement_line = (
        "This field is required — politely ask again if not provided."
        if required
        else (
            "This field is optional — if the visitor declines, acknowledge and move on "
            "without blocking the conversation."
        )
    )

    return (
        "LEAD COLLECTION (follow these rules for this reply only):\n"
        "- Answer the visitor's question or request first.\n"
        "- Then ask for one piece of contact information.\n"
        "- Ask for only the next missing field listed below.\n"
        "- Briefly confirm any newly captured values before asking for the next field.\n"
        "- Do not re-ask fields already captured.\n"
        f"- Next field to collect: **{label}** (`{next_field}`).\n"
        f"- {requirement_line}\n\n"
        f"Already captured:\n{captured_block}"
    )


async def _extract_lead_fields_from_message(
    message: str,
    lead_config: dict[str, Any],
    lead_state: dict[str, Any],
    visitor_messages_text: str,
) -> dict[str, Any]:
    configured_keys = _configured_field_keys(lead_config)
    if not configured_keys:
        return {}

    include_refusal = lead_state.get("status") in {LEAD_STATUS_COLLECTING, LEAD_STATUS_PARTIAL}
    model_cls = _build_lead_extraction_model(configured_keys, include_refusal=include_refusal)

    next_field = lead_state.get("next_field")
    missing_fields = _missing_field_keys(lead_config, lead_state)
    refusal_hint = ""
    if include_refusal and next_field:
        label = _FIELD_LABELS.get(next_field, next_field)
        refusal_hint = (
            f"\nThe agent is currently asking for: {label} (`{next_field}`). "
            "If the visitor explicitly refuses in their latest message (e.g. 'no', "
            "'I can't tell you'), set refused_field to that field key; otherwise null."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "Extract lead/contact field values ONLY from Visitor messages. "
                "Each line is prefixed with 'Visitor:' — use those lines as the sole source. "
                "NEVER extract values that appear only in Agent/assistant messages "
                "(e.g. support emails, example addresses, or contact info the bot suggested). "
                "Return null for any field the visitor has not personally provided. "
                "Do not invent data.\n\n"
                "Scan ALL visitor messages in the transcript — not just the latest line. "
                "If a field appears in multiple messages, use the most recent valid value. "
                "A visitor may refuse a field early then provide it later; always capture "
                "the latest provided value.\n\n"
                "NORMALIZATION: Return the exact clean value only — never the full conversational "
                "sentence. Strip filler words (e.g. 'yeah', 'sure', 'it's', 'my email is'). "
                "Examples: 'yeah it's john@acme.com' → email: 'john@acme.com'; "
                "'I'm Priya Sharma' → name: 'Priya Sharma'; "
                "'I am shubh, I need agents' → name: 'Shubh'."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Configured fields: {', '.join(configured_keys)}\n"
                f"Fields still missing: {', '.join(missing_fields) if missing_fields else 'none'}\n\n"
                f"Visitor messages (extract from these only):\n"
                f"{visitor_messages_text or '(no visitor messages yet)'}"
                f"{refusal_hint}"
            ),
        },
    ]

    try:
        return await openai_structured_output(
            model=LEAD_EXTRACTION_MODEL,
            messages=messages,
            response_format=model_cls,
        )
    except Exception as exc:
        logger.warning(f"Lead field extraction failed: {exc}")
        return {}


async def _evaluate_collection_trigger(
    lead_config: dict[str, Any],
    conversation_text: str,
) -> dict[str, Any]:
    trigger_prompt = (lead_config.get(COLLECTION_TRIGGER_PROMPT_KEY) or "").strip()
    messages = [
        {
            "role": "system",
            "content": (
                "You decide whether to start collecting visitor contact details based on "
                "the owner's rule and the conversation so far. Be conservative — only "
                "return should_collect=true when the rule clearly applies."
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
            model=LEAD_TRIGGER_MODEL,
            messages=messages,
            response_format=LeadCollectionTriggerResult,
        )
        return {
            "should_collect": bool(result.get("should_collect")),
            "reason": (result.get("reason") or "").strip(),
        }
    except Exception as exc:
        logger.warning(f"Lead collection trigger evaluation failed: {exc}")
        return {"should_collect": False, "reason": ""}


def _lead_document_status(lead_state: dict[str, Any]) -> str:
    if lead_state.get("status") == LEAD_STATUS_COMPLETE:
        return LEAD_DOCUMENT_STATUS_COMPLETE
    return LEAD_DOCUMENT_STATUS_PARTIAL


async def upsert_atlas_lead(
    *,
    agent_id: str,
    chat_session_id: str,
    team_id: str | None,
    lead_state: dict[str, Any],
) -> None:
    if not _has_any_captured_field(lead_state):
        return

    collection = get_collection(ATLAS_LEADS_COLLECTION)
    now = _utc_now()
    fields = {
        key: value
        for key, value in (lead_state.get("fields") or {}).items()
        if isinstance(value, str) and value.strip()
    }
    doc_status = _lead_document_status(lead_state)

    existing = await collection.find_one(
        {"agent_id": agent_id, "chat_session_id": chat_session_id},
        {"lead_id": 1, "created_at": 1},
    )

    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "chat_session_id": chat_session_id,
        "team_id": team_id,
        "status": doc_status,
        "fields": fields,
        "trigger_reason": lead_state.get("trigger_reason"),
        "triggered_at_message": lead_state.get("triggered_at_message"),
        "updated_at": now,
    }

    if doc_status == LEAD_DOCUMENT_STATUS_COMPLETE:
        payload["completed_at"] = lead_state.get("completed_at") or now

    if existing:
        await collection.update_one(
            {"agent_id": agent_id, "chat_session_id": chat_session_id},
            {"$set": payload},
        )
    else:
        payload["lead_id"] = str(uuid.uuid4())
        payload["created_at"] = now
        if doc_status != LEAD_DOCUMENT_STATUS_COMPLETE:
            payload["completed_at"] = None
        await collection.insert_one(payload)


async def persist_lead_collection_state(
    agent_id: str,
    chat_session_id: str,
    lead_state: dict[str, Any],
) -> None:
    completed_at = lead_state.get("completed_at")
    if isinstance(completed_at, datetime.datetime):
        completed_at_value = completed_at
    else:
        completed_at_value = None

    await patch_chat_session(
        agent_id,
        chat_session_id,
        {
            "lead_collection": {
                "status": lead_state.get("status"),
                "triggered_at_message": lead_state.get("triggered_at_message"),
                "trigger_reason": lead_state.get("trigger_reason"),
                "fields": lead_state.get("fields") or {},
                "next_field": lead_state.get("next_field"),
                "skipped_fields": lead_state.get("skipped_fields") or [],
                "declined_fields": lead_state.get("declined_fields") or [],
                "completed_at": completed_at_value,
            },
        },
    )


async def process_lead_collection_turn(
    *,
    agent_id: str,
    chat_session_id: str,
    message: str,
    chat_session_data: dict[str, Any],
    chat_history: list[dict[str, Any]],
    lead_config: dict[str, Any] | None,
    agent_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Run the lead collection pipeline for one visitor message.

    Returns:
        dict with keys:
            - prompt_block: str | None — inject into main LLM when collecting
            - lead_state: dict | None — updated session lead state
    """
    normalized_config = normalize_lead_collection_config(lead_config or {})
    if not normalized_config.get(ENABLE_LEAD_CAPTURING_KEY):
        return {"prompt_block": None, "lead_state": None}

    configured_keys = _configured_field_keys(normalized_config)
    if not configured_keys:
        return {"prompt_block": None, "lead_state": None}

    lead_state = get_lead_session_state(chat_session_data, configured_keys)
    if lead_state.get("status") == LEAD_STATUS_COMPLETE:
        return {"prompt_block": None, "lead_state": lead_state}

    conversation_id = chat_session_data.get("conversation_id")
    full_history = await get_chat_messages_for_session(
        agent_id,
        chat_session_id,
        limit=LEAD_CHAT_HISTORY_LIMIT,
        conversation_id=conversation_id,
    )
    visitor_count = count_visitor_messages(full_history, include_current=True)
    conversation_text = _format_conversation_for_llm(full_history, message)
    visitor_messages_text = _format_visitor_messages_for_extraction(full_history, message)

    extracted = await _extract_lead_fields_from_message(
        message,
        normalized_config,
        lead_state,
        visitor_messages_text,
    )
    _merge_extracted_fields(lead_state, extracted, configured_keys)

    refused_field = extracted.get("refused_field")
    if isinstance(refused_field, str) and refused_field in configured_keys:
        declined = lead_state.setdefault("declined_fields", [])
        if refused_field not in declined:
            declined.append(refused_field)
        if not _field_required(normalized_config, refused_field):
            skipped = lead_state.setdefault("skipped_fields", [])
            if refused_field not in skipped:
                skipped.append(refused_field)

    _recompute_lead_status(normalized_config, lead_state)

    min_messages = int(normalized_config.get(MIN_MESSAGES_BEFORE_ASK_KEY) or 2)
    should_evaluate_trigger = (
        lead_state.get("status") == LEAD_STATUS_NOT_STARTED
        and visitor_count >= min_messages
    )

    if should_evaluate_trigger:
        trigger = await _evaluate_collection_trigger(normalized_config, conversation_text)
        if trigger.get("should_collect"):
            lead_state["status"] = LEAD_STATUS_COLLECTING
            lead_state["triggered_at_message"] = visitor_count
            lead_state["trigger_reason"] = trigger.get("reason") or ""
            _recompute_lead_status(normalized_config, lead_state)

    prompt_block = build_lead_prompt_block(normalized_config, lead_state)
    if lead_state.get("status") == LEAD_STATUS_COMPLETE:
        prompt_block = None

    team_id = (agent_data or {}).get("team_id")
    if team_id is not None:
        team_id = str(team_id)

    await persist_lead_collection_state(agent_id, chat_session_id, lead_state)
    await upsert_atlas_lead(
        agent_id=agent_id,
        chat_session_id=chat_session_id,
        team_id=team_id,
        lead_state=lead_state,
    )

    return {"prompt_block": prompt_block, "lead_state": lead_state}


def _normalize_leads_list_pagination(page: int, limit: int) -> tuple[int, int]:
    return max(1, page), max(1, min(limit, MAX_LEADS_LIST_PAGE_SIZE))


def _build_leads_list_pagination_meta(total: int, page: int, limit: int) -> dict[str, Any]:
    if total == 0:
        return {
            "total": 0,
            "page": 1,
            "limit": limit,
            "total_pages": 0,
            "has_next": False,
            "has_prev": False,
        }
    total_pages = (total + limit - 1) // limit
    page = min(page, total_pages)
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


def _serialize_lead_list_item(
    doc: dict[str, Any],
    *,
    alias_name: str | None = None,
) -> dict[str, Any]:
    created_at = doc.get("created_at")
    updated_at = doc.get("updated_at")
    return {
        "lead_id": doc.get("lead_id"),
        "agent_id": doc.get("agent_id"),
        "chat_session_id": doc.get("chat_session_id"),
        "alias_name": alias_name,
        "fields": doc.get("fields") or {},
        "status": doc.get("status"),
        "created_at": format_utc_datetime_for_client(created_at)
        if isinstance(created_at, datetime.datetime)
        else None,
        "updated_at": format_utc_datetime_for_client(updated_at)
        if isinstance(updated_at, datetime.datetime)
        else None,
    }


async def list_team_leads(
    team_id: str,
    *,
    agent_id: str | None = None,
    page: int = 1,
    limit: int = DEFAULT_LEADS_LIST_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Return paginated lead documents from atlas_leads for a team.

    When agent_id is omitted, returns leads across all agents on the team,
    sorted by updated_at descending (newest activity first).
    When agent_id is set, narrows to that agent only (same sort).
    """
    page, limit = _normalize_leads_list_pagination(page, limit)
    empty_result = {"leads": [], **_build_leads_list_pagination_meta(0, page, limit)}

    query: dict[str, Any] = {"team_id": str(team_id)}
    if agent_id:
        query["agent_id"] = agent_id

    projection = {
        "_id": 0,
        "lead_id": 1,
        "agent_id": 1,
        "chat_session_id": 1,
        "fields": 1,
        "status": 1,
        "created_at": 1,
        "updated_at": 1,
    }

    try:
        collection = get_collection(ATLAS_LEADS_COLLECTION)
        total = await collection.count_documents(query)
        meta = _build_leads_list_pagination_meta(total, page, limit)
        page = meta["page"]

        if total == 0:
            return empty_result

        skip = (page - 1) * limit
        cursor = (
            collection.find(query, projection)
            .sort([("updated_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )
        lead_docs = [doc async for doc in cursor]

        from services.elysium_atlas_services.atlas_chat_session_services import (
            get_chat_session_alias_names_by_keys,
        )

        session_keys = [
            (str(doc.get("agent_id")), str(doc.get("chat_session_id")))
            for doc in lead_docs
            if doc.get("agent_id") and doc.get("chat_session_id")
        ]
        alias_by_session = await get_chat_session_alias_names_by_keys(session_keys)

        leads = [
            _serialize_lead_list_item(
                doc,
                alias_name=alias_by_session.get(
                    (str(doc.get("agent_id")), str(doc.get("chat_session_id"))),
                ),
            )
            for doc in lead_docs
        ]
        return {"leads": leads, **meta}
    except Exception as exc:
        logger.error(
            "Error listing team leads team_id=%s agent_id=%s: %s",
            team_id,
            agent_id,
            exc,
            exc_info=True,
        )
        return empty_result
