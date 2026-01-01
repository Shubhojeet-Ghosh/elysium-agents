"""
Socket emit services for handling Socket.IO emissions
"""

from logging_config import get_logger

logger = get_logger()

async def emit_atlas_response(sid=None, room=None, message=None, payload=None, skip_sid=None):
    """
    Emit an atlas_response event to a specific socket ID or room.
    
    :param sid: The socket ID to emit to (mutually exclusive with room)
    :param room: The room ID to emit to (mutually exclusive with sid)
    :param message: The message string
    :param payload: The payload data
    :param skip_sid: The socket ID to skip when emitting to a room
    """
    try:
        from sockets import sio

        if sid and room:
            logger.error("Cannot specify both sid and room for emit_atlas_response")
            return {"success": False, "message": "Cannot specify both sid and room"}
        
        elif sid:
            await sio.emit("atlas_response", {"message": message, "payload": payload}, to=sid)
            logger.info(f"Emitted atlas_response to socket {sid}.")
            return {"success": True, "message": f"Emitted atlas_response to socket {sid}."}

        elif room:
            kwargs = {"room": room}
            if skip_sid:
                kwargs["skip_sid"] = skip_sid

            await sio.emit("atlas_response", {"message": message, "payload": payload}, **kwargs)
            logger.info(f"Emitted atlas_response to room {room} (skipping {skip_sid} if provided).")
            return {"success": True, "message": f"Emitted atlas_response to room {room}."}

        else:
            logger.error("Either sid or room must be provided for emit_atlas_response")
            return {"success": False, "message": "Either sid or room must be provided"}
        
    except Exception as e:
        logger.error(f"Error emitting atlas_response: {e}")
        return {"success": False, "message": "Error emitting atlas_response"}


async def emit_atlas_response_chunk(chunk, done=False, sid=None, room=None, skip_sid=None):
    """
    Emit a single atlas response chunk to a specific socket ID or room.
    Useful for streaming LLM responses one chunk at a time.
    
    :param chunk: Single text chunk to emit
    :param done: Whether this is the final chunk (default: False)
    :param sid: The socket ID to emit to (mutually exclusive with room)
    :param room: The room ID to emit to (mutually exclusive with sid)
    :param skip_sid: The socket ID to skip when emitting to a room
    """
    try:
        from sockets import sio

        if sid and room:
            logger.error("Cannot specify both sid and room for emit_atlas_response_chunk")
            return {"success": False, "message": "Cannot specify both sid and room"}
        
        if not sid and not room:
            logger.error("Either sid or room must be provided for emit_atlas_response_chunk")
            return {"success": False, "message": "Either sid or room must be provided"}
        
        # Determine emit target
        emit_kwargs = {}
        if sid:
            emit_kwargs["to"] = sid
            target_info = f"socket {sid}"
        else:
            emit_kwargs["room"] = room
            if skip_sid:
                emit_kwargs["skip_sid"] = skip_sid
            target_info = f"room {room}"

        # Emit the chunk
        await sio.emit("atlas_response_chunk", {"chunk": chunk, "done": done}, **emit_kwargs)
        
        return {"success": True, "message": f"Emitted chunk to {target_info}"}
        
    except Exception as e:
        logger.error(f"Error emitting atlas_response_chunk: {e}")
        return {"success": False, "message": f"Error emitting atlas_response_chunk: {str(e)}"}