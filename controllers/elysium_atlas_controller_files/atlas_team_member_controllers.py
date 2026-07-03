from typing import Dict, Any
from fastapi.responses import JSONResponse

from logging_config import get_logger
from services.elysium_atlas_services.atlas_chat_session_services import (
    get_paginated_team_member_chat_sessions,
    search_paginated_team_member_chat_sessions,
)

logger = get_logger()


def _unauthorized_response(userData: Dict[str, Any] | None) -> JSONResponse | None:
    if not userData or userData.get("success") is False:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": userData.get("message", "Unauthorized") if userData else "Unauthorized"},
        )
    user_id = userData.get("user_id")
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "user_id not found in token"},
        )
    return None


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
        Each session in data includes:
            has_unread_messages          – true if visitor messages lack read_at
            unread_visitor_message_count – count of unread visitor (role=user) messages
            last_message                 – most recent message in the conversation
    """
    try:
        auth_error = _unauthorized_response(userData)
        if auth_error:
            return auth_error

        user_id = userData.get("user_id")
        result = await get_paginated_team_member_chat_sessions(
            user_id,
            agent_id=agent_id,
            page=page,
            limit=limit,
        )
        if result is None:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Failed to fetch chat sessions."},
            )

        logger.info(
            f"Fetched {len(result['data'])} chat session(s) for user_id={user_id} "
            f"agent_id={agent_id} page={result['page']} limit={result['limit']} total={result['total']}"
        )

        return {
            "success": True,
            **result,
        }

    except Exception as e:
        logger.error(f"Error in get_team_member_chat_sessions_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error"},
        )


async def search_team_member_chat_sessions_controller(
    userData: Dict[str, Any],
    query: str,
    agent_id: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Search paginated atlas_chat_sessions the authenticated team member participated in.

    Matches case-insensitive substrings on chat_session_id or alias_name.
    """
    try:
        auth_error = _unauthorized_response(userData)
        if auth_error:
            return auth_error

        user_id = userData.get("user_id")
        result, validation_error = await search_paginated_team_member_chat_sessions(
            user_id,
            query,
            agent_id=agent_id,
            page=page,
            limit=limit,
        )

        if validation_error:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": validation_error},
            )

        if result is None:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Failed to search chat sessions."},
            )

        return {
            "success": True,
            **result,
        }

    except Exception as e:
        logger.error(f"Error in search_team_member_chat_sessions_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal server error"},
        )
