from typing import Any

from logging_config import get_logger
from services.elysium_atlas_services.agent_db_operations import get_agent_by_id, update_agent_fields
from config.human_handover_config import (
    get_default_human_handover_config,
    merge_human_handover_config,
    normalize_human_handover_config,
)

logger = get_logger()


async def get_human_handover_config_for_agent(agent_id: str) -> dict[str, Any] | None:
    """
    Return normalized human_handover_config for an agent.

    Returns None when the agent does not exist.
    """
    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None

    existing = agent.get("human_handover_config")
    if not isinstance(existing, dict):
        return get_default_human_handover_config()

    return normalize_human_handover_config(existing)


async def update_human_handover_config_for_agent(
    agent_id: str,
    partial: dict,
) -> tuple[dict | None, str | None]:
    """
    Merge partial human_handover_config and persist on the agent document.

    Returns:
        (merged_config, error_message)
    """
    if not partial:
        return None, "At least one human handover field must be provided."

    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None, "Agent not found."

    existing = agent.get("human_handover_config")
    merged, error_message = merge_human_handover_config(existing, partial)
    if error_message:
        return None, error_message

    updated = await update_agent_fields(
        agent_id,
        {"human_handover_config": merged},
    )
    if not updated:
        logger.warning(
            "Human handover config update reported no modifications for agent_id=%s",
            agent_id,
        )

    return merged, None


async def reset_human_handover_config_for_agent(agent_id: str) -> tuple[dict | None, str | None]:
    """
    Reset human_handover_config to defaults for an agent.

    Returns:
        (default_config, error_message)
    """
    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None, "Agent not found."

    default_config = get_default_human_handover_config()
    updated = await update_agent_fields(
        agent_id,
        {"human_handover_config": default_config},
    )
    if not updated:
        logger.warning(
            "Human handover config reset reported no modifications for agent_id=%s",
            agent_id,
        )

    return default_config, None
