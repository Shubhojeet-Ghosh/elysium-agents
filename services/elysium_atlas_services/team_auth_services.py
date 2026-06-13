from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId

from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

TeamRole = Literal["owner", "admin", "member"]

OWNER_ROLE: TeamRole = "owner"
ADMIN_ROLE: TeamRole = "admin"
MEMBER_ROLE: TeamRole = "member"

ALL_TEAM_ROLES = frozenset({OWNER_ROLE, ADMIN_ROLE, MEMBER_ROLE})
TEAM_ADMIN_ROLES = frozenset({OWNER_ROLE, ADMIN_ROLE})


async def get_user_role_for_team(user_id: str, team_id: str) -> str | None:
    """
    Resolve the user's live role for a team from MongoDB.

    Owner is stored on atlas_teams.owner_user_id (not in atlas_team_members).
    Invited members are stored in atlas_team_members with role admin | member.

    Returns:
        "owner", "admin", "member", or None if the user is not on the team.
    """
    uid, tid = str(user_id), str(team_id)

    try:
        teams_collection = get_collection("atlas_teams")
        try:
            team_object_id = ObjectId(tid)
        except InvalidId:
            logger.warning(f"Invalid team_id format: {tid}")
            return None

        team = await teams_collection.find_one(
            {
                "_id": team_object_id,
                "owner_user_id": uid,
                "is_active": True,
                "status": "active",
            },
            {"_id": 1},
        )
        if team:
            return OWNER_ROLE

        members_collection = get_collection("atlas_team_members")
        membership = await members_collection.find_one(
            {
                "team_id": tid,
                "user_id": uid,
                "status": "active",
            },
            {"role": 1},
        )
        if membership:
            role = membership.get("role")
            if role in ALL_TEAM_ROLES:
                return role
            logger.warning(
                f"Unexpected team member role '{role}' for user_id={uid}, team_id={tid}"
            )
            return None

        return None

    except Exception as e:
        logger.error(
            f"Error resolving team role for user_id={uid}, team_id={tid}: {e}",
            exc_info=True,
        )
        return None


async def is_user_member_of_team(user_id: str, team_id: str) -> bool:
    """Return True if user_id is an active owner or member of team_id."""
    return await get_user_role_for_team(user_id, team_id) is not None


async def user_has_team_role(
    user_id: str,
    team_id: str,
    allowed_roles: frozenset[str],
) -> bool:
    """Return True if the user's live role for team_id is in allowed_roles."""
    role = await get_user_role_for_team(user_id, team_id)
    return role is not None and role in allowed_roles


async def get_agent_team_id(agent_id: str) -> str | None:
    """Return team_id for an agent, or None if the agent is missing or has no team."""
    try:
        collection = get_collection("atlas_agents")
        agent_object_id = ObjectId(agent_id)
        doc = await collection.find_one(
            {"_id": agent_object_id},
            {"team_id": 1, "_id": 0},
        )
        if not doc:
            logger.warning(f"No agent found for agent_id={agent_id} when fetching team_id")
            return None

        team_id = doc.get("team_id")
        if not team_id:
            logger.warning(f"Agent {agent_id} has no team_id")
            return None

        return str(team_id)

    except InvalidId:
        logger.warning(f"Invalid agent_id format: {agent_id}")
        return None
    except Exception as e:
        logger.error(f"Error fetching team_id for agent_id={agent_id}: {e}", exc_info=True)
        return None


async def is_user_member_of_agent_team(user_id: str, agent_id: str) -> bool:
    """Return True if user_id belongs to the team that owns the given agent."""
    team_id = await get_agent_team_id(agent_id)
    if not team_id:
        return False
    return await is_user_member_of_team(user_id, team_id)


async def user_has_agent_team_role(
    user_id: str,
    agent_id: str,
    allowed_roles: frozenset[str],
) -> bool:
    """Return True if user's live role on the agent's team is in allowed_roles."""
    team_id = await get_agent_team_id(agent_id)
    if not team_id:
        return False
    return await user_has_team_role(user_id, team_id, allowed_roles)


async def can_user_read_agent(user_id: str, agent_id: str) -> bool:
    """Return True if user_id may view the agent (any active team member)."""
    return await is_user_member_of_agent_team(user_id, agent_id)


async def can_user_modify_agent(user_id: str, agent_id: str) -> bool:
    """Return True if user_id may create/update/delete agent resources (owner or admin)."""
    return await user_has_agent_team_role(user_id, agent_id, TEAM_ADMIN_ROLES)


async def can_user_modify_team_agents(user_id: str, team_id: str) -> bool:
    """Return True if user_id may create agents for the team (owner or admin)."""
    return await user_has_team_role(user_id, team_id, TEAM_ADMIN_ROLES)


def parse_session_team_context(user_data: dict | None) -> tuple[str, str] | None:
    """
    Extract user_id and team_id from a decoded session JWT payload.

    Returns:
        (user_id, team_id) when both are present, else None.
    """
    if not user_data or user_data.get("success") is False:
        return None

    user_id = user_data.get("user_id")
    team_id = user_data.get("team_id")
    if not user_id or not team_id:
        return None

    return str(user_id), str(team_id)
