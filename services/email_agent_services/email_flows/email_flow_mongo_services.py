from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import (
    EMAIL_AI_AGENTS_COLLECTION,
    get_email_ai_agent_by_id,
    get_email_ai_agent_id_str,
    normalize_reply_action,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    DEFAULT_AGENT_FLOW_SLUG,
    EMAIL_FLOWS_COLLECTION,
    FLOW_PALETTE_NODE_TYPES,
    FLOW_STATUS_ACTIVE,
    NODE_TYPE_AI_DEPARTMENT_ROUTER,
    NODE_TYPE_AI_RECIPIENTS_GENERATOR,
    NODE_TYPE_CALL_EXTERNAL_TOOL,
    NODE_TYPE_GENERATE_EMAIL,
    NODE_TYPE_LOAD_THREAD_CONTEXT,
    NODE_TYPE_READ_KB,
    NODE_TYPE_READ_TOOLS,
    NODE_TYPE_SAVE_GMAIL_DRAFT,
    NODE_TYPE_SEND_EMAIL,
    REPLY_ACTION_MODE_AUTO_SEND,
    REPLY_ACTION_MODE_DRAFT,
)
from services.email_agent_services.email_flows.email_flow_graph_services import (
    build_canvas_edges,
    build_default_flow_name,
    build_flow_nodes_from_agent,
    build_flow_summary,
    get_default_flow_layout,
    merge_stored_node_layout,
    normalize_stored_flow_nodes,
    nodes_have_overlapping_horizontal_layout,
    relayout_flow_nodes,
)
from services.email_agent_services.email_flows.email_flow_validation_services import (
    resolve_external_tool_ids_from_config,
)
from services.email_agent_services.email_flows.email_flow_sync_services import (
    extract_agent_fields_from_flow,
    get_node_editor_schema,
    push_flow_to_agent,
)
from services.email_agent_services.email_knowledge.email_knowledge_mongo_services import (
    get_knowledge_by_id,
)
from services.email_agent_services.email_recipient_rules.email_recipient_rules_mongo_services import (
    get_recipient_rules_by_ids,
)
from services.email_agent_services.email_routing_rules.email_routing_rules_mongo_services import (
    get_routing_rules_by_ids,
)
from services.email_agent_services.email_tool_definitions.email_tool_definitions_mongo_services import (
    get_tools_by_ids,
)
from services.email_agent_services.gmail_oauth_services import get_gmail_account_by_id
from services.mongo_services import get_collection

logger = get_logger()

FLOW_ALREADY_ATTACHED_MESSAGE = (
    "This workflow is already attached to another email agent. "
    "Create a new workflow or choose an unattached one."
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_flow_id_str(flow: Dict[str, Any]) -> str:
    return str(flow["_id"])


async def get_flow_by_id(flow_id: str) -> Optional[Dict[str, Any]]:
    try:
        object_id = ObjectId(flow_id.strip())
    except InvalidId:
        return None

    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    return await collection.find_one({"_id": object_id})


async def get_agent_attached_to_flow(
    flow_id: str,
    team_id: str,
    *,
    exclude_agent_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Return the agent that currently has this flow_id linked, if any."""
    normalized_flow_id = flow_id.strip()
    normalized_team_id = team_id.strip()
    if not normalized_flow_id:
        return None

    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    query: Dict[str, Any] = {
        "team_id": normalized_team_id,
        "flow_id": normalized_flow_id,
    }

    normalized_exclude = exclude_agent_id.strip()
    if normalized_exclude:
        try:
            query["_id"] = {"$ne": ObjectId(normalized_exclude)}
        except InvalidId:
            return None

    return await collection.find_one(query)


async def build_team_flow_attachment_map(team_id: str) -> Dict[str, Dict[str, Any]]:
    """Map flow_id -> agent document for all agents in a team with a linked workflow."""
    normalized_team_id = team_id.strip()
    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    cursor = collection.find({
        "team_id": normalized_team_id,
        "flow_id": {"$exists": True, "$nin": ["", None]},
    })

    attachment_map: Dict[str, Dict[str, Any]] = {}
    async for agent in cursor:
        linked_flow_id = (agent.get("flow_id") or "").strip()
        if linked_flow_id:
            attachment_map[linked_flow_id] = agent

    return attachment_map


async def validate_flow_available_for_agent(
    flow_id: str,
    team_id: str,
    *,
    exclude_agent_id: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Ensure a workflow exists in the team and is not already attached to another agent.

    Returns an error response dict on failure, or None when valid.
    """
    normalized_flow_id = flow_id.strip()
    normalized_team_id = team_id.strip()

    if not normalized_flow_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "flow_id cannot be empty when attaching a workflow.",
        }

    flow = await get_flow_by_id(normalized_flow_id)
    if not flow:
        return {
            "success": False,
            "status_code": 400,
            "message": "Invalid flow_id. Workflow does not exist.",
        }

    if (flow.get("team_id") or "").strip() != normalized_team_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "Workflow does not belong to your team.",
        }

    attached_agent = await get_agent_attached_to_flow(
        normalized_flow_id,
        normalized_team_id,
        exclude_agent_id=exclude_agent_id,
    )
    if attached_agent:
        return {
            "success": False,
            "status_code": 409,
            "message": FLOW_ALREADY_ATTACHED_MESSAGE,
            "data": {
                "flow_id": normalized_flow_id,
                "attached_agent_id": get_email_ai_agent_id_str(attached_agent),
                "attached_agent_name": attached_agent.get("name", ""),
            },
        }

    return None


