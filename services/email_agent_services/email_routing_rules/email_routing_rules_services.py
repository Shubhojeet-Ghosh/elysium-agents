from datetime import datetime, timezone
from typing import Any, Dict

from logging_config import get_logger
from services.email_agent_services.email_department_services import get_department_by_id
from services.email_agent_services.email_routing_rules.email_routing_rules_constants import (
    ALLOWED_RULE_STATUSES,
    DEFAULT_RULE_PRIORITY,
)
from services.email_agent_services.email_routing_rules.email_routing_rules_mongo_services import (
    clear_team_fallback_flag,
    delete_routing_rule_by_id,
    get_routing_rule_by_id,
    insert_routing_rule,
    list_team_routing_rules,
    serialize_routing_rule,
    update_routing_rule_by_id,
)

logger = get_logger()


async def _validate_department_for_team(department_id: str, team_id: str) -> Dict[str, Any] | None:
    department = await get_department_by_id(department_id)
    if not department:
        return {
            "success": False,
            "status_code": 400,
            "message": "Invalid department_id. Department does not exist.",
        }
    if department.get("team_id") != team_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "Department does not belong to this team.",
        }
    return None


async def create_email_routing_rule(
    team_id: str,
    department_id: str,
    rule_name: str,
    routing_prompt: str,
    priority: int = DEFAULT_RULE_PRIORITY,
    is_fallback: bool = False,
) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()
    normalized_department_id = department_id.strip()
    normalized_rule_name = rule_name.strip()
    normalized_routing_prompt = routing_prompt.strip()

    validation_error = await _validate_department_for_team(
        normalized_department_id, normalized_team_id
    )
    if validation_error:
        return validation_error

    try:
        if is_fallback:
            await clear_team_fallback_flag(normalized_team_id)

        now = datetime.now(timezone.utc)
        document = {
            "team_id": normalized_team_id,
            "department_id": normalized_department_id,
            "rule_name": normalized_rule_name,
            "routing_prompt": normalized_routing_prompt,
            "priority": priority,
            "is_fallback": is_fallback,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }

        rule_data = await insert_routing_rule(document)

        logger.info(
            f"Created routing rule {rule_data['routing_rule_id']} for team {normalized_team_id} "
            f"→ department {normalized_department_id}"
        )

        return {
            "success": True,
            "status_code": 201,
            "message": "Routing rule created successfully.",
            "data": rule_data,
        }

    except Exception as e:
        logger.error(
            f"Failed to create routing rule for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create routing rule.",
        }


async def update_email_routing_rule(
    routing_rule_id: str,
    team_id: str,
    department_id: str,
    rule_name: str,
    routing_prompt: str,
    priority: int = DEFAULT_RULE_PRIORITY,
    is_fallback: bool = False,
    status: str = "active",
) -> Dict[str, Any]:
    normalized_rule_id = routing_rule_id.strip()
    normalized_team_id = team_id.strip()
    normalized_department_id = department_id.strip()
    normalized_rule_name = rule_name.strip()
    normalized_routing_prompt = routing_prompt.strip()
    normalized_status = status.strip().lower()

    if normalized_status not in ALLOWED_RULE_STATUSES:
        return {
            "success": False,
            "status_code": 400,
            "message": "status must be active or inactive.",
        }

    try:
        existing = await get_routing_rule_by_id(normalized_rule_id)
        if not existing:
            return {
                "success": False,
                "status_code": 404,
                "message": "Routing rule not found.",
            }

        if existing.get("team_id") != normalized_team_id:
            return {
                "success": False,
                "status_code": 403,
                "message": "Routing rule does not belong to this team.",
            }

        validation_error = await _validate_department_for_team(
            normalized_department_id, normalized_team_id
        )
        if validation_error:
            return validation_error

        if is_fallback:
            await clear_team_fallback_flag(
                normalized_team_id,
                except_rule_id=normalized_rule_id,
            )

        now = datetime.now(timezone.utc)
        updates = {
            "department_id": normalized_department_id,
            "rule_name": normalized_rule_name,
            "routing_prompt": normalized_routing_prompt,
            "priority": priority,
            "is_fallback": is_fallback,
            "status": normalized_status,
            "updated_at": now,
        }

        updated = await update_routing_rule_by_id(normalized_rule_id, updates)
        if not updated:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to update routing rule.",
            }

        updated_rule = await get_routing_rule_by_id(normalized_rule_id)

        logger.info(f"Updated routing rule {normalized_rule_id} for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Routing rule updated successfully.",
            "data": serialize_routing_rule(updated_rule),
        }

    except Exception as e:
        logger.error(f"Failed to update routing rule {normalized_rule_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to update routing rule.",
        }


async def list_team_email_routing_rules(
    team_id: str,
    *,
    include_inactive: bool = False,
) -> Dict[str, Any]:
    normalized_team_id = team_id.strip()

    try:
        rules = await list_team_routing_rules(
            normalized_team_id,
            include_inactive=include_inactive,
        )

        return {
            "success": True,
            "status_code": 200,
            "message": "Team routing rules fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(rules),
                "rules": rules,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to list routing rules for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team routing rules.",
        }


async def delete_email_routing_rule(routing_rule_id: str) -> Dict[str, Any]:
    normalized_rule_id = routing_rule_id.strip()

    try:
        existing = await get_routing_rule_by_id(normalized_rule_id)
        if not existing:
            return {
                "success": False,
                "status_code": 404,
                "message": "Routing rule not found.",
            }

        deleted = await delete_routing_rule_by_id(normalized_rule_id)
        if not deleted:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to delete routing rule.",
            }

        logger.info(f"Deleted routing rule {normalized_rule_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Routing rule deleted successfully.",
            "data": {
                "routing_rule_id": normalized_rule_id,
                "team_id": existing.get("team_id", ""),
                "rule_name": existing.get("rule_name", ""),
            },
        }

    except Exception as e:
        logger.error(f"Failed to delete routing rule {normalized_rule_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to delete routing rule.",
        }
