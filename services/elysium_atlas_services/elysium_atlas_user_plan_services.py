import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from logging_config import get_logger
from services.mongo_services import get_collection

logger = get_logger()

# Message shown to end-user clients (visitors) on any chat denial — keeps
# internal plan/billing details hidden from the agent's end users.
CLIENT_FACING_DENIAL_MESSAGE = "I'm sorry, I'm unable to process your request at this time. Please try again later."


# ---------------------------------------------------------------------------
# Helper: user plan
# ---------------------------------------------------------------------------

async def get_user_plan(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the active plan document for a given user from atlas_user_plans.

    Args:
        user_id: The user's ID.

    Returns:
        The plan document, or None if not found.
    """
    try:
        logger.info(f"Fetching plan for user_id: {user_id}")
        collection = get_collection("atlas_user_plans")
        plan = await collection.find_one({"user_id": user_id, "is_active": True})
        if plan:
            logger.info(f"Plan found for user_id: {user_id} - plan_id: {plan.get('plan_id')}, status: {plan.get('status')}")
        else:
            logger.warning(f"No plan document found for user_id: {user_id}")
        return plan
    except Exception as e:
        logger.error(f"Error fetching plan for user_id {user_id}: {e}")
        return None


async def mark_user_plan_expired(user_id: str) -> None:
    """
    Set the status of the user's plan document in atlas_user_plans to 'expired'.

    Args:
        user_id: The user's ID.
    """
    try:
        collection = get_collection("atlas_user_plans")
        await collection.update_one(
            {"user_id": user_id, "is_active": True},
            {"$set": {"status": "expired", "updatedAt": datetime.now(timezone.utc)}}
        )
        logger.info(f"Marked plan as expired for user_id: {user_id}")
    except Exception as e:
        logger.error(f"Error marking plan expired for user_id {user_id}: {e}")


# ---------------------------------------------------------------------------
# Helper: plan limits
# ---------------------------------------------------------------------------

async def get_user_plan_limits(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the plan limits document for a given user from atlas_user_available_plan_limits.

    Args:
        user_id: The user's ID.

    Returns:
        The plan limits document, or None if not found.
    """
    try:
        logger.info(f"Fetching plan limits for user_id: {user_id}")
        collection = get_collection("atlas_user_available_plan_limits")
        plan = await collection.find_one({"user_id": user_id})
        if plan:
            logger.info(f"Plan limits found for user_id: {user_id} - ai_agents: {plan.get('ai_agents')}, ai_queries: {plan.get('ai_queries')}")
        else:
            logger.warning(f"No plan limits document found for user_id: {user_id}")
        return plan
    except Exception as e:
        logger.error(f"Error fetching plan limits for user_id {user_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Helper: agent counts
# ---------------------------------------------------------------------------

async def get_user_agent_count(user_id: str) -> int:
    """
    Return the number of agents currently built under the given user_id.

    Args:
        user_id: The user's ID (matched against owner_user_id in atlas_agents).

    Returns:
        The count of agent documents, or 0 on error.
    """
    try:
        logger.info(f"Counting agents for user_id: {user_id}")
        collection = get_collection("atlas_agents")
        count = await collection.count_documents({"owner_user_id": user_id})
        logger.info(f"Agent count for user_id {user_id}: {count}")
        return count
    except Exception as e:
        logger.error(f"Error counting agents for user_id {user_id}: {e}")
        return 0


# ---------------------------------------------------------------------------
# Shared: plan validity check (expiry)
# ---------------------------------------------------------------------------

async def validate_user_plan_active(user_id: str) -> Dict[str, Any]:
    """
    Checks that the user has an existing, non-expired plan in atlas_user_plans.
    If the plan has expired, marks it as expired in the DB.

    Args:
        user_id: The user's ID.

    Returns:
        dict: {"success": True, "user_plan": <doc>} if valid,
              {"success": False, "message": <reason>} otherwise.
    """
    try:
        logger.info(f"Validating active plan for user_id: {user_id}")
        user_plan = await get_user_plan(user_id)

        if user_plan is None:
            logger.warning(f"Plan validation failed - no plan document for user_id: {user_id}")
            return {
                "success": False,
                "message": "No active plan found for this account. Please set up a plan to continue."
            }

        expires_at = user_plan.get("expires_at")
        if expires_at is not None:
            if isinstance(expires_at, datetime):
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                else:
                    expires_at = expires_at.astimezone(timezone.utc)
            else:
                parsed = datetime.fromisoformat(str(expires_at))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                expires_at = parsed.astimezone(timezone.utc)

            now_utc = datetime.now(timezone.utc)
            logger.info(f"Plan expiry check for user_id {user_id}: now={now_utc.isoformat()}, expires_at={expires_at.isoformat()}")

            if now_utc >= expires_at:
                logger.warning(f"Plan expired for user_id: {user_id} - expired at {expires_at.isoformat()}")
                await mark_user_plan_expired(user_id)
                return {
                    "success": False,
                    "message": "Your plan has expired. Please renew or upgrade your plan to continue."
                }

        logger.info(f"Plan is active for user_id: {user_id}")
        return {"success": True, "user_plan": user_plan}

    except Exception as e:
        logger.error(f"Error in validate_user_plan_active for user_id {user_id}: {e}")
        return {"success": False, "message": "An error occurred while validating the plan."}


# ---------------------------------------------------------------------------
# Permission check: build agent
# ---------------------------------------------------------------------------

async def can_user_build_agent(user_id: str, requestData: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks whether the user's current plan allows them to build additional agents.

    Validates:
      1. Plan exists and has not expired (via validate_user_plan_active).
      2. User has a plan limits document in atlas_user_available_plan_limits.
      3. Current agent count is below the ai_agents limit.

    Args:
        user_id: The ID of the user performing the action.
        requestData: The request payload (reserved for future action-specific checks).

    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    try:
        logger.info(f"Checking agent build permission for user_id: {user_id}")
        plan_check, plan_limits, current_agent_count = await asyncio.gather(
            validate_user_plan_active(user_id),
            get_user_plan_limits(user_id),
            get_user_agent_count(user_id)
        )

        if not plan_check.get("success"):
            logger.warning(f"Agent build denied for user_id {user_id}: {plan_check.get('message')}")
            return plan_check

        if plan_limits is None:
            logger.warning(f"Agent build denied for user_id {user_id}: no plan limits document found")
            return {
                "success": False,
                "message": "Plan limits not configured for this account. Please contact support."
            }

        max_agents = plan_limits.get("ai_agents", 0)
        logger.info(f"Agent build check for user_id {user_id}: current={current_agent_count}, max={max_agents}")

        if current_agent_count >= max_agents:
            logger.warning(f"Agent build denied for user_id {user_id}: limit reached ({current_agent_count}/{max_agents})")
            return {
                "success": False,
                "message": (
                    f"You have reached the maximum number of agents ({max_agents}) "
                    "allowed on your current plan. Please upgrade to create more agents."
                )
            }

        logger.info(f"Agent build permitted for user_id {user_id}: ({current_agent_count}/{max_agents})")
        return {"success": True, "message": "User is allowed to build a new agent."}

    except Exception as e:
        logger.error(f"Error in can_user_build_agent for user_id {user_id}: {e}")
        return {"success": False, "message": "An error occurred while checking agent build permissions."}


# ---------------------------------------------------------------------------
# Permission check: send chat message
# ---------------------------------------------------------------------------

async def can_user_send_chat(user_id: str, chatPayload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks whether the user's current plan allows them to send more chat messages.

    Validates:
      1. Plan exists and has not expired (via validate_user_plan_active).
      2. User has a plan limits document in atlas_user_available_plan_limits.
      3. Remaining ai_queries limit is greater than 0.

    Note: This function does NOT decrement ai_queries — that is handled separately.

    Args:
        user_id: The ID of the user sending the message.
        chatPayload: The chat request payload (reserved for future checks).

    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    try:
        logger.info(f"Checking chat send permission for user_id: {user_id}")
        plan_check, plan_limits = await asyncio.gather(
            validate_user_plan_active(user_id),
            get_user_plan_limits(user_id)
        )

        if not plan_check.get("success"):
            logger.warning(f"Chat send denied for user_id {user_id}: {plan_check.get('message')}")
            return {**plan_check, "client_message": CLIENT_FACING_DENIAL_MESSAGE}

        if plan_limits is None:
            logger.warning(f"Chat send denied for user_id {user_id}: no plan limits document found")
            return {
                "success": False,
                "message": "Plan limits not configured for this account. Please contact support.",
                "client_message": CLIENT_FACING_DENIAL_MESSAGE
            }

        ai_queries_remaining = plan_limits.get("ai_queries", 0)
        logger.info(f"Chat query check for user_id {user_id}: ai_queries_remaining={ai_queries_remaining}")

        if ai_queries_remaining <= 0:
            logger.warning(f"Chat send denied for user_id {user_id}: no ai_queries remaining")
            return {
                "success": False,
                "message": "You have used all your AI query credits for this plan. Please upgrade to continue chatting.",
                "client_message": CLIENT_FACING_DENIAL_MESSAGE
            }

        logger.info(f"Chat send permitted for user_id {user_id}: {ai_queries_remaining} queries remaining")
        return {"success": True, "message": "User is allowed to send a chat message."}

    except Exception as e:
        logger.error(f"Error in can_user_send_chat for user_id {user_id}: {e}")
        return {"success": False, "message": "An error occurred while checking chat permissions."}


# ---------------------------------------------------------------------------
# Usage tracking: decrement ai_queries
# ---------------------------------------------------------------------------

async def decrement_user_ai_queries(user_id: str) -> None:
    """
    Decrements the ai_queries counter in atlas_user_available_plan_limits by 1
    for the given user_id. Will not go below 0.

    Args:
        user_id: The user's ID.
    """
    try:
        collection = get_collection("atlas_user_available_plan_limits")
        result = await collection.update_one(
            {"user_id": user_id, "ai_queries": {"$gt": 0}},
            {"$inc": {"ai_queries": -1}}
        )
        if result.modified_count:
            logger.info(f"Decremented ai_queries for user_id: {user_id}")
        else:
            logger.warning(f"ai_queries not decremented for user_id {user_id} (already 0 or document missing)")
    except Exception as e:
        logger.error(f"Error decrementing ai_queries for user_id {user_id}: {e}")