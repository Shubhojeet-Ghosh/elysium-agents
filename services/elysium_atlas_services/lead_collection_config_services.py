from typing import Any

from logging_config import get_logger
from services.elysium_atlas_services.agent_db_operations import get_agent_by_id, update_agent_fields
from config.lead_collection_config import (
    get_default_lead_collection_config,
    get_lead_field_catalog,
    merge_lead_collection_config,
    normalize_lead_collection_config,
)

logger = get_logger()


async def get_lead_collection_config_for_agent(agent_id: str) -> dict[str, Any] | None:
    """
    Return normalized lead_collection_config for an agent.

    Returns None when the agent does not exist.
    """
    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None

    existing = agent.get("lead_collection_config")
    if not isinstance(existing, dict):
        return get_default_lead_collection_config()

    return normalize_lead_collection_config(existing)


async def update_lead_collection_config_for_agent(
    agent_id: str,
    partial: dict,
) -> tuple[dict | None, str | None]:
    """
    Merge partial lead_collection_config and persist on the agent document.

    Returns:
        (merged_config, error_message)
    """
    if not partial:
        return None, "At least one lead collection field must be provided."

    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None, "Agent not found."

    existing = agent.get("lead_collection_config")
    merged, error_message = merge_lead_collection_config(existing, partial)
    if error_message:
        return None, error_message

    updated = await update_agent_fields(
        agent_id,
        {"lead_collection_config": merged},
    )
    if not updated:
        logger.warning(
            "Lead collection config update reported no modifications for agent_id=%s",
            agent_id,
        )

    return merged, None


async def reset_lead_collection_config_for_agent(agent_id: str) -> tuple[dict | None, str | None]:
    """
    Reset lead_collection_config to defaults for an agent.

    Returns:
        (default_config, error_message)
    """
    agent = await get_agent_by_id(agent_id)
    if not agent:
        return None, "Agent not found."

    default_config = get_default_lead_collection_config()
    updated = await update_agent_fields(
        agent_id,
        {"lead_collection_config": default_config},
    )
    if not updated:
        logger.warning(
            "Lead collection config reset reported no modifications for agent_id=%s",
            agent_id,
        )

    return default_config, None


def get_lead_collection_field_catalog() -> list[dict[str, str]]:
    return get_lead_field_catalog()
