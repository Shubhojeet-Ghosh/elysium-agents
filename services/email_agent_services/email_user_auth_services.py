from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from middlewares.jwt_middleware import generate_jwt_token
from services.email_agent_services.email_department_services import get_department_by_id
from services.email_agent_services.password_helpers import hash_password, verify_password
from services.mongo_services import get_collection

EMAIL_LOGIN_TOKEN_EXPIRY_HOURS = 30 * 24  # 30 days

logger = get_logger()

EMAIL_USERS_COLLECTION = "email-users"
EMAIL_USER_DEPARTMENT_MAPPING_COLLECTION = "email-user-department-mapping"
DEFAULT_EMAIL_USER_ROLE = "admin"


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_user_id_str(user: Dict[str, Any]) -> str:
    """Return the user id string from a user document (_id)."""
    return str(user["_id"])


async def _upsert_user_department_mapping(
    user_id: str,
    department_id: str,
    email: str,
    name: str,
    now: datetime,
) -> None:
    mapping_collection = get_collection(EMAIL_USER_DEPARTMENT_MAPPING_COLLECTION)
    await mapping_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "department_id": department_id,
                "email": email,
                "name": name,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )


def _build_user_response_data(
    user_id: str,
    name: str,
    email: str,
    team_id: str,
    department_id: str,
    department_name: str,
    role: str,
    created_at: Any,
    updated_at: datetime,
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "name": name,
        "email": email,
        "team_id": team_id,
        "department_id": department_id,
        "department_name": department_name,
        "role": role,
        "created_at": _format_datetime(created_at),
        "updated_at": updated_at.isoformat(),
    }


def _resolve_user_role(user: Dict[str, Any]) -> str:
    return user.get("role") or DEFAULT_EMAIL_USER_ROLE


async def create_email_user(
    name: str,
    email: str,
    password: str,
    team_id: str,
    department_id: str,
    role: str,
) -> Dict[str, Any]:
    """
    Register an email/password user in the email-users collection.

    Creates a new user when the email is new. If the email already exists,
    updates name, password, team_id, department_id, and mapping (prototype upsert).
    """
    normalized_email = _normalize_email(email)
    normalized_name = name.strip()
    normalized_team_id = team_id.strip()
    normalized_department_id = department_id.strip()
    normalized_role = role.strip()

    try:
        department = await get_department_by_id(normalized_department_id)
        if not department:
            return {
                "success": False,
                "status_code": 400,
                "message": "Invalid department_id. Department does not exist.",
            }

        department_name = department["department_name"]
        collection = get_collection(EMAIL_USERS_COLLECTION)
        now = datetime.now(timezone.utc)

        existing_user = await collection.find_one({"email": normalized_email})
        if existing_user:
            user_id = get_user_id_str(existing_user)
            await collection.update_one(
                {"email": normalized_email},
                {
                    "$set": {
                        "name": normalized_name,
                        "password_hash": hash_password(password),
                        "team_id": normalized_team_id,
                        "department_id": normalized_department_id,
                        "role": normalized_role,
                        "updated_at": now,
                    }
                },
            )
            await _upsert_user_department_mapping(
                user_id=user_id,
                department_id=normalized_department_id,
                email=normalized_email,
                name=normalized_name,
                now=now,
            )

            logger.info(f"Updated email user {user_id} for {normalized_email}")

            return {
                "success": True,
                "status_code": 200,
                "message": "User updated successfully.",
                "data": _build_user_response_data(
                    user_id=user_id,
                    name=normalized_name,
                    email=normalized_email,
                    team_id=normalized_team_id,
                    department_id=normalized_department_id,
                    department_name=department_name,
                    role=normalized_role,
                    created_at=existing_user.get("created_at"),
                    updated_at=now,
                ),
            }

        document = {
            "name": normalized_name,
            "email": normalized_email,
            "password_hash": hash_password(password),
            "team_id": normalized_team_id,
            "department_id": normalized_department_id,
            "role": normalized_role,
            "created_at": now,
            "updated_at": now,
        }

        result = await collection.insert_one(document)
        user_id = str(result.inserted_id)
        await _upsert_user_department_mapping(
            user_id=user_id,
            department_id=normalized_department_id,
            email=normalized_email,
            name=normalized_name,
            now=now,
        )

        logger.info(f"Created email user {user_id} for {normalized_email}")

        return {
            "success": True,
            "status_code": 201,
            "message": "User created successfully.",
            "data": _build_user_response_data(
                user_id=user_id,
                name=normalized_name,
                email=normalized_email,
                team_id=normalized_team_id,
                department_id=normalized_department_id,
                department_name=department_name,
                role=normalized_role,
                created_at=now,
                updated_at=now,
            ),
        }

    except Exception as e:
        logger.error(f"Failed to register email user for {normalized_email}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to register user.",
        }


async def get_email_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Fetch a user document by email."""
    collection = get_collection(EMAIL_USERS_COLLECTION)
    return await collection.find_one({"email": _normalize_email(email)})


async def get_email_users_by_ids(user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch multiple email-users documents by MongoDB _id. Returns map of id string -> document."""
    if not user_ids:
        return {}

    collection = get_collection(EMAIL_USERS_COLLECTION)
    object_ids = []
    for user_id in user_ids:
        try:
            object_ids.append(ObjectId(user_id.strip()))
        except InvalidId:
            continue

    if not object_ids:
        return {}

    users: Dict[str, Dict[str, Any]] = {}
    cursor = collection.find({"_id": {"$in": object_ids}})
    async for user in cursor:
        users[get_user_id_str(user)] = user

    return users


async def login_email_user(email: str, password: str) -> Dict[str, Any]:
    """
    Authenticate a user by email and password.

    Returns a JWT (30-day expiry) with user and department info on success.
    """
    normalized_email = _normalize_email(email)

    try:
        user = await get_email_user_by_email(normalized_email)
        if not user or not verify_password(password, user.get("password_hash", "")):
            return {
                "success": False,
                "status_code": 401,
                "message": "Invalid email or password.",
            }

        department = await get_department_by_id(user.get("department_id", ""))
        department_name = department.get("department_name", "") if department else ""
        department_id = user.get("department_id", "")

        user_id = get_user_id_str(user)
        role = _resolve_user_role(user)

        payload = {
            "user_id": user_id,
            "name": user.get("name", ""),
            "email": user["email"],
            "team_id": user.get("team_id", ""),
            "department_id": department_id,
            "department_name": department_name,
            "role": role,
        }
        token = generate_jwt_token(
            payload=payload,
            expires_in_hours=EMAIL_LOGIN_TOKEN_EXPIRY_HOURS,
        )

        logger.info(f"Email user {user_id} logged in successfully")

        return {
            "success": True,
            "status_code": 200,
            "message": "Login successful.",
            "data": {
                "token": token,
                "user_id": user_id,
                "name": user.get("name", ""),
                "email": user["email"],
                "team_id": user.get("team_id", ""),
                "department_id": department_id,
                "department_name": department_name,
                "role": role,
            },
        }

    except Exception as e:
        logger.error(f"Failed to login email user for {normalized_email}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to login.",
        }
