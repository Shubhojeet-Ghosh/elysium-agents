"""
Write-only Socket.IO emitter for background processes (ARQ worker, scripts).

The FastAPI process owns real client connections. Auxiliary processes must publish
events through Redis using the same channel as sockets.py.
"""

import socketio
from socketio import AsyncRedisManager

from config.settings import settings

REDIS_URL = f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
# Must match AsyncRedisManager(channel=...) in sockets.py
SOCKETIO_REDIS_CHANNEL = "socketio"

_external_sio: socketio.AsyncServer | None = None


def get_external_sio() -> socketio.AsyncServer:
    global _external_sio
    if _external_sio is None:
        manager = AsyncRedisManager(
            REDIS_URL,
            write_only=True,
            channel=SOCKETIO_REDIS_CHANNEL,
        )
        _external_sio = socketio.AsyncServer(async_mode="asgi", client_manager=manager)
    return _external_sio


async def emit_to_room(event: str, data: dict, room: str) -> None:
    sio = get_external_sio()
    await sio.emit(event, data, room=room)
