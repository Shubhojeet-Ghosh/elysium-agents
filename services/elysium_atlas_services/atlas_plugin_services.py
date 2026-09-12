from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from config.atlas_plugin_config import MAX_AGENT_PLUGIN_IDS
from config.atlas_plugin_models import (
    CreatePluginRequest,
    SetPluginSecretsRequest,
    UpdatePluginRequest,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_plugin_parser import PluginParseError, parse_plugin_source
from services.elysium_atlas_services.atlas_plugin_secrets import encrypt_plugin_secret
from services.mongo_services import get_collection

logger = get_logger()

COLLECTION_NAME = "atlas_plugins"
TOOLS_COLLECTION_NAME = "atlas_tools"


def _duplicate_key_message(exc: DuplicateKeyError) -> str:
    details = exc.details or {}
    key_pattern = details.get("keyPattern") or {}
    if "display_name" in key_pattern:
        return "A plugin with this display name already exists for this team."
    return "A plugin with this name already exists for this team."


def _serialize_plugin_document(document: dict[str, Any]) -> dict[str, Any]:
    secret_names = list(document.get("secret_names") or [])
    stored_secrets = document.get("secrets") or {}
    secrets_configured = {name: bool(stored_secrets.get(name)) for name in secret_names}

    created_at = document.get("created_at")
    updated_at = document.get("updated_at")

    return {
        "plugin_id": str(document["_id"]),
        "team_id": document.get("team_id"),
        "created_by_user_id": document.get("created_by_user_id"),
        "name": document.get("name"),
        "display_name": document.get("display_name"),
        "description": document.get("description"),
        "parameters": document.get("parameters") or {"type": "object", "properties": {}},
        "python_code": document.get("python_code") or "",
        "secret_names": secret_names,
        "secrets_configured": secrets_configured,
        "is_active": document.get("is_active", True),
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
    }


def _prune_secrets(existing_secrets: dict[str, str], secret_names: list[str]) -> dict[str, str]:
    return {name: existing_secrets[name] for name in secret_names if name in existing_secrets}


async def check_plugin_name_exists(
    team_id: str,
    name: str,
    exclude_plugin_id: str | None = None,
) -> bool:
    try:
        collection = get_collection(COLLECTION_NAME)
        query: dict[str, Any] = {"team_id": team_id, "name": name}
        if exclude_plugin_id:
            query["_id"] = {"$ne": ObjectId(exclude_plugin_id)}
        existing = await collection.find_one(query, {"_id": 1})
        return existing is not None
    except InvalidId:
        return False
    except Exception as e:
        logger.error(
            f"Error checking plugin name '{name}' for team_id={team_id}: {e}",
            exc_info=True,
        )
        return False


async def check_plugin_display_name_exists(
    team_id: str,
    display_name: str,
    exclude_plugin_id: str | None = None,
) -> bool:
    try:
        collection = get_collection(COLLECTION_NAME)
        query: dict[str, Any] = {"team_id": team_id, "display_name": display_name}
        if exclude_plugin_id:
            query["_id"] = {"$ne": ObjectId(exclude_plugin_id)}
        existing = await collection.find_one(query, {"_id": 1})
        return existing is not None
    except InvalidId:
        return False
    except Exception as e:
        logger.error(
            f"Error checking plugin display_name '{display_name}' for team_id={team_id}: {e}",
            exc_info=True,
        )
        return False


async def check_tool_name_taken(team_id: str, name: str) -> bool:
    try:
        collection = get_collection(TOOLS_COLLECTION_NAME)
        existing = await collection.find_one({"team_id": team_id, "name": name}, {"_id": 1})
        return existing is not None
    except Exception as e:
        logger.error(
            f"Error checking tool name '{name}' for plugin uniqueness team_id={team_id}: {e}",
            exc_info=True,
        )
        return False


async def validate_agent_plugin_ids(
    team_id: str,
    plugin_ids: Any,
    *,
    max_count: int = MAX_AGENT_PLUGIN_IDS,
) -> tuple[list[str] | None, str | None]:
    if not isinstance(plugin_ids, list):
        return None, "plugin_ids must be an array of plugin ID strings."

    if len(plugin_ids) > max_count:
        return None, f"plugin_ids cannot contain more than {max_count} items."

    normalized: list[str] = []
    seen: set[str] = set()
    object_ids: list[ObjectId] = []

    for raw_id in plugin_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            return None, "Each plugin_id must be a non-empty string."
        plugin_id = raw_id.strip()
        if plugin_id in seen:
            continue
        seen.add(plugin_id)
        try:
            object_ids.append(ObjectId(plugin_id))
        except InvalidId:
            return None, f"Invalid plugin_id: {plugin_id}"
        normalized.append(plugin_id)

    if not object_ids:
        return [], None

    collection = get_collection(COLLECTION_NAME)
    cursor = collection.find(
        {"_id": {"$in": object_ids}, "team_id": team_id},
        {"_id": 1},
    )
    documents = await cursor.to_list(length=len(object_ids))
    found_ids = {str(doc["_id"]) for doc in documents}
    missing = [plugin_id for plugin_id in normalized if plugin_id not in found_ids]
    if missing:
        return None, "One or more plugin_ids are invalid or do not belong to this team."

    return normalized, None


async def validate_attached_function_names(
    team_id: str,
    tool_ids: list[str],
    plugin_ids: list[str],
) -> str | None:
    """Reject when an attached tool and plugin share the same LLM function name."""
    tool_names: set[str] = set()
    plugin_names: set[str] = set()

    if tool_ids:
        object_ids = [ObjectId(item) for item in tool_ids]
        cursor = get_collection(TOOLS_COLLECTION_NAME).find(
            {"_id": {"$in": object_ids}, "team_id": team_id},
            {"name": 1},
        )
        for document in await cursor.to_list(length=len(object_ids)):
            name = document.get("name")
            if name:
                tool_names.add(name)

    if plugin_ids:
        object_ids = [ObjectId(item) for item in plugin_ids]
        cursor = get_collection(COLLECTION_NAME).find(
            {"_id": {"$in": object_ids}, "team_id": team_id},
            {"name": 1},
        )
        for document in await cursor.to_list(length=len(object_ids)):
            name = document.get("name")
            if name:
                plugin_names.add(name)

    overlap = sorted(tool_names & plugin_names)
    if overlap:
        joined = ", ".join(overlap)
        return (
            "Attached tools and plugins cannot share the same function name: "
            f"{joined}."
        )
    return None


async def get_plugin_team_id(plugin_id: str) -> str | None:
    try:
        collection = get_collection(COLLECTION_NAME)
        document = await collection.find_one({"_id": ObjectId(plugin_id)}, {"team_id": 1})
        if not document:
            return None
        team_id = document.get("team_id")
        return str(team_id) if team_id else None
    except InvalidId:
        logger.warning(f"Invalid plugin_id format: {plugin_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching team_id for plugin_id={plugin_id}: {e}", exc_info=True)
        return None


async def get_plugin_document_by_id(plugin_id: str) -> dict[str, Any] | None:
    try:
        collection = get_collection(COLLECTION_NAME)
        return await collection.find_one({"_id": ObjectId(plugin_id)})
    except InvalidId:
        return None
    except Exception as e:
        logger.error(f"Error fetching plugin document plugin_id={plugin_id}: {e}", exc_info=True)
        return None


async def get_active_plugins_by_ids(plugin_ids: list[str]) -> list[dict[str, Any]]:
    if not plugin_ids:
        return []

    object_ids: list[ObjectId] = []
    for plugin_id in plugin_ids:
        try:
            object_ids.append(ObjectId(plugin_id))
        except InvalidId:
            logger.warning(f"Skipping invalid plugin_id during chat plugin load: {plugin_id}")

    if not object_ids:
        return []

    collection = get_collection(COLLECTION_NAME)
    cursor = collection.find({"_id": {"$in": object_ids}, "is_active": True})
    return await cursor.to_list(length=len(object_ids))


async def _guard_parsed_identity(
    team_id: str,
    parsed: dict[str, Any],
    exclude_plugin_id: str | None = None,
) -> str | None:
    if await check_plugin_name_exists(team_id, parsed["name"], exclude_plugin_id):
        return "A plugin with this name already exists for this team."
    if await check_plugin_display_name_exists(team_id, parsed["display_name"], exclude_plugin_id):
        return "A plugin with this display name already exists for this team."
    if await check_tool_name_taken(team_id, parsed["name"]):
        return "A tool with this name already exists for this team. PLUGIN_NAME must be unique across tools and plugins."
    return None


async def create_plugin(team_id: str, user_id: str, request: CreatePluginRequest) -> dict[str, Any]:
    try:
        parsed = parse_plugin_source(request.python_code)
    except PluginParseError as exc:
        return {"success": False, "message": str(exc), "status_code": 400}

    conflict = await _guard_parsed_identity(team_id, parsed)
    if conflict:
        return {"success": False, "message": conflict, "status_code": 409}

    current_time = datetime.now(timezone.utc)
    document = {
        "team_id": team_id,
        "created_by_user_id": user_id,
        "name": parsed["name"],
        "display_name": parsed["display_name"],
        "description": parsed["description"],
        "parameters": parsed["parameters"],
        "python_code": request.python_code,
        "secret_names": parsed["secret_names"],
        "secrets": {},
        "is_active": True,
        "created_at": current_time,
        "updated_at": current_time,
    }

    collection = get_collection(COLLECTION_NAME)
    try:
        result = await collection.insert_one(document)
    except DuplicateKeyError as exc:
        return {"success": False, "message": _duplicate_key_message(exc), "status_code": 409}

    document["_id"] = result.inserted_id
    logger.info(f"Created plugin_id={result.inserted_id} for team_id={team_id}")
    return {"success": True, "plugin": _serialize_plugin_document(document)}


async def list_plugins_for_team(
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
    plugins = [_serialize_plugin_document(doc) for doc in documents]
    total_pages = max(1, (total + limit - 1) // limit) if total else 0

    return {
        "success": True,
        "plugins": plugins,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total > 0,
    }


async def get_plugin_by_id(plugin_id: str) -> dict[str, Any] | None:
    document = await get_plugin_document_by_id(plugin_id)
    if not document:
        return None
    return _serialize_plugin_document(document)


async def update_plugin(plugin_id: str, request: UpdatePluginRequest) -> dict[str, Any]:
    try:
        collection = get_collection(COLLECTION_NAME)
        existing = await collection.find_one({"_id": ObjectId(plugin_id)})
        if not existing:
            return {"success": False, "message": "Plugin not found.", "status_code": 404}

        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}

        if request.python_code is not None:
            try:
                parsed = parse_plugin_source(request.python_code)
            except PluginParseError as exc:
                return {"success": False, "message": str(exc), "status_code": 400}

            conflict = await _guard_parsed_identity(
                existing["team_id"],
                parsed,
                exclude_plugin_id=plugin_id,
            )
            if conflict:
                return {"success": False, "message": conflict, "status_code": 409}

            updates["name"] = parsed["name"]
            updates["display_name"] = parsed["display_name"]
            updates["description"] = parsed["description"]
            updates["parameters"] = parsed["parameters"]
            updates["python_code"] = request.python_code
            updates["secret_names"] = parsed["secret_names"]
            updates["secrets"] = _prune_secrets(existing.get("secrets") or {}, parsed["secret_names"])

        if request.is_active is not None:
            updates["is_active"] = request.is_active

        try:
            await collection.update_one({"_id": ObjectId(plugin_id)}, {"$set": updates})
        except DuplicateKeyError as exc:
            return {"success": False, "message": _duplicate_key_message(exc), "status_code": 409}

        updated = await collection.find_one({"_id": ObjectId(plugin_id)})
        logger.info(f"Updated plugin_id={plugin_id}")
        return {"success": True, "plugin": _serialize_plugin_document(updated)}
    except InvalidId:
        return {"success": False, "message": "Plugin not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error updating plugin_id={plugin_id}: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while updating the plugin."}


async def delete_plugin(plugin_id: str) -> dict[str, Any]:
    try:
        collection = get_collection(COLLECTION_NAME)
        result = await collection.delete_one({"_id": ObjectId(plugin_id)})
        if result.deleted_count == 0:
            return {"success": False, "message": "Plugin not found.", "status_code": 404}

        logger.info(f"Deleted plugin_id={plugin_id}")
        return {"success": True, "message": "Plugin deleted successfully."}
    except InvalidId:
        return {"success": False, "message": "Plugin not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error deleting plugin_id={plugin_id}: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while deleting the plugin."}


async def set_plugin_secrets(plugin_id: str, request: SetPluginSecretsRequest) -> dict[str, Any]:
    try:
        collection = get_collection(COLLECTION_NAME)
        existing = await collection.find_one({"_id": ObjectId(plugin_id)})
        if not existing:
            return {"success": False, "message": "Plugin not found.", "status_code": 404}

        secret_names = set(existing.get("secret_names") or [])
        if not secret_names:
            return {
                "success": False,
                "message": "This plugin does not declare a PluginSecrets class.",
                "status_code": 400,
            }

        unknown = [key for key in request.secrets if key not in secret_names]
        if unknown:
            return {
                "success": False,
                "message": f"Unknown secret key(s): {', '.join(unknown)}.",
                "status_code": 400,
            }

        stored = dict(existing.get("secrets") or {})
        for key, value in request.secrets.items():
            if value is None or (isinstance(value, str) and value.strip() == ""):
                stored.pop(key, None)
                continue
            stored[key] = encrypt_plugin_secret(value)

        await collection.update_one(
            {"_id": ObjectId(plugin_id)},
            {
                "$set": {
                    "secrets": stored,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        updated = await collection.find_one({"_id": ObjectId(plugin_id)})
        logger.info(f"Updated secrets for plugin_id={plugin_id}")
        return {"success": True, "plugin": _serialize_plugin_document(updated)}
    except InvalidId:
        return {"success": False, "message": "Plugin not found.", "status_code": 404}
    except Exception as e:
        logger.error(f"Error setting secrets for plugin_id={plugin_id}: {e}", exc_info=True)
        return {"success": False, "message": "An error occurred while saving plugin secrets."}
