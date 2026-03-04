from logging_config import get_logger
import uuid
import datetime
import asyncio

logger = get_logger()


async def chat_with_visitor_controller_v1(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import get_visitor_sid_by_chat_session
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_visitor_message
        from services.elysium_atlas_services.atlas_chat_session_services import create_and_store_chat_messages
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")
        message = socketData.get("message")

        # Get the team member's user_id from their socket session
        session = await sio.get_session(sid)
        team_member_id = session.get("user_id") if session else None

        if not agent_id or not chat_session_id or message is None:
            logger.warning("atlas team member message missing agent_id/chat_session_id/message")
            return {"success": False, "message": "agent_id, chat_session_id and message are required"}
        
        message_arrived_at = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        # Build payload for storage (role is 'team-member')
        message_payload = {
            "message_id": str(uuid.uuid4()),
            "role": "human",
            "content": message,
            "created_at": message_arrived_at,
        }
        if team_member_id:
            message_payload["team_member_id"] = team_member_id

        # Always store the team-member message asynchronously
        asyncio.create_task(create_and_store_chat_messages(
            chat_session_id=chat_session_id,
            agent_id=agent_id,
            user_message_payload=None,
            agent_message_payload=message_payload,
        ))

        # Track team member participation on the chat session (idempotent, async)
        if team_member_id:
            from services.mongo_services import get_collection
            async def _add_team_member_id():
                collection = get_collection("atlas_chat_sessions")
                await collection.update_one(
                    {"chat_session_id": chat_session_id, "agent_id": agent_id},
                    {"$addToSet": {"team_member_ids": team_member_id}}
                )
                logger.info(f"Added team_member_id {team_member_id} to team_member_ids for chat_session_id {chat_session_id}")
            asyncio.create_task(_add_team_member_id())

        # Attempt to emit to visitor if they're online
        visitor_sid = get_visitor_sid_by_chat_session(agent_id, chat_session_id)
        if visitor_sid:
            await emit_visitor_message(visitor_sid, agent_id, chat_session_id, message, team_member_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}. Message stored to DB.")

        return {"success": True, "message": "Message stored and emitted if visitor present"}

    except Exception as e:
        logger.error(f"Error in chat_with_visitor_controller_v1: {e}")
        return {"success": False, "message": "An error occurred while handling the team-member message."}

async def team_member_start_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import update_visitor_conversation_status
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_started
        from sockets import sio

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        # Get user_id from the team member's session
        session = await sio.get_session(sid)
        user_id = session.get("user_id") if session else None

        visitor_sid = update_visitor_conversation_status(agent_id, chat_session_id, user_id)
        if visitor_sid:
            await emit_conversation_started(visitor_sid, agent_id, chat_session_id, user_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in team_member_start_conversation_controller: {e}")

async def team_member_end_conversation_controller(sid, socketData):
    try:
        from services.elysium_atlas_services.atlas_redis_services import update_visitor_conversation_status
        from services.elysium_atlas_services.atlas_team_member_emit_services import emit_conversation_ended

        agent_id = socketData.get("agent_id")
        chat_session_id = socketData.get("chat_session_id")

        visitor_sid = update_visitor_conversation_status(agent_id, chat_session_id, None)
        if visitor_sid:
            await emit_conversation_ended(visitor_sid, agent_id, chat_session_id)
        else:
            logger.warning(f"Visitor not found for agent {agent_id}, chat_session_id {chat_session_id}")

    except Exception as e:
        logger.error(f"Error in team_member_end_conversation_controller: {e}")