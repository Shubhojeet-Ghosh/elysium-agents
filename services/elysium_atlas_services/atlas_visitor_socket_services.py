from logging_config import get_logger
from services.elysium_atlas_services.atlas_redis_services import add_visitor_to_agent, get_visitors_for_agent, get_visitor_count_for_agent, remove_visitor_from_agent
from services.elysium_atlas_services.atlas_chat_session_services import set_visitor_online_status

logger = get_logger()

async def handle_visitor_connection(agent_id, chat_session_id, sid):
    from sockets import sio
    room_name = f"agent_{agent_id}_visitors"
    await sio.enter_room(sid, room_name)
    logger.info(f"Socket {sid} joined room {room_name} for chat_session_id {chat_session_id}")
    
    # Save agent_id and chat_session_id in session
    await sio.save_session(sid, {"agent_id": agent_id, "chat_session_id": chat_session_id})
    
    # Add visitor to Redis
    add_visitor_to_agent(agent_id, chat_session_id, sid)

    # Mark visitor as online in the chat session document
    await set_visitor_online_status(agent_id, chat_session_id, True)
    
    # # Get and log all visitors for testing
    # visitors = get_visitors_for_agent(agent_id)
    # logger.info(f"All visitors for agent {agent_id}: {visitors['visitors']}")
    
    # # Get visitor count
    # count = get_visitor_count_for_agent(agent_id)
    # logger.info(f"Visitor count for agent {agent_id}: {count}")

async def handle_atlas_visitor_connected_service(socketData, sid=None):
    try:
        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        
        if agent_id and sid:
            await handle_visitor_connection(agent_id, chat_session_id, sid)

    except Exception as e:
        logger.error(f"Error handling atlas visitor connected: {e}")
