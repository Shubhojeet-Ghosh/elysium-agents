from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    NODE_LOG_STATUS_OK,
    NODE_TYPE_STOP,
)

logger = get_logger()

NODE_ID = "stop"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def execute_stop_node(
    context: Dict[str, Any],
    config: Dict[str, Any],
    agent: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Terminal node — marks the pipeline complete without further side effects."""
    started_at = _utc_now()
    thread_id = (context.get("thread_id") or "").strip()
    final_action = context.get("final_action") or {}

    logger.info(
        f"stop_node completed thread_id={thread_id} "
        f"final_action_type={(final_action.get('type') or 'none')}"
    )

    completed_at = _utc_now()
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    node_log = {
        "node_id": NODE_ID,
        "node_type": NODE_TYPE_STOP,
        "status": NODE_LOG_STATUS_OK,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "input_summary": {
            "thread_id": thread_id,
            "final_action_type": final_action.get("type", ""),
        },
        "output": {
            "final_action": final_action,
        },
    }
    return context, node_log