async def set_agent_flow_id(agent_id: str, flow_id: str) -> None:
    try:
        agent_object_id = ObjectId(agent_id.strip())
    except InvalidId:
        raise ValueError("Invalid agent_id.")

    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    await collection.update_one(
        {"_id": agent_object_id},
        {"$set": {"flow_id": flow_id.strip(), "updated_at": _utc_now()}},
    )


async def create_default_flow_for_agent(agent: Dict[str, Any]) -> str:
    """Insert a new non-deletable default workflow for a team (not stored on the flow doc)."""
    agent_id = get_email_ai_agent_id_str(agent)
    team_id = (agent.get("team_id") or "").strip()
    now = _utc_now()
    nodes = build_flow_nodes_from_agent(agent)
    flow_name = build_default_flow_name(agent.get("name", ""))

    document = {
        "team_id": team_id,
        "name": flow_name,
        "slug": DEFAULT_AGENT_FLOW_SLUG,
        "description": "Default inbound reply workflow generated from agent configuration.",
        "is_system_default": True,
        "is_deletable": False,
        "is_editable": True,
        "version": 1,
        "status": FLOW_STATUS_ACTIVE,
        "nodes": nodes,
        "summary": build_flow_summary(agent, len(nodes)),
        "created_at": now,
        "updated_at": now,
    }

    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    result = await collection.insert_one(document)
    flow_id = str(result.inserted_id)

    await collection.update_one(
        {"_id": result.inserted_id},
        {"$set": {"flow_id": flow_id}},
    )

    logger.info(
        f"Created default email flow {flow_id} for team {team_id} "
        f"(linked to agent {agent_id} via email-ai-agents.flow_id)"
    )
    return flow_id


