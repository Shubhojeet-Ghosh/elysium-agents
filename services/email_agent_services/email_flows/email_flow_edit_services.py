from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import (
    _validate_knowledge_for_team,
    _validate_recipient_rules_for_team,
    _validate_routing_rules_for_team,
    _validate_tools_for_team,
    get_email_ai_agent_by_id,
    get_email_ai_agent_id_str,
    normalize_reply_action,
)
from services.email_agent_services.email_flows.email_flow_constants import (
    CUSTOM_FLOW_SLUG,
    EMAIL_FLOWS_COLLECTION,
    FLOW_STATUS_ACTIVE,
    NODE_TYPE_SEND_EMAIL,
)
from services.email_agent_services.email_flows.email_flow_graph_services import (
    build_flow_summary,
    build_minimal_flow_scaffold,
)
from services.email_agent_services.email_flows.email_flow_mongo_services import (
    get_agent_attached_to_flow,
    get_flow_by_id,
    get_flow_detail,
    get_flow_id_str,
)
from services.email_agent_services.email_flows.email_flow_sync_services import (
    extract_agent_fields_from_flow,
    push_flow_to_agent,
)
from services.email_agent_services.email_flows.email_flow_validation_services import (
    extract_call_external_tool_config,
    normalize_call_external_tool_nodes,
    resolve_external_tool_ids_from_config,
    validate_flow_graph,
)
from services.mongo_services import get_collection

logger = get_logger()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _nodes_from_payload(raw_nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(node) for node in raw_nodes]


async def _validate_flow_config_values_for_team(
    nodes: List[Dict[str, Any]],
    team_id: str,
) -> Optional[Dict[str, Any]]:
    extracted = extract_agent_fields_from_flow(nodes)

    knowledge_id = extracted.get("knowledge_id")
    if knowledge_id:
        validation_error = await _validate_knowledge_for_team(knowledge_id, team_id)
        if validation_error:
            return validation_error

    tool_ids = extracted.get("tool_ids")
    if tool_ids:
        validation_error = await _validate_tools_for_team(
            tool_ids,
            team_id,
            require_at_least_one=False,
        )
        if validation_error:
            return validation_error

    routing_rule_ids = extracted.get("routing_rule_ids")
    if routing_rule_ids:
        validation_error = await _validate_routing_rules_for_team(routing_rule_ids, team_id)
        if validation_error:
            return validation_error

    recipient_rule_ids = extracted.get("recipient_rule_ids")
    if recipient_rule_ids:
        validation_error = await _validate_recipient_rules_for_team(recipient_rule_ids, team_id)
        if validation_error:
            return validation_error

    external_config = extract_call_external_tool_config(nodes)
    if external_config:
        external_tool_ids = resolve_external_tool_ids_from_config(external_config)
        if external_tool_ids:
            validation_error = await _validate_tools_for_team(
                external_tool_ids,
                team_id,
                require_at_least_one=False,
            )
            if validation_error:
                return validation_error

    for node in nodes:
        if (node.get("type") or "").strip() == NODE_TYPE_SEND_EMAIL:
            reply_action = normalize_reply_action((node.get("config") or {}).get("reply_action"))
            confidence = reply_action.get("auto_send_min_confidence")
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                return {
                    "success": False,
                    "status_code": 400,
                    "message": "Send Email node requires a valid auto_send_min_confidence between 0 and 1.",
                }
            if value < 0 or value > 1:
                return {
                    "success": False,
                    "status_code": 400,
                    "message": "Send Email auto_send_min_confidence must be between 0 and 1.",
                }

    return None


async def create_team_email_flow(
    team_id: str,
    name: str,
    description: str = "",
) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()
    normalized_name = name.strip()
    normalized_description = description.strip()

    if not normalized_name:
        return {
            "success": False,
            "status_code": 400,
            "message": "Workflow name cannot be empty.",
        }

    nodes = build_minimal_flow_scaffold()
    now = _utc_now()

    document = {
        "team_id": normalized_team_id,
        "name": normalized_name,
        "slug": CUSTOM_FLOW_SLUG,
        "description": normalized_description or "Custom email workflow.",
        "is_system_default": False,
        "is_deletable": True,
        "is_editable": True,
        "version": 1,
        "status": FLOW_STATUS_ACTIVE,
        "nodes": nodes,
        "summary": f"Custom workflow · {len(nodes)} nodes · Draft only",
        "created_at": now,
        "updated_at": now,
    }

    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    result = await collection.insert_one(document)
    flow_id = str(result.inserted_id)
    await collection.update_one({"_id": result.inserted_id}, {"$set": {"flow_id": flow_id}})

    logger.info(f"Created custom email flow {flow_id} for team {normalized_team_id}")

    detail = await get_flow_detail(flow_id, normalized_team_id)
    if detail.get("success"):
        return {
            "success": True,
            "status_code": 201,
            "message": "Email workflow created successfully.",
            "data": detail["data"],
        }

    return {
        "success": True,
        "status_code": 201,
        "message": "Email workflow created successfully.",
        "data": {"flow_id": flow_id},
    }


async def update_team_email_flow(
    team_id: str,
    flow_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()
    normalized_flow_id = flow_id.strip()
    normalized_nodes = normalize_call_external_tool_nodes(_nodes_from_payload(nodes))

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

    if not flow.get("is_editable", True):
        return {
            "success": False,
            "status_code": 403,
            "message": "This workflow is read-only and cannot be edited.",
        }

    graph_error = validate_flow_graph(normalized_nodes)
    if graph_error:
        return graph_error

    config_error = await _validate_flow_config_values_for_team(normalized_nodes, normalized_team_id)
    if config_error:
        return config_error

    attached_agent = await get_agent_attached_to_flow(normalized_flow_id, normalized_team_id)
    summary_source: Dict[str, Any] = attached_agent or {}
    if attached_agent:
        summary_source = {**attached_agent, **extract_agent_fields_from_flow(normalized_nodes)}

    now = _utc_now()
    update_fields: Dict[str, Any] = {
        "nodes": normalized_nodes,
        "summary": build_flow_summary(summary_source, len(normalized_nodes)),
        "updated_at": now,
    }

    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            return {
                "success": False,
                "status_code": 400,
                "message": "Workflow name cannot be empty.",
            }
        update_fields["name"] = normalized_name

    if description is not None:
        update_fields["description"] = description.strip()

    collection = get_collection(EMAIL_FLOWS_COLLECTION)
    await collection.update_one({"_id": flow["_id"]}, {"$set": update_fields})

    attached_agent_id = ""
    agent_synced = False
    if attached_agent:
        attached_agent_id = get_email_ai_agent_id_str(attached_agent)
        await push_flow_to_agent(attached_agent, normalized_nodes)
        agent_synced = True
        attached_agent = await get_email_ai_agent_by_id(attached_agent_id)

    logger.info(f"Updated email flow {normalized_flow_id} for team {normalized_team_id}")

    detail = await get_flow_detail(normalized_flow_id, normalized_team_id)
    if not detail.get("success"):
        return {
            "success": True,
            "status_code": 200,
            "message": "Workflow saved.",
            "data": {"flow_id": normalized_flow_id},
        }

    detail_data = detail["data"]
    detail_data["agent_synced"] = agent_synced
    detail_data["attached_agent_id"] = attached_agent_id
    return {
        "success": True,
        "status_code": 200,
        "message": "Workflow saved.",
        "data": detail_data,
    }
