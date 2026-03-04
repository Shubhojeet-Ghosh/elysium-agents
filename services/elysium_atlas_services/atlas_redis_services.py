import json
import datetime
from services.redis_services import get_redis_client
from logging_config import get_logger

logger = get_logger()

def get_or_cache_agent_data(agent_id):
    """
    Get agent data from Redis cache, or fetch from MongoDB and cache for 24 hours.

    The data is stored under key: agent_{agent_id}_data
    Value: {"agent_name": ..., "owner_user_id": ..., "team_id": ...}

    Args:
        agent_id (str): The agent ID

    Returns:
        dict | None: Agent data if found/cached, None if not found or error
    """
    try:
        client = get_redis_client()
        key = f"agent_{agent_id}_data"
        cached = client.get(key)
        if cached:
            logger.info(f"Cache hit for agent data: {agent_id}")
            return json.loads(cached)

        # Not in cache — fetch from MongoDB
        import asyncio
        from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
        agent = asyncio.get_event_loop().run_until_complete(get_agent_by_id(agent_id))
        if not agent:
            logger.warning(f"Agent not found in DB for agent_id: {agent_id}")
            return None

        agent_data = {
            "agent_name": agent.get("agent_name"),
            "owner_user_id": agent.get("owner_user_id"),
            "team_id": agent.get("team_id")
        }
        client.set(key, json.dumps(agent_data), ex=86400)  # 24 hours
        logger.info(f"Cached agent data for agent_id: {agent_id}")
        return agent_data

    except Exception as e:
        logger.error(f"Error getting/caching agent data for agent_id {agent_id}: {e}")
        return None

async def get_or_cache_agent_data_async(agent_id):
    """
    Async version: Get agent data from Redis cache, or fetch from MongoDB and cache for 24 hours.

    The data is stored under key: agent_{agent_id}_data
    Value: {"agent_name": ..., "owner_user_id": ..., "team_id": ...}

    Args:
        agent_id (str): The agent ID

    Returns:
        dict | None: Agent data if found/cached, None if not found or error
    """
    try:
        client = get_redis_client()
        key = f"agent_{agent_id}_data"
        cached = client.get(key)
        if cached:
            logger.info(f"Cache hit for agent data: {agent_id}")
            return json.loads(cached)

        # Not in cache — fetch from MongoDB
        from services.elysium_atlas_services.agent_db_operations import get_agent_by_id
        agent = await get_agent_by_id(agent_id)
        if not agent:
            logger.warning(f"Agent not found in DB for agent_id: {agent_id}")
            return None

        agent_data = {
            "agent_name": agent.get("agent_name"),
            "owner_user_id": agent.get("owner_user_id"),
            "team_id": agent.get("team_id")
        }
        client.set(key, json.dumps(agent_data), ex=86400)  # 24 hours
        logger.info(f"Cached agent data for agent_id: {agent_id}")
        return agent_data

    except Exception as e:
        logger.error(f"Error getting/caching agent data for agent_id {agent_id}: {e}")
        return None

def add_visitor_to_agent(agent_id, chat_session_id, sid=None, geo_data=None, visitor_at=None, alias_name=None):
    """
    Add or update a visitor in the agent's visitors hash in Redis.
    
    The data is stored in a Redis hash with key: atlas_{agent_id}_visitors
    Each field is a sid (socket ID), and the value is a JSON string of visitor data.
    
    Example structure in Redis:
    Key: atlas_123_visitors
    Fields:
        "socket123": '{"agent_id": "123", "chat_session_id": "session1", "created_at": "2023-01-01T00:00:00+00:00", "last_message_at": null, "sid": "socket123", "alias_name": null}'
        "socket124": '{"agent_id": "123", "chat_session_id": "session2", "created_at": "2023-01-01T00:01:00+00:00", "last_message_at": null, "sid": "socket124", "alias_name": "User A"}'
    
    Args:
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        sid (str): Socket ID (cannot be None)
        geo_data (dict | None): Optional geo data (country_name, country_flag, district, ip, time_zone, etc.)
        alias_name (str | None): Optional alias name pre-fetched from atlas_chat_sessions
    
    Returns:
        bool: True if successful, None if error
    """
    try:
        if sid is None:
            logger.error("sid cannot be None")
            return None
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        now = datetime.datetime.now(datetime.timezone.utc)
        visitor_data = {
            "agent_id": agent_id,
            "chat_session_id": chat_session_id,
            "created_at": now.isoformat(),
            "last_message_at": None,
            "last_connected_at": now.isoformat(timespec="milliseconds"),
            "sid": sid,
            "alias_name": alias_name,
            "in_conversation_with": None,
            "geo_data": geo_data if isinstance(geo_data, dict) else None,
            "visitor_at": visitor_at if isinstance(visitor_at, str) else None
        }
        client.hset(key, sid, json.dumps(visitor_data))
        logger.info(f"Added visitor {chat_session_id} to agent {agent_id} visitors hash")
        return visitor_data
    except Exception as e:
        logger.error(f"Error adding visitor to agent: {e}")
        return None

