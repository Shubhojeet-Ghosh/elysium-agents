from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from middlewares.jwt_middleware import authorize_user
from controllers.elysium_atlas_controller_files.atlas_team_member_controllers import get_team_member_chat_sessions_controller

atlas_team_members_router = APIRouter(prefix="/atlas-team-members", tags=["Atlas Team Members"])


class TeamMemberChatSessionsRequest(BaseModel):
    agent_id: Optional[str] = None
    page: int = 1
    limit: int = 20


@atlas_team_members_router.post("/team-member-chat-sessions")
async def get_team_member_chat_sessions(
    body: TeamMemberChatSessionsRequest,
    user: dict = Depends(authorize_user),
):
    """
    Get paginated chat sessions the authenticated team member participated in.

    Request body:
        agent_id  (optional) – filter to a specific agent
        page      (default: 1)
        limit     (default: 20)

    Returns sessions sorted by last_message_at descending.
    """
    return await get_team_member_chat_sessions_controller(
        userData=user,
        agent_id=body.agent_id,
        page=body.page,
        limit=body.limit,
    )
