from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import (
    EMAIL_AI_AGENTS_COLLECTION,
    get_email_ai_agent_id_str,
    normalize_reply_action,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
    NODE_TYPE_CALL_EXTERNAL_TOOL,
    NODE_TYPE_GENERATE_EMAIL,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
    NODE_TYPE_START,
    NODE_TYPE_STOP,
    REPLY_ACTION_MODE_AUTO_SEND,
    REPLY_ACTION_MODE_DRAFT,
)
from services.email_agent_services.email_flows.email_flow_validation_services import (
    build_linear_chain,
)
from services.mongo_services import get_collection

logger = get_logger()

# Fields workflow → agent sync may update. Intentionally excludes agent-only fields
# (system_prompt, gmail_account_id, name, user_id, team_id, flow_id, sync state, etc.).
FLOW_TO_AGENT_SYNC_FIELD_KEYS = frozenset({
    "knowledge_id",
    "tool_ids",
    "routing_rule_ids",
    "recipient_rule_ids",
    "email_format_template",
    "llm_model",
    "reply_action",
})

# Never written by flow attach/save sync — edited only via agent settings APIs.
AGENT_ONLY_CONFIG_FIELD_KEYS = frozenset({
    "system_prompt",
    "gmail_account_id",
    "name",
    "user_id",
    "team_id",
    "flow_id",
    "status",
    "activated_at",
    "sync_status",
    "last_synced_at",
    "last_sync_error",
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _nodes_by_type(nodes: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        node_type = (node.get("type") or "").strip()
        grouped.setdefault(node_type, []).append(node)
    return grouped


def extract_agent_fields_from_flow(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Map syncable workflow node config → email-ai-agents fields.

    Agent document remains runtime source of truth; this is applied when a linked workflow is saved.
    """
    nodes_by_type = _nodes_by_type(nodes)
    updates: Dict[str, Any] = {}

    read_kb_nodes = nodes_by_type.get(NODE_TYPE_READ_KB, [])
    if read_kb_nodes:
        knowledge_id = (read_kb_nodes[0].get("config") or {}).get("knowledge_id", "")
        updates["knowledge_id"] = str(knowledge_id).strip()
    else:
        updates["knowledge_id"] = ""

    read_tools_nodes = nodes_by_type.get(NODE_TYPE_READ_TOOLS, [])
    if read_tools_nodes:
        tool_ids = (read_tools_nodes[0].get("config") or {}).get("tool_ids") or []
        updates["tool_ids"] = [str(tool_id).strip() for tool_id in tool_ids if str(tool_id).strip()]
    else:
        updates["tool_ids"] = []

    router_nodes = nodes_by_type.get(NODE_TYPE_AI_DEPARTMENT_ROUTER, [])
    if router_nodes:
        routing_rule_ids = (router_nodes[0].get("config") or {}).get("routing_rule_ids") or []
        updates["routing_rule_ids"] = [
            str(rule_id).strip() for rule_id in routing_rule_ids if str(rule_id).strip()
        ]
    else:
        updates["routing_rule_ids"] = []

    recipient_nodes = nodes_by_type.get(NODE_TYPE_AI_RECIPIENTS_GENERATOR, [])
    if recipient_nodes:
        recipient_rule_ids = (recipient_nodes[0].get("config") or {}).get("recipient_rule_ids") or []
        updates["recipient_rule_ids"] = [
            str(rule_id).strip() for rule_id in recipient_rule_ids if str(rule_id).strip()
        ]
    else:
        updates["recipient_rule_ids"] = []

    generate_nodes = nodes_by_type.get(NODE_TYPE_GENERATE_EMAIL, [])
    if generate_nodes:
        generate_config = generate_nodes[0].get("config") or {}
        format_prompt = (generate_config.get("format_prompt") or "").strip()
        updates["email_format_template"] = format_prompt
        llm_model = (generate_config.get("llm_model") or "").strip()
        if llm_model:
            updates["llm_model"] = llm_model

    send_nodes = nodes_by_type.get(NODE_TYPE_SEND_EMAIL, [])
    draft_nodes = nodes_by_type.get(NODE_TYPE_SAVE_GMAIL_DRAFT, [])

    if send_nodes:
        send_config = send_nodes[0].get("config") or {}
        reply_action = normalize_reply_action(send_config.get("reply_action"))
        reply_action["mode"] = REPLY_ACTION_MODE_AUTO_SEND
        updates["reply_action"] = reply_action
    elif draft_nodes:
        draft_config = draft_nodes[0].get("config") or {}
        reply_action = normalize_reply_action(draft_config.get("reply_action"))
        reply_action["mode"] = REPLY_ACTION_MODE_DRAFT
        updates["reply_action"] = reply_action

    return updates


async def push_flow_to_agent(agent: Dict[str, Any], nodes: List[Dict[str, Any]]) -> List[str]:
    """
    Apply workflow node config to the linked email AI agent document.

    Uses an allowlist so agent-only fields (especially system_prompt) are never modified.
    Returns the list of agent field keys that were written.
    """
    agent_id = get_email_ai_agent_id_str(agent)
    raw_fields = extract_agent_fields_from_flow(nodes)
    update_fields = {
        key: value
        for key, value in raw_fields.items()
        if key in FLOW_TO_AGENT_SYNC_FIELD_KEYS
    }
    if not update_fields:
        return []

    update_fields["updated_at"] = _utc_now()
    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    await collection.update_one({"_id": agent["_id"]}, {"$set": update_fields})
    synced_keys = [key for key in update_fields if key != "updated_at"]
    logger.info(f"Pushed workflow config from flow to agent {agent_id}: {synced_keys}")
    return synced_keys


def get_node_editor_schema() -> Dict[str, Any]:
    """Frontend panel schema: which fields each node type exposes in the right-side editor."""
    return {
        NODE_TYPE_START: {
            "editable": False,
            "note": "No configuration. System prompt is edited on the agent settings page only.",
        },
        NODE_TYPE_LOAD_THREAD_CONTEXT: {
            "editable": False,
            "note": "Uses the agent's linked Gmail inbox at runtime.",
        },
        NODE_TYPE_READ_KB: {
            "editable": True,
            "fields": [
                {
                    "key": "knowledge_id",
                    "label": "Knowledge base",
                    "input": "knowledge_picker",
                    "required": True,
                },
            ],
        },
        NODE_TYPE_READ_TOOLS: {
            "editable": True,
            "fields": [
                {
                    "key": "tool_ids",
                    "label": "Tools",
                    "input": "tool_multi_picker",
                    "required": False,
                    "max_items": 20,
                },
            ],
        },
        NODE_TYPE_AI_DEPARTMENT_ROUTER: {
            "editable": True,
            "fields": [
                {
                    "key": "routing_rule_ids",
                    "label": "Routing rules",
                    "input": "routing_rule_multi_picker",
                    "required": False,
                },
            ],
        },
        NODE_TYPE_AI_RECIPIENTS_GENERATOR: {
            "editable": True,
            "fields": [
                {
                    "key": "recipient_rule_ids",
                    "label": "Recipient rules",
                    "input": "recipient_rule_multi_picker",
                    "required": False,
                },
            ],
        },
        NODE_TYPE_GENERATE_EMAIL: {
            "editable": True,
            "fields": [
                {
                    "key": "format_prompt",
                    "label": "Email format template",
                    "input": "textarea",
                    "maps_to_agent_field": "email_format_template",
                },
                {
                    "key": "llm_model",
                    "label": "LLM model",
                    "input": "llm_model_picker",
                    "maps_to_agent_field": "llm_model",
                },
            ],
        },
        NODE_TYPE_SAVE_GMAIL_DRAFT: {
            "editable": True,
            "fields": [
                {
                    "key": "reply_action.mode",
                    "value": REPLY_ACTION_MODE_DRAFT,
                    "input": "readonly",
                    "note": "Sets agent reply_action.mode to draft when saved.",
                },
            ],
        },
        NODE_TYPE_SEND_EMAIL: {
            "editable": True,
            "fields": [
                {
                    "key": "reply_action.auto_send_min_confidence",
                    "label": "Auto-send min confidence",
                    "input": "number",
                    "min": 0,
                    "max": 1,
                    "step": 0.05,
                    "maps_to_agent_field": "reply_action.auto_send_min_confidence",
                },
                {
                    "key": "reply_action.mode",
                    "value": REPLY_ACTION_MODE_AUTO_SEND,
                    "input": "readonly",
                    "note": "Sets agent reply_action.mode to auto_send when saved.",
                },
            ],
        },
        NODE_TYPE_CALL_EXTERNAL_TOOL: {
            "editable": True,
            "fields": [
                {
                    "key": "external_tools",
                    "label": "External tools",
                    "input": "tool_multi_picker",
                    "required": False,
                    "max_items": 20,
                },
            ],
        },
        NODE_TYPE_STOP: {
            "editable": False,
        },
    }