def get_visitors_for_agent(agent_id, page=1, size=100):
    """
    Get a paginated list of visitors connected to the agent, sorted by last_connected_at descending (latest first).
    
    Args:
        agent_id (str): The agent ID
        page (int): Page number (1-based)
        size (int): Number of visitors per page (default: 100)
        
    Returns:
        dict: {
            'visitors': list of visitor dictionaries (sorted latest first),
            'total': total number of visitors,
            'page': current page,
            'size': page size,
            'has_next': bool indicating if there are more pages,
            'has_prev': bool indicating if there are previous pages
        }
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        visitor_list = []
        for sid, data in visitors.items():
            visitor_list.append(json.loads(data))
        
        # Sort by last_connected_at descending (latest first), fall back to created_at
        def sort_key(v):
            ts = v.get("last_connected_at") or v.get("created_at") or ""
            return ts
        visitor_list.sort(key=sort_key, reverse=True)

        total = len(visitor_list)
        start = (page - 1) * size
        end = start + size
        paginated_visitors = visitor_list[start:end]
        
        logger.info(f"Retrieved {len(paginated_visitors)} visitors for agent {agent_id} (page {page}, size {size}, total {total})")
        return {
            'visitors': paginated_visitors,
            'total': total,
            'page': page,
            'size': size,
            'has_next': end < total,
            'has_prev': page > 1
        }
    except Exception as e:
        logger.error(f"Error getting visitors for agent {agent_id}: {e}")
        return None

def remove_visitor_from_agent(agent_id, sid):
    """
    Remove a visitor from the agent's visitors hash in Redis.
    
    Args:
        agent_id (str): The agent ID
        sid (str): The socket ID to remove
        
    Returns:
        bool: True if successful (found or not), None if error
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        result = client.hdel(key, sid)
        if result:
            logger.info(f"Removed visitor with sid {sid} from agent {agent_id} visitors hash")
        else:
            logger.info(f"Visitor with sid {sid} was not found in agent {agent_id} visitors hash, but operation completed successfully")
        
        # Log current visitor count after removal
        count = get_visitor_count_for_agent(agent_id)
        if count is not None:
            logger.info(f"Current visitor count for agent {agent_id} after removal: {count}")
        else:
            logger.warning(f"Failed to retrieve visitor count for agent {agent_id} after removal")
        return True
    except Exception as e:
        logger.error(f"Error removing visitor from agent: {e}")
        return None

