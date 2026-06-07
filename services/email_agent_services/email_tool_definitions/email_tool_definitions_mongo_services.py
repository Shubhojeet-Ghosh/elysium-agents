from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_tool_definitions.email_tool_definitions_constants import (
    EMAIL_TOOLS_COLLECTION,
)
from services.mongo_services import get_collection

logger = get_logger()


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_tool_id_str(tool: Dict[str, Any]) -> str:
    return str(tool["_id"])


def _format_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tool_id": get_tool_id_str(tool),
        "team_id": tool.get("team_id", ""),
        "name": tool.get("name", ""),
        "display_name": tool.get("display_name", ""),
        "description": tool.get("description", ""),
        "endpoint_url": tool.get("endpoint_url", ""),
        "http_method": tool.get("http_method", ""),
        "inputs": tool.get("inputs", []),
        "input_schema": tool.get("input_schema", {}),
        "status": tool.get("status", "active"),
        "created_at": _format_datetime(tool.get("created_at")),
        "updated_at": _format_datetime(tool.get("updated_at")),
    }


async def get_tools_by_ids(tool_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple tools by MongoDB _id. Returns map of id string -> document."""
    if not tool_ids:
        return {}

    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    object_ids = []

    for tool_id in tool_ids:
        try:
            object_ids.append(ObjectId(tool_id.strip()))
        except InvalidId:
            continue

    if not object_ids:
        return {}

    tools: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})

    async for tool in cursor:
        tools[get_tool_id_str(tool)] = tool

    return tools


async def get_tool_by_id(tool_id: str) -> Optional[Dict[str, Any]]:
    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    try:
        object_id = ObjectId(tool_id.strip())
    except InvalidId:
        return None
    return await collection.find_one({"_id": object_id})


async def get_tool_by_team_and_name(team_id: str, name: str) -> Optional[Dict[str, Any]]:
    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    return await collection.find_one({"team_id": team_id.strip(), "name": name.strip().lower()})


async def insert_tool(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    result = await collection.insert_one(document)
    return _format_tool({"_id": result.inserted_id, **document})


async def list_team_tools(team_id: str) -> List[Dict[str, Any]]:
    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    cursor = collection.find({"team_id": team_id.strip()}).sort("created_at", -1)

    tools: List[Dict[str, Any]] = []
    async for tool in cursor:
        tools.append(_format_tool(tool))
    return tools


async def delete_tool_by_id(tool_id: str) -> bool:
    collection = get_collection(EMAIL_TOOLS_COLLECTION)
    try:
        object_id = ObjectId(tool_id.strip())
    except InvalidId:
        return False
    result = await collection.delete_one({"_id": object_id})
    return result.deleted_count > 0
