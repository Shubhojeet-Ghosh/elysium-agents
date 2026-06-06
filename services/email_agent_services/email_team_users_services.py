from typing import Any, Dict

from logging_config import get_logger
from services.email_agent_services.email_department_services import get_departments_by_ids
from services.email_agent_services.email_user_auth_services import (
    EMAIL_USERS_COLLECTION,
    _format_datetime,
    get_user_id_str,
)
from services.mongo_services import get_collection

logger = get_logger()


async def list_team_users(team_id: str) -> Dict[str, Any]:
    """List all users for a team with department name and description."""
    normalized_team_id = team_id.strip()

    try:
        users_collection = get_collection(EMAIL_USERS_COLLECTION)
        cursor = users_collection.find({"team_id": normalized_team_id})

        users = []
        department_ids = set()

        async for user in cursor:
            department_id = user.get("department_id", "")
            if department_id:
                department_ids.add(department_id)
            users.append(user)

        departments_by_id = await get_departments_by_ids(list(department_ids))

        team_users = []
        for user in users:
            department_id = user.get("department_id", "")
            department = departments_by_id.get(department_id)

            team_users.append({
                "user_id": get_user_id_str(user),
                "name": user.get("name", ""),
                "email": user.get("email", ""),
                "team_id": user.get("team_id", ""),
                "department_id": department_id,
                "department_name": department.get("department_name", "") if department else "",
                "department_description": department.get("department_description", "") if department else "",
                "created_at": _format_datetime(user.get("created_at")),
                "updated_at": _format_datetime(user.get("updated_at")),
            })

        logger.info(f"Listed {len(team_users)} users for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Team users fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(team_users),
                "users": team_users,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list users for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team users.",
        }
