# helpers/socket_user_registry.py
from datetime import datetime, timezone
from logging_config import get_logger
from services.redis_services import cache_get, cache_set, delete_cache

logger = get_logger()

SOCKET_REDIS_TTL_SECONDS = 48 * 60 * 60  # 48 hours

def _now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def upsert_user_socket_mapping(user_data: dict, sid: str) -> dict:
    """
    Ensures Redis has a single JSON entry per user:
      Key:   socket_user_id_{user_id}
      Value: {"user_id": "...", "socket_ids": [...], "connected_at": "..."}
    """
    user_id = user_data.get("user_id") or user_data.get("userId")
    if not user_id:
        logger.warning("[socket-registry] Missing user_id in user_data; skipping.")
        return {}

    key = f"socket_user_id_{user_id}"
    existing = cache_get(key) or {
        "user_id": user_id,
        "company_id": user_data.get("company_id") or user_data.get("companyId") or 0,
        "socket_ids": [],
        "connected_at": _now_iso(),
    }

    # Append sid if not already present
    socket_ids = set(existing.get("socket_ids") or [])
    if sid not in socket_ids:
        socket_ids.add(sid)

    # Update the record
    record = {
        "user_id": user_id,
        "company_id": user_data.get("company_id") or user_data.get("companyId") or 0,
        "socket_ids": list(socket_ids),
        "connected_at": existing.get("connected_at") or _now_iso()
    }

    cache_set({key: record}, ex=SOCKET_REDIS_TTL_SECONDS)
    logger.info(f"[socket-registry] Upserted {key}: {record}")
    return record

def remove_user_socket_mapping(user_data: dict, sid: str, delete_if_empty: bool = True):
    """
    Removes `sid` from the user's Redis record:
      Key: socket_user_id_{user_id}
      Value: {"user_id": "...", "socket_ids": [...], "connected_at": "...", "last_seen": "..."}

    If no sockets remain and delete_if_empty=True, deletes the key.
    Returns the updated record (or None if deleted/not found).
    """
    if not user_data:
        logger.warning("[socket-registry] remove: missing user_data; skipping.")
        return None

    user_id = str(
        user_data.get("user_id")
        or user_data.get("userId")
        or user_data.get("id")
        or ""
    ).strip()

    if not user_id:
        logger.warning("[socket-registry] remove: missing user_id in user_data; skipping.")
        return None

    key = f"socket_user_id_{user_id}"
    existing = cache_get(key)
    if not existing:
        logger.info(f"[socket-registry] remove: no existing record for {key}")
        return None

    sockets = set(existing.get("socket_ids") or [])
    if sid in sockets:
        sockets.remove(sid)

    if not sockets and delete_if_empty:
        delete_cache(key)
        logger.info(f"[socket-registry] remove: deleted {key} (no active sockets)")
        return None

    updated = {
        "user_id": user_id,
        "socket_ids": list(sockets),
        "connected_at": existing.get("connected_at"),
    }
    cache_set({key: updated}, ex=SOCKET_REDIS_TTL_SECONDS)
    logger.info(f"[socket-registry] remove: updated {key}: {updated}")
    return updated