def get_visitor_count_for_agent(agent_id):
    """
    Get the total number of visitors for the agent.
    
    Args:
        agent_id (str): The agent ID
        
    Returns:
        int: Number of visitors
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        count = client.hlen(key)
        # logger.info(f"Visitor count for agent {agent_id}: {count}")
        return count
    except Exception as e:
        logger.error(f"Error getting visitor count for agent {agent_id}: {e}")
        return None

def add_team_member(team_id, user_id, agent_id, sid):
    """
    Add or update a team member in the team's members hash in Redis.

    The data is stored in a Redis hash with key: atlas_team_{team_id}_members
    Each field is a sid (socket ID), and the value is a JSON string of team member data.

    Example structure in Redis:
    Key: atlas_team_456_members
    Fields:
        "socket123": '{"team_id": "456", "user_id": "user1", "agent_id": "123", "connected_at": "2026-01-01T00:00:00+00:00", "sid": "socket123"}'

    Args:
        team_id (str): The team ID
        user_id (str): The user ID
        agent_id (str): The agent ID
        sid (str): Socket ID (cannot be None)

    Returns:
        bool: True if successful, None if error
    """
    try:
        if sid is None:
            logger.error("sid cannot be None")
            return None
        client = get_redis_client()
        key = f"atlas_team_{team_id}_members"
        now = datetime.datetime.now(datetime.timezone.utc)
        team_member_data = {
            "team_id": team_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "connected_at": now.isoformat(timespec="milliseconds"),
            "sid": sid
        }
        client.hset(key, sid, json.dumps(team_member_data))
        logger.info(f"Added team member {user_id} (sid: {sid}) to team {team_id} members hash")
        return True
    except Exception as e:
        logger.error(f"Error adding team member to team {team_id}: {e}")
        return None

def remove_team_member(team_id, sid):
    """
    Remove a team member from the team's members hash in Redis.

    Args:
        team_id (str): The team ID
        sid (str): The socket ID to remove

    Returns:
        bool: True if successful, None if error
    """
    try:
        client = get_redis_client()
        key = f"atlas_team_{team_id}_members"
        result = client.hdel(key, sid)
        if result:
            logger.info(f"Removed team member with sid {sid} from team {team_id} members hash")
        else:
            logger.info(f"Team member with sid {sid} was not found in team {team_id} members hash")
        return True
    except Exception as e:
        logger.error(f"Error removing team member from team {team_id}: {e}")
        return None

def remove_agent_member(agent_id, sid):
    """
    Remove a member from the agent's members hash in Redis.

    Args:
        agent_id (str): The agent ID
        sid (str): The socket ID to remove

    Returns:
        bool: True if successful, None if error
    """
    try:
        client = get_redis_client()
        key = f"agent_{agent_id}_members"
        result = client.hdel(key, sid)
        if result:
            logger.info(f"Removed member with sid {sid} from agent {agent_id} members hash")
        else:
            logger.info(f"Member with sid {sid} was not found in agent {agent_id} members hash")
        return True
    except Exception as e:
        logger.error(f"Error removing member from agent {agent_id}: {e}")
        return None

def add_agent_member(agent_id, team_id, user_id, sid):
    """
    Add or update a team member in the agent's members hash in Redis.

    The data is stored in a Redis hash with key: agent_{agent_id}_members
    Each field is a sid (socket ID), and the value is a JSON string of member data.

    Example structure in Redis:
    Key: agent_999_members
    Fields:
        "socket123": '{"agent_id": "agent_999", "team_id": "team_abc", "user_id": "user_001", "connected_at": "2026-01-01T00:00:00.000+00:00", "sid": "socket123"}'

    Args:
        agent_id (str): The agent ID
        team_id (str): The team ID
        user_id (str): The user ID
        sid (str): Socket ID (cannot be None)

    Returns:
        bool: True if successful, None if error
    """
    try:
        if sid is None:
            logger.error("sid cannot be None")
            return None
        client = get_redis_client()
        key = f"agent_{agent_id}_members"
        now = datetime.datetime.now(datetime.timezone.utc)
        agent_member_data = {
            "agent_id": agent_id,
            "team_id": team_id,
            "user_id": user_id,
            "connected_at": now.isoformat(timespec="milliseconds"),
            "sid": sid
        }
        client.hset(key, sid, json.dumps(agent_member_data))
        logger.info(f"Added member {user_id} (sid: {sid}) to agent {agent_id} members hash")
        return True
    except Exception as e:
        logger.error(f"Error adding member to agent {agent_id}: {e}")
        return None

def update_visitor_conversation_status(agent_id, chat_session_id, user_id):
    """
    Update in_conversation_with for a visitor identified by chat_session_id.

    Args:
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        user_id (str | None): The team member's user ID (or None to clear)

    Returns:
        str | None: The visitor's sid if updated, None otherwise
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        for sid, data in visitors.items():
            visitor = json.loads(data)
            if visitor.get("chat_session_id") == chat_session_id:
                visitor["in_conversation_with"] = user_id
                client.hset(key, sid, json.dumps(visitor))
                logger.info(f"Updated in_conversation_with for visitor {chat_session_id} in agent {agent_id} to {user_id}")
                return sid
        logger.warning(f"No visitor found for agent {agent_id} with chat_session_id {chat_session_id}")
        return None
    except Exception as e:
        logger.error(f"Error updating conversation status for agent {agent_id}, chat_session_id {chat_session_id}: {e}")
        return None

