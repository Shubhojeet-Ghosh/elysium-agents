from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from services.email_agent_services.email_recipient_rules.email_recipient_rules_constants import (
    EMAIL_RECIPIENT_RULES_COLLECTION,
)
from services.mongo_services import get_collection


def get_recipient_rule_id_str(rule: Dict[str, Any]) -> str:
    return str(rule["_id"])


def serialize_recipient_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    created_at = rule.get("created_at")
    updated_at = rule.get("updated_at")
    return {
        "recipient_rule_id": get_recipient_rule_id_str(rule),
        "team_id": rule.get("team_id", ""),
        "rule_name": rule.get("rule_name", ""),
        "recipient_prompt": rule.get("recipient_prompt", ""),
        "cc_user_ids": rule.get("cc_user_ids", []),
        "bcc_user_ids": rule.get("bcc_user_ids", []),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
    }


async def get_recipient_rule_by_id(recipient_rule_id: str) -> Optional[Dict[str, Any]]:
    try:
        object_id = ObjectId(recipient_rule_id.strip())
    except InvalidId:
        return None

    collection = get_collection(EMAIL_RECIPIENT_RULES_COLLECTION)
    return await collection.find_one({"_id": object_id})


async def get_recipient_rules_by_ids(
    recipient_rule_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple recipient rules by MongoDB _id. Returns map of id string -> document."""
    if not recipient_rule_ids:
        return {}

    collection = get_collection(EMAIL_RECIPIENT_RULES_COLLECTION)
    object_ids = []

    for recipient_rule_id in recipient_rule_ids:
        try:
            object_ids.append(ObjectId(recipient_rule_id.strip()))
        except InvalidId:
            continue

    if not object_ids:
        return {}

    rules: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})

    async for rule in cursor:
        rules[get_recipient_rule_id_str(rule)] = rule

    return rules


async def insert_recipient_rule(document: Dict[str, Any]) -> Dict[str, Any]:
    collection = get_collection(EMAIL_RECIPIENT_RULES_COLLECTION)
    result = await collection.insert_one(document)
    return serialize_recipient_rule({**document, "_id": result.inserted_id})


async def list_team_recipient_rules(team_id: str) -> List[Dict[str, Any]]:
    collection = get_collection(EMAIL_RECIPIENT_RULES_COLLECTION)
    cursor = collection.find({"team_id": team_id.strip()}).sort("created_at", 1)
    rules: List[Dict[str, Any]] = []
    async for rule in cursor:
        rules.append(serialize_recipient_rule(rule))
    return rules


async def update_recipient_rule_by_id(recipient_rule_id: str, updates: Dict[str, Any]) -> bool:
    try:
        object_id = ObjectId(recipient_rule_id.strip())
    except InvalidId:
        return False

    collection = get_collection(EMAIL_RECIPIENT_RULES_COLLECTION)
    result = await collection.update_one({"_id": object_id}, {"$set": updates})
    return result.matched_count > 0