async def sync_flow_from_agent(flow_id: str, agent: Dict[str, Any]) -> None:
    """
    Rebuild a linked workflow graph from the current agent configuration.

    Agent-only fields (system_prompt, gmail_account_id, etc.) are never stored on the flow.
    Editable workflows keep stored node positions; graph structure follows agent optional nodes.
    """
    flow = await get_flow_by_id(flow_id)
    if not flow:
        raise ValueError("Flow not found.")

    agent_id = get_email_ai_agent_id_str(agent)
    linked_flow_id = (agent.get("flow_id") or "").strip()
    if linked_flow_id != flow_id.strip():
        raise ValueError("Flow is not linked to this agent.")

    if (flow.get("team_id") or "").strip() != (agent.get("team_id") or "").strip():
        raise ValueError("Flow does not belong to this agent's team.")

    existing_nodes = flow.get("nodes") or []
    nodes = build_flow_nodes_from_agent(agent, existing_nodes)

    if flow.get("is_editable", False):
        nodes = merge_stored_node_layout(nodes, existing_nodes)
        nodes = normalize_stored_flow_nodes(nodes)
        if nodes_have_overlapping_horizontal_layout(nodes):
            nodes = relayout_flow_nodes(nodes)
    else:
        nodes = relayout_flow_nodes(nodes)

    now = _utc_now()
    update_fields: Dict[str, Any] = {
        "nodes": nodes,
        "summary": build_flow_summary(agent, len(nodes)),
        "updated_at": now,
    }

    if flow.get("is_system_default"):
        update_fields["name"] = build_default_flow_name(agent.get("name", ""))

    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    await collection.update_one(
        {"_id": flow["_id"]},
        {"$set": update_fields},
    )

    logger.info(f"Synced email flow {flow_id} from agent {agent_id}")


async def attach_flow_to_agent(agent: Dict[str, Any], flow_id: str) -> Dict[str, Any]:
    """
    Link a workflow to an agent and push node config from the workflow onto the agent.

    The workflow canvas is preserved (not rebuilt from agent). Syncable agent fields
    (knowledge_id, tool_ids, routing/recipient rules, email_format_template, llm_model,
    reply_action) are overwritten from flow nodes. system_prompt and gmail_account_id
    are not changed.

    Caller must validate availability before attaching an existing flow_id.
    """
    normalized_flow_id = flow_id.strip()
    flow = await get_flow_by_id(normalized_flow_id)
    if not flow:
        raise ValueError("Flow not found.")

    if (flow.get("team_id") or "").strip() != (agent.get("team_id") or "").strip():
        raise ValueError("Flow does not belong to this agent's team.")

    agent_id = get_email_ai_agent_id_str(agent)
    await set_agent_flow_id(agent_id, normalized_flow_id)

    flow_nodes = flow.get("nodes") or []
    synced_field_keys = await push_flow_to_agent(agent, flow_nodes)
    synced_fields = extract_agent_fields_from_flow(flow_nodes)
    updated_agent = {**agent, "flow_id": normalized_flow_id, **synced_fields}

    logger.info(
        f"Attached flow {normalized_flow_id} to agent {agent_id} "
        f"(pushed config: {synced_field_keys or list(synced_fields.keys())})"
    )
    return updated_agent


async def ensure_and_sync_agent_flow(agent: Dict[str, Any]) -> str:
    """
    Ensure the agent has a linked workflow.

    Creates a new default flow when missing; otherwise syncs agent.flow_id only.
    """
    agent_id = get_email_ai_agent_id_str(agent)
    linked_flow_id = (agent.get("flow_id") or "").strip()

    if linked_flow_id:
        linked_flow = await get_flow_by_id(linked_flow_id)
        if linked_flow and (linked_flow.get("team_id") or "").strip() == (agent.get("team_id") or "").strip():
            await sync_flow_from_agent(linked_flow_id, agent)
            return linked_flow_id

    flow_id = await create_default_flow_for_agent(agent)
    await attach_flow_to_agent(agent, flow_id)
    return flow_id


def _infer_tail_mode_from_nodes(nodes: List[Dict[str, Any]]) -> str:
    for node in nodes:
        node_type = (node.get("type") or "").strip()
        if node_type == NODE_TYPE_SEND_EMAIL:
            return REPLY_ACTION_MODE_AUTO_SEND
        if node_type == NODE_TYPE_SAVE_GMAIL_DRAFT:
            return REPLY_ACTION_MODE_DRAFT
    return REPLY_ACTION_MODE_DRAFT


