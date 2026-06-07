from typing import Any, Dict, List, TypedDict

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    DEFAULT_THREAD_MESSAGE_LIMIT,
    RUN_TYPE_SYNC,
)
from services.email_agent_services.email_flows.email_flow_engine import (
    run_agent_thread_flow,
)

logger = get_logger()


class SyncThreadFlowTrigger(TypedDict):
    thread_id: str
    trigger_message_id: str


async def run_sync_flows_for_threads(
    agent_id: str,
    thread_triggers: List[SyncThreadFlowTrigger],
    *,
    message_limit: int = DEFAULT_THREAD_MESSAGE_LIMIT,
) -> Dict[str, Any]:
    """
    Run the email flow sequentially for threads that received new inbound messages
    during inbox sync. Uses production idempotency (force_reprocess=False).
    """
    results: List[Dict[str, Any]] = []

    for trigger in thread_triggers:
        thread_id = trigger["thread_id"]
        trigger_message_id = trigger.get("trigger_message_id", "")

        logger.info(
            f"Starting sync-triggered flow agent_id={agent_id} thread_id={thread_id} "
            f"trigger_message_id={trigger_message_id or '(auto)'}"
        )

        try:
            flow_result = await run_agent_thread_flow(
                agent_id=agent_id,
                thread_id=thread_id,
                trigger_message_id=trigger_message_id,
                force_reprocess=False,
                message_limit=message_limit,
                run_type=RUN_TYPE_SYNC,
            )
            results.append({
                "thread_id": thread_id,
                "trigger_message_id": trigger_message_id,
                "success": flow_result.get("success", False),
                "status": flow_result.get("data", {}).get("status", ""),
                "run_id": flow_result.get("data", {}).get("run_id", ""),
                "message": flow_result.get("message", ""),
            })
        except Exception as exc:
            logger.error(
                f"Sync-triggered flow failed agent_id={agent_id} thread_id={thread_id}: {exc}",
                exc_info=True,
            )
            results.append({
                "thread_id": thread_id,
                "trigger_message_id": trigger_message_id,
                "success": False,
                "status": "failed",
                "run_id": "",
                "message": str(exc),
            })

    completed = sum(1 for item in results if item.get("success"))
    failed = sum(
        1 for item in results
        if not item.get("success") and item.get("status") != "skipped"
    )
    skipped = sum(1 for item in results if item.get("status") == "skipped")

    logger.info(
        f"Sync-triggered flows finished agent_id={agent_id}: "
        f"total={len(results)}, completed={completed}, failed={failed}, skipped={skipped}"
    )

    return {
        "threads_processed": len(results),
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }
