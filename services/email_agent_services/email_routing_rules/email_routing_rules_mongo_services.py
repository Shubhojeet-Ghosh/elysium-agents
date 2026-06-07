from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from services.email_agent_services.email_routing_rules.email_routing_rules_constants import (
    EMAIL_ROUTING_RULES_COLLECTION,
)
from services.mongo_services import get_collection


def get_routing_rule_id_str(rule: Dict[str, Any]) -> str:
    return str(rule["_id"])


def serialize_routing_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    created_at = rule.get("created_at")
    updated_at = rule.get("updated_at")
    return {
        "routing_rule_id": get_routing_rule_id_str(rule),
        "team_id": rule.get("team_id", ""),
        "department_id": rule.get("department_id", ""),
        "rule_name": rule.get("rule_name", ""),
        "routing_prompt": rule.get("routing_prompt", ""),
        "priority": rule.get("priority", 100),
        "is_fallback": rule.get("is_fallback", False),
        "status": rule.get("status", "active"),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


async def get_routing_rules_by_ids(
    routing_rule_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple routing rules by MongoDB _id. Returns map of id string -> document."""
    if not routing_rule_ids:
        return {}

    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    object_ids = []

    for routing_rule_id in routing_rule_ids:
        try:
            object_ids.append(ObjectId(routing_rule_id.strip()))
        except InvalidId:
            continue

    if not object_ids:
        return {}

    rules: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})

    async for rule in cursor:
        rules[get_routing_rule_id_str(rule)] = rule

    return rules


async def get_routing_rule_by_id(routing_rule_id: str) -> Optional[Dict[str, Any]]:
    try:
        object_id = ObjectId(routing_rule_id.strip())
    except InvalidId:
        return None

    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    return await collection.find_one({"_id": object_id})


async def insert_routing_rule(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    result = await collection.insert_one(document)
    return serialize_routing_rule({**document, "_id": result.inserted_id})


async def list_team_routing_rules(
    team_id: str,
    *,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    query: Dict[str, Any] = {"team_id": team_id.strip()}
    if not include_inactive:
        query["status"] = "active"

    cursor = collection.find(query).sort([("priority", 1), ("created_at", 1)])
    rules: List[Dict[str, Any]] = []
    async for rule in cursor:
        rules.append(serialize_routing_rule(rule))
    return rules


async def update_routing_rule_by_id(routing_rule_id: str, updates: Dict[str, Any]) -> bool:
    try:
        object_id = ObjectId(routing_rule_id.strip())
    except InvalidId:
        return False

    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    result = await collection.update_one({"_id": object_id}, {"$set": updates})
    return result.matched_count > 0


async def delete_routing_rule_by_id(routing_rule_id: str) -> bool:
    try:
        object_id = ObjectId(routing_rule_id.strip())
    except InvalidId:
        return False

    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    result = await collection.delete_one({"_id": object_id})
    return result.deleted_count > 0


async def clear_team_fallback_flag(team_id: str, *, except_rule_id: str | None = None) -> None:
    collection = get_collection(EMAIL_ROUTING_RULES_COLLECTION)
    query: Dict[str, Any] = {"team_id": team_id.strip(), "is_fallback": True}
    if except_rule_id:
        try:
            query["_id"] = {"$ne": ObjectId(except_rule_id.strip())}
        except InvalidId:
            pass

    await collection.update_many(query, {"$set": {"is_fallback": False}})