def _serialize_flow_summary(
    flow: Dict[str, Any],
    *,
    attached_agent: Dict[str, Any] | None,
    gmail_account: Dict[str, Any] | None,
) -> Dict[str, Any]:
    flow_id = get_flow_id_str(flow)
    nodes = flow.get("nodes") or []
    is_attached = attached_agent is not None

    return {
        "flow_id": flow_id,
        "attached_agent_id": get_email_ai_agent_id_str(attached_agent) if attached_agent else "",
        "attached_agent_name": attached_agent.get("name", "") if attached_agent else "",
        "gmail_account_id": attached_agent.get("gmail_account_id", "") if attached_agent else "",
        "inbox_name": gmail_account.get("inbox_name", "") if gmail_account else "",
        "email_address": gmail_account.get("email_address", "") if gmail_account else "",
        "name": flow.get("name", ""),
        "slug": flow.get("slug", DEFAULT_AGENT_FLOW_SLUG),
        "summary": flow.get("summary") or build_flow_summary(attached_agent or {}, len(nodes)),
        "node_count": len(nodes),
        "is_system_default": bool(flow.get("is_system_default")),
        "is_deletable": bool(flow.get("is_deletable", True)),
        "is_editable": bool(flow.get("is_editable", False)),
        "is_attached": is_attached,
        "status": flow.get("status", FLOW_STATUS_ACTIVE),
        "created_at": _format_datetime(flow.get("created_at")),
        "updated_at": _format_datetime(flow.get("updated_at")),
    }


async def list_team_email_flows(team_id: str) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()
    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    cursor = collection.find({"team_id": normalized_team_id}).sort("updated_at", -1)
    attachment_map = await build_team_flow_attachment_map(normalized_team_id)

    summaries: List[Dict[str, Any]] = []
    async for flow in cursor:
        flow_id = get_flow_id_str(flow)
        attached_agent = attachment_map.get(flow_id)
        gmail_account = None
        if attached_agent:
            gmail_account = await get_gmail_account_by_id(attached_agent.get("gmail_account_id", ""))

        summaries.append(
            _serialize_flow_summary(
                flow,
                attached_agent=attached_agent,
                gmail_account=gmail_account,
            )
        )

    return {
        "success": True,
        "status_code": 200,
        "message": "Email flows fetched successfully.",
        "data": {
            "team_id": normalized_team_id,
            "count": len(summaries),
            "flows": summaries,
        },
    }


