import json
import datetime
from services.redis_services import get_redis_client
from logging_config import get_logger

logger = get_logger()

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
            "sid": sid,
            "alias_name": None
        }
        client.hset(key, sid, json.dumps(visitor_data))
        logger.info(f"Added visitor {chat_session_id} to agent {agent_id} visitors hash")
        return True
    except Exception as e:
        logger.error(f"Error adding visitor to agent: {e}")
        return None

def get_visitors_for_agent(agent_id, page=1, size=10):
    """
    Get a paginated list of visitors connected to the agent.
    
    Args:
        agent_id (str): The agent ID
        page (int): Page number (1-based)
        size (int): Number of visitors per page
        
    Returns:
        dict: {
            'visitors': list of visitor dictionaries,
            'total': total number of visitors,
            'page': current page,
            'size': page size
        }
    """
    try:
        client = get_redis_client()
        key = f"atlas_{agent_id}_visitors"
        visitors = client.hgetall(key)
        visitor_list = []
        for sid, data in visitors.items():
            visitor_list.append(json.loads(data))
        
        total = len(visitor_list)
        start = (page - 1) * size
        end = start + size
        paginated_visitors = visitor_list[start:end]
        
        logger.info(f"Retrieved {len(paginated_visitors)} visitors for agent {agent_id} (page {page}, size {size}, total {total})")
        return {
            'visitors': paginated_visitors,
            'total': total,
            'page': page,
            'size': size
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