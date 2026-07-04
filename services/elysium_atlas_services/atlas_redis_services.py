import json
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


# Visitor and team-member live presence: atlas_presence_services.py (Mongo)


def _session_monitors_key(agent_id: str) -> str:
    return f"atlas_{agent_id}_session_monitors"


def _load_session_monitors(client, key: str, chat_session_id: str) -> list[dict]:
    raw = client.hget(key, chat_session_id)
    if not raw:
        return []
    try:
        monitors = json.loads(raw)
        return monitors if isinstance(monitors, list) else []
    except json.JSONDecodeError:
        return []


def _save_session_monitors(client, key: str, chat_session_id: str, monitors: list[dict]) -> None:
    if monitors:
        client.hset(key, chat_session_id, json.dumps(monitors))
    else:
        client.hdel(key, chat_session_id)


def add_session_monitor(agent_id: str, chat_session_id: str, user_id: str, sid: str) -> bool:
    """
    Register a team member socket as a passive monitor for a chat session.

    Redis hash: atlas_{agent_id}_session_monitors
    Field: chat_session_id → JSON list of {user_id, sid}
    """
    try:
        if not agent_id or not chat_session_id or not user_id or not sid:
            return False
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        monitors = _load_session_monitors(client, key, chat_session_id)
        monitors = [m for m in monitors if m.get("user_id") != user_id or m.get("sid") != sid]
        monitors.append({"user_id": user_id, "sid": sid})
        _save_session_monitors(client, key, chat_session_id, monitors)
        logger.info(
            f"Added monitor user_id={user_id} sid={sid} for chat_session_id={chat_session_id} "
            f"on agent {agent_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error adding session monitor for agent {agent_id}, chat_session_id {chat_session_id}: {e}"
        )
        return False


def remove_session_monitor(
    agent_id: str,
    chat_session_id: str,
    user_id: str,
    sid: str | None = None,
) -> bool:
    """Remove a team member from passive monitor list for a chat session."""
    try:
        if not agent_id or not chat_session_id or not user_id:
            return False
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        monitors = _load_session_monitors(client, key, chat_session_id)
        if not monitors:
            return False

        if sid:
            updated = [
                m for m in monitors
                if not (m.get("user_id") == user_id and m.get("sid") == sid)
            ]
        else:
            updated = [m for m in monitors if m.get("user_id") != user_id]

        if len(updated) == len(monitors):
            return False

        _save_session_monitors(client, key, chat_session_id, updated)
        logger.info(
            f"Removed monitor user_id={user_id} sid={sid} for chat_session_id={chat_session_id} "
            f"on agent {agent_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error removing session monitor for agent {agent_id}, chat_session_id {chat_session_id}: {e}"
        )
        return False


def get_session_monitors(agent_id: str, chat_session_id: str) -> list[dict]:
    """Return monitor registrations {user_id, sid} for a chat session."""
    try:
        if not agent_id or not chat_session_id:
            return []
        client = get_redis_client()
        return _load_session_monitors(client, _session_monitors_key(agent_id), chat_session_id)
    except Exception as e:
        logger.error(
            f"Error getting session monitors for agent {agent_id}, chat_session_id {chat_session_id}: {e}"
        )
        return []


def get_session_monitor_sids(agent_id: str, chat_session_id: str) -> list[str]:
    """Return socket IDs of team members passively monitoring a chat session."""
    try:
        if not agent_id or not chat_session_id:
            return []
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        monitors = _load_session_monitors(client, key, chat_session_id)
        sids: list[str] = []
        for monitor in monitors:
            monitor_sid = monitor.get("sid")
            if monitor_sid:
                sids.append(monitor_sid if isinstance(monitor_sid, str) else monitor_sid.decode())
        return sids
    except Exception as e:
        logger.error(
            f"Error getting session monitor sids for agent {agent_id}, chat_session_id {chat_session_id}: {e}"
        )
        return []


def is_session_monitor(
    agent_id: str,
    chat_session_id: str,
    user_id: str,
    sid: str | None = None,
) -> bool:
    """True when the team member (optionally a specific socket) is monitoring the session."""
    try:
        if not agent_id or not chat_session_id or not user_id:
            return False
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        monitors = _load_session_monitors(client, key, chat_session_id)
        for monitor in monitors:
            if monitor.get("user_id") != user_id:
                continue
            if sid is None or monitor.get("sid") == sid:
                return True
        return False
    except Exception as e:
        logger.error(
            f"Error checking session monitor for agent {agent_id}, chat_session_id {chat_session_id}: {e}"
        )
        return False


def get_session_monitor_sids_excluding_user(
    agent_id: str,
    chat_session_id: str,
    exclude_user_id: str,
    exclude_sid: str | None = None,
) -> list[str]:
    """Monitor socket IDs for a session, excluding the team member who took over."""
    try:
        if not agent_id or not chat_session_id or not exclude_user_id:
            return get_session_monitor_sids(agent_id, chat_session_id)
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        monitors = _load_session_monitors(client, key, chat_session_id)
        sids: list[str] = []
        for monitor in monitors:
            if monitor.get("user_id") == exclude_user_id:
                if exclude_sid is None or monitor.get("sid") == exclude_sid:
                    continue
            monitor_sid = monitor.get("sid")
            if monitor_sid:
                sids.append(monitor_sid if isinstance(monitor_sid, str) else monitor_sid.decode())
        return sids
    except Exception as e:
        logger.error(
            f"Error getting session monitor sids excluding user for agent {agent_id}, "
            f"chat_session_id {chat_session_id}: {e}"
        )
        return []


def remove_all_session_monitors_for_user(agent_id: str, user_id: str, sid: str | None = None) -> None:
    """Clear monitor registrations for a user (optionally scoped to one socket) across all sessions."""
    try:
        if not agent_id or not user_id:
            return
        client = get_redis_client()
        key = _session_monitors_key(agent_id)
        all_sessions = client.hgetall(key)
        for chat_session_id, raw in all_sessions.items():
            session_id = chat_session_id if isinstance(chat_session_id, str) else chat_session_id.decode()
            try:
                monitors = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(monitors, list):
                continue
            if sid:
                updated = [
                    m for m in monitors
                    if not (m.get("user_id") == user_id and m.get("sid") == sid)
                ]
            else:
                updated = [m for m in monitors if m.get("user_id") != user_id]
            if len(updated) != len(monitors):
                _save_session_monitors(client, key, session_id, updated)
        logger.info(f"Cleared session monitors for user_id={user_id} on agent {agent_id}")
    except Exception as e:
        logger.error(f"Error clearing session monitors for user {user_id} on agent {agent_id}: {e}")