async def _build_node_binding(
    node: Dict[str, Any],
    *,
    agent: Dict[str, Any] | None,
    gmail_account: Dict[str, Any] | None,
) -> Dict[str, Any]:
    node_type = (node.get("type") or "").strip()
    config = node.get("config") or {}
    binding: Dict[str, Any] = {
        "synced_from": "agent" if agent else "flow",
    }

    if node_type == NODE_TYPE_LOAD_THREAD_CONTEXT:
        binding["gmail_account_id"] = (agent.get("gmail_account_id") or "").strip() if agent else ""
        binding["inbox_name"] = gmail_account.get("inbox_name", "") if gmail_account else ""
        binding["email_address"] = gmail_account.get("email_address", "") if gmail_account else ""
        return binding

    if node_type == NODE_TYPE_READ_KB:
        knowledge_id = (config.get("knowledge_id") or (agent.get("knowledge_id") if agent else "") or "").strip()
        binding["knowledge_id"] = knowledge_id
        knowledge = await get_knowledge_by_id(knowledge_id) if knowledge_id else None
        binding["title"] = knowledge.get("title", "") if knowledge else ""
        return binding

    if node_type == NODE_TYPE_READ_TOOLS:
        tool_ids = config.get("tool_ids") or (agent.get("tool_ids") if agent else []) or []
        tools_map = await get_tools_by_ids([str(tool_id) for tool_id in tool_ids])
        binding["tools"] = [
            {
                "tool_id": tool_id,
                "name": tools_map[tool_id].get("name", ""),
                "display_name": tools_map[tool_id].get("display_name", ""),
            }
            for tool_id in tool_ids
            if tool_id in tools_map
        ]
        return binding

    if node_type == NODE_TYPE_AI_DEPARTMENT_ROUTER:
        routing_rule_ids = config.get("routing_rule_ids") or (agent.get("routing_rule_ids") if agent else []) or []
        rules_map = await get_routing_rules_by_ids([str(rule_id) for rule_id in routing_rule_ids])
        binding["routing_rules"] = [
            {
                "routing_rule_id": rule_id,
                "rule_name": rules_map[rule_id].get("rule_name", ""),
                "department_id": rules_map[rule_id].get("department_id", ""),
            }
            for rule_id in routing_rule_ids
            if rule_id in rules_map
        ]
        return binding

    if node_type == NODE_TYPE_AI_RECIPIENTS_GENERATOR:
        recipient_rule_ids = config.get("recipient_rule_ids") or (agent.get("recipient_rule_ids") if agent else []) or []
        rules_map = await get_recipient_rules_by_ids([str(rule_id) for rule_id in recipient_rule_ids])
        binding["recipient_rules"] = [
            {
                "recipient_rule_id": rule_id,
                "rule_name": rules_map[rule_id].get("rule_name", ""),
            }
            for rule_id in recipient_rule_ids
            if rule_id in rules_map
        ]
        return binding

    if node_type == NODE_TYPE_GENERATE_EMAIL:
        binding["llm_model"] = (config.get("llm_model") or (agent.get("llm_model") if agent else "") or "").strip()
        return binding

    if node_type in (NODE_TYPE_SAVE_GMAIL_DRAFT, NODE_TYPE_SEND_EMAIL):
        reply_action = normalize_reply_action(
            config.get("reply_action") or (agent.get("reply_action") if agent else None)
        )
        binding["reply_action"] = reply_action
        if reply_action.get("mode") == REPLY_ACTION_MODE_AUTO_SEND:
            binding["label_hint"] = (
                f"Auto-send when confidence >= {reply_action.get('auto_send_min_confidence', 0.8):g} "
                "(otherwise save draft)"
            )
        else:
            binding["label_hint"] = "Always save a Gmail draft"
        return binding

    if node_type == NODE_TYPE_CALL_EXTERNAL_TOOL:
        external_tool_ids = resolve_external_tool_ids_from_config(config)
        tools_map = await get_tools_by_ids([str(tool_id) for tool_id in external_tool_ids])
        binding["tools"] = [
            {
                "tool_id": tool_id,
                "name": tools_map[tool_id].get("name", ""),
                "display_name": tools_map[tool_id].get("display_name", ""),
            }
            for tool_id in external_tool_ids
            if tool_id in tools_map
        ]
        binding["synced_from"] = "flow"
        return binding

    return binding


async def _build_flow_detail_data(
    flow: Dict[str, Any],
    *,
    team_id: str,
    attached_agent: Dict[str, Any] | None,
) -> Dict[str, Any]:
    flow_id = get_flow_id_str(flow)
    raw_nodes = flow.get("nodes") or []
    if flow.get("is_editable", False):
        nodes = normalize_stored_flow_nodes(raw_nodes)
        if nodes_have_overlapping_horizontal_layout(nodes):
            nodes = relayout_flow_nodes(nodes)
    else:
        nodes = relayout_flow_nodes(raw_nodes)
    gmail_account = None
    if attached_agent:
        gmail_account = await get_gmail_account_by_id(attached_agent.get("gmail_account_id", ""))

    hydrated_nodes = []
    for node in nodes:
        hydrated_nodes.append({
            **node,
            "binding": await _build_node_binding(
                node,
                agent=attached_agent,
                gmail_account=gmail_account,
            ),
        })

    if attached_agent:
        reply_action = normalize_reply_action(attached_agent.get("reply_action"))
        tail_mode = reply_action.get("mode", REPLY_ACTION_MODE_DRAFT)
        summary_source = attached_agent
    else:
        tail_mode = _infer_tail_mode_from_nodes(nodes)
        summary_source = {}

    return {
        "flow_id": flow_id,
        "attached_agent_id": get_email_ai_agent_id_str(attached_agent) if attached_agent else "",
        "attached_agent_name": attached_agent.get("name", "") if attached_agent else "",
        "team_id": team_id.strip(),
        "gmail_account_id": attached_agent.get("gmail_account_id", "") if attached_agent else "",
        "inbox_name": gmail_account.get("inbox_name", "") if gmail_account else "",
        "email_address": gmail_account.get("email_address", "") if gmail_account else "",
        "name": flow.get("name", ""),
        "summary": flow.get("summary") or build_flow_summary(summary_source, len(hydrated_nodes)),
        "is_system_default": bool(flow.get("is_system_default")),
        "is_deletable": bool(flow.get("is_deletable", True)),
        "is_editable": bool(flow.get("is_editable", False)),
        "is_read_only": not bool(flow.get("is_editable", False)),
        "is_attached": attached_agent is not None,
        "tail_mode": tail_mode,
        "layout": get_default_flow_layout(),
        "node_editor_schema": get_node_editor_schema(),
        "validation_rules": {
            "required_nodes": ["start", "load_thread_context", "generate_email", "stop"],
            "required_tail": "exactly_one_of: save_gmail_draft | send_email",
            "first_after_start": "load_thread_context",
            "before_tail": "generate_email",
            "optional_middle_nodes": [
                "read_kb",
                "read_tools",
                "ai_department_router",
                "ai_recipients_generator",
            ],
            "optional_post_tail_node": "call_external_tool",
            "call_external_tool_rules": (
                "At most one Call External Tool node. When present: "
                "tail → call_external_tool → stop. "
                "config.external_tools is flow-only (not synced to agent)."
            ),
            "linear_chain_only": True,
            "agent_sync_on_save_when_attached": True,
            "system_prompt_not_on_canvas": True,
        },
        "palette_node_types": list(FLOW_PALETTE_NODE_TYPES),
        "nodes": hydrated_nodes,
        "edges": build_canvas_edges(hydrated_nodes),
        "created_at": _format_datetime(flow.get("created_at")),
        "updated_at": _format_datetime(flow.get("updated_at")),
    }


