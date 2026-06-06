from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.email_agent_services.gmail_oauth_services import (
    GMAIL_ACCOUNTS_COLLECTION,
    get_gmail_account_by_id,
)
from services.mongo_services import get_collection

logger = get_logger()

EMAIL_AI_AGENTS_COLLECTION = "email-ai-agents"


def _format_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def get_email_ai_agent_id_str(agent: Dict[str, Any]) -> str:
    return str(agent["_id"])


async def get_email_ai_agent_by_id(agent_id: str) -> Dict[str, Any] | None:
    """Fetch an email AI agent by MongoDB _id."""
    try:
        object_id = ObjectId(agent_id.strip())
    except InvalidId:
        return None

    collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
    return await collection.find_one({"_id": object_id})


def _serialize_email_ai_agent(agent: Dict[str, Any], gmail_account: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        "agent_id": get_email_ai_agent_id_str(agent),
        "name": agent.get("name", ""),
        "gmail_account_id": agent.get("gmail_account_id", ""),
        "user_id": agent.get("user_id", ""),
        "team_id": agent.get("team_id", ""),
        "status": agent.get("status", "active"),
        "activated_at": _format_datetime(agent.get("activated_at")),
        "sync_status": agent.get("sync_status", "idle"),
        "last_synced_at": _format_datetime(agent.get("last_synced_at")) if agent.get("last_synced_at") else None,
        "last_sync_error": agent.get("last_sync_error"),
        "inbox_name": gmail_account.get("inbox_name", "") if gmail_account else "",
        "email_address": gmail_account.get("email_address", "") if gmail_account else "",
        "created_at": _format_datetime(agent.get("created_at")),
        "updated_at": _format_datetime(agent.get("updated_at")),
    }


async def create_email_ai_agent(
    user_id: str,
    team_id: str,
    name: str,
    gmail_account_id: str,
) -> Dict[str, Any]:
    """Create an email AI agent linked to a Gmail inbox."""
    normalized_name = name.strip()
    normalized_team_id = team_id.strip()
    normalized_gmail_account_id = gmail_account_id.strip()

    try:
        gmail_account = await get_gmail_account_by_id(normalized_gmail_account_id)
        if not gmail_account:
            return {
                "success": False,
                "status_code": 400,
                "message": "Invalid gmail_account_id. Gmail inbox does not exist.",
            }

        if gmail_account.get("status") == "revoked":
            return {
                "success": False,
                "status_code": 400,
                "message": "Gmail inbox is disconnected. Connect it before creating an agent.",
            }

        if gmail_account.get("team_id") != normalized_team_id:
            return {
                "success": False,
                "status_code": 400,
                "message": "Gmail inbox does not belong to your team.",
            }

        now = datetime.now(timezone.utc)
        collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)

        document = {
            "name": normalized_name,
            "gmail_account_id": normalized_gmail_account_id,
            "user_id": user_id,
            "team_id": normalized_team_id,
            "status": "active",
            "activated_at": now,
            "sync_status": "idle",
            "last_synced_at": None,
            "last_sync_error": None,
            "created_at": now,
            "updated_at": now,
        }

        result = await collection.insert_one(document)
        agent_id = str(result.inserted_id)

        logger.info(f"Created email AI agent {agent_id} for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 201,
            "message": "Email AI agent created successfully.",
            "data": _serialize_email_ai_agent(
                {**document, "_id": result.inserted_id},
                gmail_account,
            ),
        }

    except Exception as e:
        logger.error(f"Failed to create email AI agent for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create email AI agent.",
        }


async def list_team_email_ai_agents(team_id: str) -> Dict[str, Any]:
    """List all email AI agents for a team with linked inbox details."""
    normalized_team_id = team_id.strip()

    try:
        collection = get_collection(EMAIL_AI_AGENTS_COLLECTION)
        gmail_collection = get_collection(GMAIL_ACCOUNTS_COLLECTION)

        cursor = collection.find({"team_id": normalized_team_id})
        agents = []

        async for agent in cursor:
            gmail_account = None
            try:
                gmail_object_id = ObjectId(agent.get("gmail_account_id", ""))
                gmail_account = await gmail_collection.find_one({"_id": gmail_object_id})
            except InvalidId:
                gmail_account = None

            agents.append(_serialize_email_ai_agent(agent, gmail_account))

        logger.info(f"Listed {len(agents)} email AI agents for team {normalized_team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Email AI agents fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(agents),
                "agents": agents,
            },
        }

    except Exception as e:
        logger.error(f"Failed to list email AI agents for team {normalized_team_id}: {e}", exc_info=True)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch email AI agents.",
        }
