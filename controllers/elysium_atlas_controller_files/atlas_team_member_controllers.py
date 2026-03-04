import datetime
from typing import Dict, Any
from fastapi.responses import JSONResponse

from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()


async def get_team_member_chat_sessions_controller(
    userData: Dict[str, Any],
    agent_id: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Return paginated atlas_chat_sessions where the authenticated user appears
    in team_member_ids, sorted by last_message_at descending (most recent first).

    Args:
        userData:  Decoded JWT payload; must contain 'user_id'.
        agent_id:  Optional — scope results to a specific agent.
        page:      1-based page number (default: 1).
        limit:     Documents per page (default: 20).

    Returns:
        {
            "success": True,
            "data": [ ...chat session documents... ],
            "total": <int>,
            "page": <int>,
            "limit": <int>,
            "has_next": <bool>,
            "has_prev": <bool>
        }
    """
    try:
        if not userData or userData.get("success") == False:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": userData.get("message", "Unauthorized")}
            )

        user_id = userData.get("user_id")
        if not user_id:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "user_id not found in token"}
            )

        if page < 1:
            page = 1
        if limit < 1:
            limit = 1

        query: Dict[str, Any] = {"team_member_ids": user_id}
        if agent_id:
            query["agent_id"] = agent_id

        collection = get_collection("atlas_chat_sessions")

        total = await collection.count_documents(query)

        skip = (page - 1) * limit
        cursor = (
            collection.find(query)
            .sort("last_message_at", -1)
            .skip(skip)
            .limit(limit)
        )
        documents = await cursor.to_list(length=None)

        # Return only the required fields; missing keys default to None
        FIELDS = ("chat_session_id", "alias_name", "last_message_at", "visitor_online", "last_connected_at","geo_data")
        serialised = []
        for doc in documents:
            entry = {}
            for field in FIELDS:
                val = doc.get(field)
                # Serialise datetime objects to ISO string
                if isinstance(val, datetime.datetime):
                    val = val.isoformat()
                entry[field] = val
            serialised.append(entry)
        documents = serialised

        logger.info(
            f"Fetched {len(documents)} chat session(s) for user_id={user_id} "
            f"agent_id={agent_id} page={page} limit={limit} total={total}"
        )

        return {
            "success": True,
            "data": documents,
            "total": total,
            "page": page,
            "limit": limit,
            "has_next": (skip + limit) < total,
            "has_prev": page > 1,
        }

    except Exception as e:
        logger.error(f"Error in get_team_member_chat_sessions_controller: {e}")
        return {"success": False, "message": str(e)}
