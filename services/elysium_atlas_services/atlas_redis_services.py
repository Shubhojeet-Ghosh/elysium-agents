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

def add_visitor_to_agent(agent_id, chat_session_id, sid=None):
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
            "alias_name": None
        }
        client.hset(key, sid, json.dumps(visitor_data))
        logger.info(f"Added visitor {chat_session_id} to agent {agent_id} visitors hash")
        return True
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

def update_visitor_alias(agent_id, sid, alias_name):
    """
    Update the alias_name for a specific visitor.
    
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