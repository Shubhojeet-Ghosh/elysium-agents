from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from config.atlas_tool_models import (
    CreateToolRequest,
    ToolAuthConfigInput,
    ToolParameterInput,
    UpdateToolAuthConfigInput,
    UpdateToolRequest,
    build_tool_parameters_schema,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_tool_secrets import encrypt_tool_token
from services.mongo_services import get_collection

logger = get_logger()

COLLECTION_NAME = "atlas_tools"


def _build_parameters_schema(parameters: list[ToolParameterInput]) -> dict[str, Any]:
    return build_tool_parameters_schema(parameters)


def _build_auth_document(auth: ToolAuthConfigInput) -> dict[str, Any]:
    if auth.type == "none":
        return {"type": "none"}

    token_prefix = auth.token_prefix or "Bearer"
    if auth.location == "query":
        token_prefix = "none"

    return {
        "type": "api_key",
        "location": auth.location,
        "param_name": auth.param_name.strip(),
        "token_prefix": token_prefix,
        "token_encrypted": encrypt_tool_token(auth.token.strip()),
    }


def _merge_auth_update(
    existing_auth: dict[str, Any],
    auth_update: UpdateToolAuthConfigInput,
) -> dict[str, Any] | None:
    current_type = existing_auth.get("type", "none")
    next_type = auth_update.type or current_type

    if next_type == "none":
        return {"type": "none"}

    location = auth_update.location or existing_auth.get("location")
    param_name = auth_update.param_name or existing_auth.get("param_name")
    token_prefix = auth_update.token_prefix or existing_auth.get("token_prefix", "Bearer")

    if not location:
        return None
    if not param_name or not str(param_name).strip():
        return None

    if location == "query":
        token_prefix = "none"

    merged: dict[str, Any] = {
        "type": "api_key",
        "location": location,
        "param_name": str(param_name).strip(),
        "token_prefix": token_prefix,
    }

    if auth_update.token is not None and auth_update.token.strip():
        merged["token_encrypted"] = encrypt_tool_token(auth_update.token.strip())
    elif existing_auth.get("token_encrypted"):
        merged["token_encrypted"] = existing_auth["token_encrypted"]
    else:
        return None

    return merged


def _serialize_tool_document(document: dict[str, Any]) -> dict[str, Any]:
    auth = document.get("auth") or {"type": "none"}
    serialized_auth: dict[str, Any] = {"type": auth.get("type", "none")}
    if auth.get("type") == "api_key":
        serialized_auth.update(
            {
                "location": auth.get("location"),
                "param_name": auth.get("param_name"),
                "token_prefix": auth.get("token_prefix"),
                "token_configured": bool(auth.get("token_encrypted")),
            }
        )

    created_at = document.get("created_at")
    updated_at = document.get("updated_at")

    return {
        "tool_id": str(document["_id"]),
        "team_id": document.get("team_id"),
        "created_by_user_id": document.get("created_by_user_id"),
        "name": document.get("name"),
        "display_name": document.get("display_name"),
        "description": document.get("description"),
        "api_url": document.get("api_url"),
        "http_method": document.get("http_method"),
        "auth": serialized_auth,
        "parameters": document.get("parameters") or {"type": "object", "properties": {}},
        "is_active": document.get("is_active", True),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
    }


COLLECTION_NAME = "atlas_tools"
MAX_AGENT_TOOL_IDS = 50


async def validate_agent_tool_ids(
    team_id: str,
    tool_ids: Any,
    *,
    max_count: int = MAX_AGENT_TOOL_IDS,
) -> tuple[list[str] | None, str | None]:
    """
    Validate and normalize tool_ids for attachment to an agent.

    Returns:
        (normalized_ids, None) on success, or (None, error_message) on failure.
    """
    if not isinstance(tool_ids, list):
        return None, "tool_ids must be an array of tool ID strings."

    if len(tool_ids) > max_count:
        return None, f"tool_ids cannot contain more than {max_count} items."

    normalized: list[str] = []
    seen: set[str] = set()
    object_ids: list[ObjectId] = []

    for raw_id in tool_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            return None, "Each tool_id must be a non-empty string."
        tool_id = raw_id.strip()
        if tool_id in seen:
            continue
        seen.add(tool_id)
        try:
            object_ids.append(ObjectId(tool_id))
        except InvalidId:
            return None, f"Invalid tool_id: {tool_id}"
        normalized.append(tool_id)

    if not object_ids:
        return [], None

    collection = get_collection(COLLECTION_NAME)
    cursor = collection.find(
        {"_id": {"$in": object_ids}, "team_id": team_id},
        {"_id": 1},
    )
    documents = await cursor.to_list(length=len(object_ids))
    found_ids = {str(doc["_id"]) for doc in documents}
    missing = [tool_id for tool_id in normalized if tool_id not in found_ids]
    if missing:
        return None, "One or more tool_ids are invalid or do not belong to this team."

    return normalized, None


async def get_tool_team_id(tool_id: str) -> str | None:
    try:
        collection = get_collection(COLLECTION_NAME)
        document = await collection.find_one(
            {"_id": ObjectId(tool_id)},
            {"team_id": 1},
        )
        if not document:
            return None
        team_id = document.get("team_id")
        return str(team_id) if team_id else None
    except InvalidId:
        logger.warning(f"Invalid tool_id format: {tool_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching team_id for tool_id={tool_id}: {e}", exc_info=True)
        return None


async def check_tool_name_exists(team_id: str, name: str, exclude_tool_id: str | None = None) -> bool:
    try:
        collection = get_collection(COLLECTION_NAME)
        query: dict[str, Any] = {"team_id": team_id, "name": name}
        if exclude_tool_id:
            query["_id"] = {"$ne": ObjectId(exclude_tool_id)}
        existing = await collection.find_one(query, {"_id": 1})
        return existing is not None
    except InvalidId:
        return False
    except Exception as e:
        logger.error(
            f"Error checking tool name '{name}' for team_id={team_id}: {e}",
            exc_info=True,
        )
        return False


async def create_tool(team_id: str, user_id: str, request: CreateToolRequest) -> dict[str, Any]:
    if await check_tool_name_exists(team_id, request.name):
        return {"success": False, "message": "A tool with this name already exists for this team."}

    current_time = datetime.now(timezone.utc)
    document = {
        "team_id": team_id,
        "created_by_user_id": user_id,
        "name": request.name,
        "display_name": request.display_name.strip(),
        "description": request.description.strip(),
        "api_url": request.api_url,
        "http_method": request.http_method,
        "auth": _build_auth_document(request.auth),
        "parameters": _build_parameters_schema(request.parameters),
        "is_active": True,
        "created_at": current_time,
        "updated_at": current_time,
    }

    collection = get_collection(COLLECTION_NAME)
    try:
        result = await collection.insert_one(document)
    except DuplicateKeyError:
        return {"success": False, "message": "A tool with this name already exists for this team."}

    document["_id"] = result.inserted_id
    logger.info(f"Created tool_id={result.inserted_id} for team_id={team_id}")
    return {"success": True, "tool": _serialize_tool_document(document)}


async def list_tools_for_team(
    team_id: str,
    page: int = 1,
    limit: int = 50,
    include_inactive: bool = False,
) -> dict[str, Any]:
    collection = get_collection(COLLECTION_NAME)
    query: dict[str, Any] = {"team_id": team_id}
    if not include_inactive:
        query["is_active"] = True

    total = await collection.count_documents(query)
    skip = (page - 1) * limit
    cursor = (
        collection.find(query)
        .sort([("updated_at", -1), ("_id", -1)])
        .skip(skip)
        .limit(limit)
    )
    documents = await cursor.to_list(length=limit)
    tools = [_serialize_tool_document(doc) for doc in documents]
    total_pages = max(1, (total + limit - 1) // limit) if total else 0

    return {
        "success": True,
        "tools": tools,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total > 0,
    }


async def get_tool_by_id(tool_id: str) -> dict[str, Any] | None:
    try:
        collection = get_collection(COLLECTION_NAME)
        document = await collection.find_one({"_id": ObjectId(tool_id)})
        if not document:
            return None
        return _serialize_tool_document(document)
    except InvalidId:
        logger.warning(f"Invalid tool_id format: {tool_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching tool_id={tool_id}: {e}", exc_info=True)
        return None


async def update_tool(tool_id: str, request: UpdateToolRequest) -> dict[str, Any]:
    try:
        collection = get_collection(COLLECTION_NAME)
        existing = await collection.find_one({"_id": ObjectId(tool_id)})
        if not existing:
            return {"success": False, "message": "Tool not found.", "status_code": 404}

        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if request.name is not None:
            if await check_tool_name_exists(existing["team_id"], request.name, exclude_tool_id=tool_id):
                return {"success": False, "message": "A tool with this name already exists for this team."}
            updates["name"] = request.name

        if request.display_name is not None:
            updates["display_name"] = request.display_name.strip()

        if request.description is not None:
            updates["description"] = request.description.strip()
        if request.api_url is not None:
            updates["api_url"] = request.api_url
        if request.http_method is not None:
            updates["http_method"] = request.http_method
        if request.parameters is not None:
            updates["parameters"] = _build_parameters_schema(request.parameters)
        if request.is_active is not None:
            updates["is_active"] = request.is_active

        if request.auth is not None:
            merged_auth = _merge_auth_update(existing.get("auth") or {"type": "none"}, request.auth)
            if merged_auth is None:
                return {
                    "success": False,
                    "message": "Invalid auth configuration. Provide location, param_name, and token when using api_key auth.",
                }
            updates["auth"] = merged_auth

        if len(updates) == 1:
            return {"success": False, "message": "No valid fields provided to update."}

        try:
            await collection.update_one({"_id": ObjectId(tool_id)}, {"$set": updates})
        except DuplicateKeyError:
            return {"success": False, "message": "A tool with this name already exists for this team."}

        updated = await collection.find_one({"_id": ObjectId(tool_id)})
        logger.info(f"Updated tool_id={tool_id}")
        return {"success": True, "tool": _serialize_tool_document(updated)}

    except InvalidId:
        return {"success": False, "message": "Tool not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error updating tool_id={tool_id}: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while updating the tool."}


async def delete_tool(tool_id: str) -> dict[str, Any]:
    try:
        collection = get_collection(COLLECTION_NAME)
        result = await collection.delete_one({"_id": ObjectId(tool_id)})
        if result.deleted_count == 0:
            return {"success": False, "message": "Tool not found.", "status_code": 404}

        logger.info(f"Deleted tool_id={tool_id}")
        return {"success": True, "message": "Tool deleted successfully."}
    except InvalidId:
        return {"success": False, "message": "Tool not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error deleting tool_id={tool_id}: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while deleting the tool."}
