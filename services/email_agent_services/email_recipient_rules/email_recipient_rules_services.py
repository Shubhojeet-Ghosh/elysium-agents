from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.email_user_auth_services import (
    EMAIL_USERS_COLLECTION,
    get_user_id_str,
)
from services.email_agent_services.email_recipient_rules.email_recipient_rules_mongo_services import (
    get_recipient_rule_by_id,
    insert_recipient_rule,
    list_team_recipient_rules,
    serialize_recipient_rule,
    update_recipient_rule_by_id,
)
from services.mongo_services import get_collection

logger = get_logger()


def _normalize_user_ids(user_ids: List[str]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for user_id in user_ids:
        stripped = user_id.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalized.append(stripped)
    return normalized


async def _validate_user_ids_for_team(
    user_ids: List[str],
    team_id: str,
    *,
    field_label: str,
) -> Dict[str, Any] | None:
    if not user_ids:
        return None

    collection = get_collection(EMAIL_USERS_COLLECTION)
    object_ids = []
    for user_id in user_ids:
        try:
            object_ids.append(ObjectId(user_id))
        except InvalidId:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Invalid {field_label} user_id: {user_id}",
            }

    users_by_id: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})
    async for user in cursor:
        users_by_id[get_user_id_str(user)] = user

    for user_id in user_ids:
        user = users_by_id.get(user_id)
        if not user:
            return {
                "success": False,
                "status_code": 400,
                "message": f"Invalid {field_label} user_id: {user_id}. User does not exist.",
            }
        if user.get("team_id") != team_id:
            return {
                "success": False,
                "status_code": 400,
                "message": f"User {user_id} in {field_label} does not belong to this team.",
            }

    return None


async def create_email_recipient_rule(
    team_id: str,
    rule_name: str,
    recipient_prompt: str,
    cc_user_ids: List[str],
    bcc_user_ids: List[str],
) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()
    normalized_rule_name = rule_name.strip()
    normalized_prompt = recipient_prompt.strip()
    normalized_cc_user_ids = _normalize_user_ids(cc_user_ids)
    normalized_bcc_user_ids = _normalize_user_ids(bcc_user_ids)

    if not normalized_cc_user_ids and not normalized_bcc_user_ids:
        return {
            "success": False,
            "status_code": 400,
            "message": "At least one cc_user_id or bcc_user_id is required.",
        }

    if not normalized_rule_name:
        return {
            "success": False,
            "status_code": 400,
            "message": "rule_name cannot be empty.",
        }

    validation_error = await _validate_user_ids_for_team(
        normalized_cc_user_ids, normalized_team_id, field_label="cc"
    )
    if validation_error:
        return validation_error

    validation_error = await _validate_user_ids_for_team(
        normalized_bcc_user_ids, normalized_team_id, field_label="bcc"
    )
    if validation_error:
        return validation_error

    try:
        now = datetime.now(timezone.utc)
        document = {
            "team_id": normalized_team_id,
            "rule_name": normalized_rule_name,
            "recipient_prompt": normalized_prompt,
            "cc_user_ids": normalized_cc_user_ids,
            "bcc_user_ids": normalized_bcc_user_ids,
            "created_at": now,
            "updated_at": now,
        }

        rule_data = await insert_recipient_rule(document)

        logger.info(
            f"Created recipient rule {rule_data['recipient_rule_id']} for team {normalized_team_id}"
        )

        return {
            "success": True,
            "status_code": 201,
            "message": "Recipient rule created successfully.",
            "data": rule_data,
        }

    except Exception as e:
        logger.error(
            f"Failed to create recipient rule for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create recipient rule.",
        }


async def update_email_recipient_rule(
    recipient_rule_id: str,
    team_id: str,
    rule_name: str,
    recipient_prompt: str,
    cc_user_ids: List[str],
    bcc_user_ids: List[str],
) -> Dict[str, Any]:
    normalized_rule_id = recipient_rule_id.strip()
    normalized_team_id = team_id.strip()
    normalized_rule_name = rule_name.strip()
    normalized_prompt = recipient_prompt.strip()
    normalized_cc_user_ids = _normalize_user_ids(cc_user_ids)
    normalized_bcc_user_ids = _normalize_user_ids(bcc_user_ids)

    if not normalized_cc_user_ids and not normalized_bcc_user_ids:
        return {
            "success": False,
            "status_code": 400,
            "message": "At least one cc_user_id or bcc_user_id is required.",
        }

    if not normalized_rule_name:
        return {
            "success": False,
            "status_code": 400,
            "message": "rule_name cannot be empty.",
        }

    try:
        existing = await get_recipient_rule_by_id(normalized_rule_id)
        if not existing:
            return {
                "success": False,
                "status_code": 404,
                "message": "Recipient rule not found.",
            }

        if existing.get("team_id") != normalized_team_id:
            return {
                "success": False,
                "status_code": 403,
                "message": "Recipient rule does not belong to this team.",
            }

        validation_error = await _validate_user_ids_for_team(
            normalized_cc_user_ids, normalized_team_id, field_label="cc"
        )
        if validation_error:
            return validation_error

        validation_error = await _validate_user_ids_for_team(
            normalized_bcc_user_ids, normalized_team_id, field_label="bcc"
        )
        if validation_error:
            return validation_error

        now = datetime.now(timezone.utc)
        updates = {
            "rule_name": normalized_rule_name,
            "recipient_prompt": normalized_prompt,
            "cc_user_ids": normalized_cc_user_ids,
            "bcc_user_ids": normalized_bcc_user_ids,
            "updated_at": now,
        }

        updated = await update_recipient_rule_by_id(normalized_rule_id, updates)
        if not updated:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to update recipient rule.",
            }

        updated_rule = await get_recipient_rule_by_id(normalized_rule_id)

        logger.info(f"Updated recipient rule {normalized_rule_id} for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Recipient rule updated successfully.",
            "data": serialize_recipient_rule(updated_rule),
        }

    except Exception as e:
        logger.error(f"Failed to update recipient rule {normalized_rule_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to update recipient rule.",
        }


async def list_team_email_recipient_rules(team_id: str) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()

    try:
        rules = await list_team_recipient_rules(normalized_team_id)

        return {
            "success": True,
            "status_code": 200,
            "message": "Team recipient rules fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(rules),
                "rules": rules,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to list recipient rules for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team recipient rules.",
        }