def get_visitor_sid_by_chat_session(agent_id, chat_session_id):
    """
    Get the socket ID (sid) for a visitor identified by agent_id and chat_session_id.

    Args:
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID

    Returns:
        str | None: The socket ID if found, None otherwise
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        for sid, data in visitors.items():
            visitor = json.loads(data)
            if visitor.get("chat_session_id") == chat_session_id:
                return sid
        logger.warning(f"No visitor found for agent {agent_id} with chat_session_id {chat_session_id}")
        return None
    except Exception as e:
        logger.error(f"Error getting visitor sid for agent {agent_id}, chat_session_id {chat_session_id}: {e}")
        return None

def get_agent_member_sids_by_user_id(agent_id, user_id):
    """
    Return all socket IDs (sids) for a team member identified by user_id
    in the agent's members hash (key: agent_{agent_id}_members).

    Args:
        agent_id (str): The agent ID
        user_id (str): The team member's user ID

    Returns:
        list[str]: List of matching socket IDs, or [] if none found
    """
    try:
        client = get_redis_client()
        key = f"agent_{agent_id}_members"
        members = client.hgetall(key)
        sids = []
        for sid, data in members.items():
            try:
                member = json.loads(data)
                if member.get("user_id") == user_id:
                    sids.append(sid if isinstance(sid, str) else sid.decode())
            except Exception:
                continue
        if sids:
            logger.info(f"Found {len(sids)} socket(s) for user_id {user_id} on agent {agent_id}")
        else:
            logger.warning(f"No sockets found for user_id {user_id} on agent {agent_id}")
        return sids
    except Exception as e:
        logger.error(f"Error getting agent member sids for agent {agent_id}, user_id {user_id}: {e}")
        return []


def get_agent_ids_for_user_in_team(team_id, user_id):
    """
    Scan the team members hash (atlas_team_{team_id}_members) and return all unique
    agent_ids associated with the given user_id. Useful when agent_id is not known
    at disconnect time.

    Args:
        team_id (str): The team ID
        user_id (str): The user ID

    Returns:
        list[str]: Unique agent_ids (non-null) found for this user in the team hash
    """
    try:
        client = get_redis_client()
        key = f"atlas_team_{team_id}_members"
        members = client.hgetall(key)
        agent_ids = set()
        for sid, data in members.items():
            try:
                member = json.loads(data)
                if member.get("user_id") == user_id and member.get("agent_id"):
                    agent_ids.add(member["agent_id"])
            except Exception:
                continue
        result = list(agent_ids)
        logger.info(f"Found {len(result)} agent_id(s) for user_id {user_id} in team {team_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Error getting agent_ids for user_id {user_id} in team {team_id}: {e}")
        return []


def remove_team_members_by_user_id(team_id, user_id):
    """
    Remove all team member entries for a given user_id from the team's members hash in Redis.

    Args:
        team_id (str): The team ID
        user_id (str): The user ID to remove

    Returns:
        list[str]: List of removed socket IDs
    """
    try:
        client = get_redis_client()
        key = f"atlas_team_{team_id}_members"
        members = client.hgetall(key)
        sids_to_remove = []
        for sid, data in members.items():
            try:
                member = json.loads(data)
                if member.get("user_id") == user_id:
                    sids_to_remove.append(sid if isinstance(sid, str) else sid.decode())
            except Exception:
                continue
        for sid in sids_to_remove:
            client.hdel(key, sid)
        logger.info(f"Removed {len(sids_to_remove)} socket(s) for user_id {user_id} from team {team_id} members hash")
        return sids_to_remove
    except Exception as e:
        logger.error(f"Error removing team members by user_id for team {team_id}, user_id {user_id}: {e}")
        return []


def remove_agent_members_by_user_id(agent_id, user_id):
    """
    Remove all agent member entries for a given user_id from the agent's members hash in Redis.

    Args:
        agent_id (str): The agent ID
        user_id (str): The user ID to remove

    Returns:
        list[str]: List of removed socket IDs
    """
    try:
        client = get_redis_client()
        key = f"agent_{agent_id}_members"
        members = client.hgetall(key)
        sids_to_remove = []
        for sid, data in members.items():
            try:
                member = json.loads(data)
                if member.get("user_id") == user_id:
                    sids_to_remove.append(sid if isinstance(sid, str) else sid.decode())
            except Exception:
                continue
        for sid in sids_to_remove:
            client.hdel(key, sid)
        logger.info(f"Removed {len(sids_to_remove)} socket(s) for user_id {user_id} from agent {agent_id} members hash")
        return sids_to_remove
    except Exception as e:
        logger.error(f"Error removing agent members by user_id for agent {agent_id}, user_id {user_id}: {e}")
        return []


def get_visitors_in_conversation_with(agent_id, user_id):
    """
    Get all visitors for an agent whose in_conversation_with field matches the given user_id.

    Args:
        agent_id (str): The agent ID
        user_id (str): The team member's user ID

    Returns:
        list[dict]: List of visitor data dicts
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        matched = []
        for sid, data in visitors.items():
            try:
                visitor = json.loads(data)
                if visitor.get("in_conversation_with") == user_id:
                    matched.append(visitor)
            except Exception:
                continue
        logger.info(f"Found {len(matched)} visitor(s) in conversation with user_id {user_id} for agent {agent_id}")
        return matched
    except Exception as e:
        logger.error(f"Error getting visitors in conversation with user_id {user_id} for agent {agent_id}: {e}")
        return []