async def get_flow_detail(flow_id: str, team_id: str) -> Dict[str, Any]:
    """Fetch a workflow by flow_id with hydrated nodes for the flow-builder canvas."""
    normalized_flow_id = flow_id.strip()
    normalized_team_id = team_id.strip()

    flow = await get_flow_by_id(normalized_flow_id)
    if not flow:
        return {
            "success": False,
            "status_code": 404,
            "message": "Email flow not found.",
        }

    if (flow.get("team_id") or "").strip() != normalized_team_id:
        return {
            "success": False,
            "status_code": 403,
            "message": "Email flow does not belong to your team.",
        }

    attached_agent = await get_agent_attached_to_flow(normalized_flow_id, normalized_team_id)

    return {
        "success": True,
        "status_code": 200,
        "message": "Email flow fetched successfully.",
        "data": await _build_flow_detail_data(
            flow,
            team_id=normalized_team_id,
            attached_agent=attached_agent,
        ),
    }


async def get_flow_for_agent_detail(agent_id: str, team_id: str) -> Dict[str, Any]:
    normalized_agent_id = agent_id.strip()
    normalized_team_id = team_id.strip()

    agent = await get_email_ai_agent_by_id(normalized_agent_id)
    if not agent:
        return {
            "success": False,
            "status_code": 404,
            "message": "Email AI agent not found.",
        }

    if (agent.get("team_id") or "").strip() != normalized_team_id:
        return {
            "success": False,
            "status_code": 403,
            "message": "Email AI agent does not belong to your team.",
        }

    flow_id = (agent.get("flow_id") or "").strip()
    if not flow_id:
        return {
            "success": False,
            "status_code": 404,
            "message": (
                "This agent has no linked workflow yet. Update the agent once to generate "
                "or attach a workflow."
            ),
        }

    flow = await get_flow_by_id(flow_id)
    if not flow:
        return {
            "success": False,
            "status_code": 404,
            "message": "Linked workflow not found. Update the agent to recreate or reattach one.",
        }

    if (flow.get("team_id") or "").strip() != normalized_team_id:
        return {
            "success": False,
            "status_code": 403,
            "message": "Linked workflow does not belong to your team.",
        }

    return {
        "success": True,
        "status_code": 200,
        "message": "Email flow fetched successfully.",
        "data": await _build_flow_detail_data(
            flow,
            team_id=normalized_team_id,
            attached_agent=agent,
        ),
    }
