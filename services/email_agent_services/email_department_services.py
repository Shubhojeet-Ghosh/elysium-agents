from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

EMAIL_DEPARTMENTS_COLLECTION = "email-departments"


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _format_department(department: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "department_id": get_department_id_str(department),
        "team_id": department.get("team_id", ""),
        "department_name": department.get("department_name", ""),
        "department_description": department.get("department_description", ""),
        "created_at": _format_datetime(department.get("created_at")),
        "updated_at": _format_datetime(department.get("updated_at")),
    }


def get_department_id_str(department: Dict[str, Any]) -> str:
    """Return the department id string from a department document (_id)."""
    return str(department["_id"])


async def get_departments_by_ids(department_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple departments by MongoDB _id. Returns a map of id string -> document."""
    if not department_ids:
        return {}

    collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)
    object_ids = []

    for department_id in department_ids:
        try:
            object_ids.append(ObjectId(department_id.strip()))
        except InvalidId:
            continue

    if not object_ids:
        return {}

    departments: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})

    async for department in cursor:
        departments[get_department_id_str(department)] = department

    return departments


async def get_department_by_id(department_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a department by MongoDB _id."""
    collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)

    try:
        object_id = ObjectId(department_id.strip())
    except InvalidId:
        return None

    return await collection.find_one({"_id": object_id})


async def create_department(name: str, description: str, team_id: str) -> Dict[str, Any]:
    """Create a department in the email-departments collection. _id is the department id."""
    department_name = name.strip()
    department_description = description.strip()
    normalized_team_id = team_id.strip()

    try:
        collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)
        now = datetime.now(timezone.utc)

        document = {
            "team_id": normalized_team_id,
            "department_name": department_name,
            "department_description": department_description,
            "created_at": now,
            "updated_at": now,
        }

        result = await collection.insert_one(document)
        department_id = str(result.inserted_id)

        logger.info(
            f"Created department {department_id} for team {normalized_team_id}: {department_name}"
        )

        return {
            "success": True,
            "status_code": 201,
            "message": "Department created successfully.",
            "data": _format_department(
                {
                    "_id": result.inserted_id,
                    **document,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Failed to create department {department_name}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create department.",
        }


async def list_team_departments(team_id: str) -> Dict[str, Any]:
    """List all departments for a team."""
    normalized_team_id = team_id.strip()

    try:
        collection = get_collection(EMAIL_DEPARTMENTS_COLLECTION)
        cursor = collection.find({"team_id": normalized_team_id}).sort("department_name", 1)

        departments = []
        async for department in cursor:
            departments.append(_format_department(department))

        logger.info(f"Listed {len(departments)} departments for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Team departments fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(departments),
                "departments": departments,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to list departments for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team departments.",
        }