def update_visitor_alias(agent_id, sid, alias_name):
    """
    Update the alias_name for a specific visitor by sid.
    
    Args:
        agent_id (str): The agent ID
        sid (str): The socket ID
        alias_name (str): The new alias name
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        data = client.hget(key, sid)
        if data:
            visitor_data = json.loads(data)
            visitor_data["alias_name"] = alias_name
            client.hset(key, sid, json.dumps(visitor_data))
            logger.info(f"Updated alias_name for visitor with sid {sid} in agent {agent_id} to {alias_name}")
        else:
            logger.warning(f"Visitor with sid {sid} not found for agent {agent_id}")
    except Exception as e:
        logger.error(f"Error updating visitor alias for agent {agent_id}, sid {sid}: {e}")
        return None


def update_visitor_alias_by_chat_session(agent_id, chat_session_id, alias_name):
    """
    Update the alias_name for a visitor identified by chat_session_id in the agent's
    visitors hash. Scans all entries and updates the matching one.

    Args:
        agent_id (str): The agent ID
        chat_session_id (str): The chat session ID
        alias_name (str): The new alias name

    Returns:
        str | None: The visitor's sid if updated, None if not found or error
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        for sid, data in visitors.items():
            visitor = json.loads(data)
            if visitor.get("chat_session_id") == chat_session_id:
                visitor["alias_name"] = alias_name
                client.hset(key, sid, json.dumps(visitor))
                logger.info(f"Updated alias_name for visitor {chat_session_id} in agent {agent_id} to {alias_name}")
                return sid if isinstance(sid, str) else sid.decode()
        logger.warning(f"No visitor found for agent {agent_id} with chat_session_id {chat_session_id} to update alias")
        return None
    except Exception as e:
        logger.error(f"Error updating visitor alias by chat_session for agent {agent_id}, chat_session_id {chat_session_id}: {e}")
        return None