from datetime import datetime, timezone
from typing import Any, Dict, List

from logging_config import get_logger
from services.email_agent_services.email_tool_definitions.email_tool_definitions_constants import (
    ALLOWED_HTTP_METHODS,
)
from services.email_agent_services.email_tool_definitions.email_tool_definitions_mongo_services import (
    delete_tool_by_id,
    get_tool_by_id,
    get_tool_by_team_and_name,
    insert_tool,
    list_team_tools,
)
from services.email_agent_services.email_tool_definitions.email_tool_schema_builder import (
    build_input_schema,
    normalize_tool_name,
    validate_inputs,
    validate_tool_name,
)

logger = get_logger()


def _normalize_http_method(http_method: str) -> str:
    return http_method.strip().upper()


def _serialize_inputs(inputs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "name": item.name.strip(),
            "type": item.type.strip().lower(),
            "description": item.description.strip(),
            "required": item.required,
        }
        for item in inputs
    ]


async def create_email_tool_definition(
    team_id: str,
    name: str,
    display_name: str,
    description: str,
    endpoint_url: str,
    http_method: str,
    inputs: List[Any],
) -> Dict[str, Any]:
    """Register an external HTTP tool for LLM tool calling."""
    normalized_team_id = team_id.strip()
    normalized_name = normalize_tool_name(name)
    normalized_display_name = display_name.strip()
    normalized_description = description.strip()
    normalized_endpoint_url = endpoint_url.strip()
    normalized_http_method = _normalize_http_method(http_method)
    serialized_inputs = _serialize_inputs(inputs)

    name_error = validate_tool_name(normalized_name)
    if name_error:
        return {"success": False, "status_code": 400, "message": name_error}

    if not normalized_display_name:
        return {"success": False, "status_code": 400, "message": "display_name cannot be empty."}
    if not normalized_description:
        return {"success": False, "status_code": 400, "message": "description cannot be empty."}
    if not normalized_endpoint_url:
        return {"success": False, "status_code": 400, "message": "endpoint_url cannot be empty."}
    if normalized_http_method not in ALLOWED_HTTP_METHODS:
        return {
            "success": False,
            "status_code": 400,
            "message": f"http_method must be one of: {', '.join(sorted(ALLOWED_HTTP_METHODS))}",
        }

    inputs_error = validate_inputs(serialized_inputs)
    if inputs_error:
        return {"success": False, "status_code": 400, "message": inputs_error}

    try:
        existing = await get_tool_by_team_and_name(normalized_team_id, normalized_name)
        if existing:
            return {
                "success": False,
                "status_code": 400,
                "message": f"A tool named '{normalized_name}' already exists for this team.",
            }

        now = datetime.now(timezone.utc)
        input_schema = build_input_schema(serialized_inputs)

        document = {
            "team_id": normalized_team_id,
            "name": normalized_name,
            "display_name": normalized_display_name,
            "description": normalized_description,
            "endpoint_url": normalized_endpoint_url,
            "http_method": normalized_http_method,
            "inputs": serialized_inputs,
            "input_schema": input_schema,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }

        tool_data = await insert_tool(document)

        logger.info(
            f"Created email tool {tool_data['tool_id']} for team {normalized_team_id}: "
            f"{normalized_name}"
        )

        return {
            "success": True,
            "status_code": 201,
            "message": "Tool created successfully.",
            "data": tool_data,
        }

    except Exception as e:
        logger.error(f"Failed to create email tool for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create tool.",
        }


async def list_team_email_tool_definitions(team_id: str) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()

    try:
        tools = await list_team_tools(normalized_team_id)

        return {
            "success": True,
            "status_code": 200,
            "message": "Team tools fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(tools),
                "tools": tools,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list tools for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team tools.",
        }


async def delete_email_tool_definition(tool_id: str) -> Dict[str, Any]:
    normalized_tool_id = tool_id.strip()

    try:
        tool_doc = await get_tool_by_id(normalized_tool_id)
        if not tool_doc:
            return {
                "success": False,
                "status_code": 404,
                "message": "Tool not found.",
            }

        deleted = await delete_tool_by_id(normalized_tool_id)
        if not deleted:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to delete tool.",
            }

        logger.info(f"Deleted email tool {normalized_tool_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Tool deleted successfully.",
            "data": {
                "tool_id": normalized_tool_id,
                "team_id": tool_doc.get("team_id", ""),
                "name": tool_doc.get("name", ""),
            },
        }

    except Exception as e:
        logger.error(f"Failed to delete tool {normalized_tool_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to delete tool.",
        }
