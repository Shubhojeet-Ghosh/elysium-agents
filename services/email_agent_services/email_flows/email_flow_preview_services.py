"""
Test/dev helpers that wrap node handlers for manual verification.

Production path (no HTTP):
  sync inserts inbound → enqueue_flow_run() → run_flow() → execute_*_node() services

These preview_* functions are what test APIs call; the flow engine will call the same
node handlers (e.g. execute_load_thread_context_node) directly.
"""

from typing import Any, Dict

from bson.errors import InvalidId
from bson import ObjectId

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import get_email_ai_agent_by_id
from services.email_agent_services.email_flows.email_flow_constants import (
    FLOW_RUN_STATUS_COMPLETED,
    FLOW_RUN_STATUS_FAILED,
    NODE_LOG_STATUS_FAILED,
)
from services.email_agent_services.email_flows.email_flow_context import (
    build_initial_flow_context,
    serialize_for_json,
)
from services.email_agent_services.email_flows.email_flow_run_mongo_services import (
    append_flow_node_log,
    create_flow_run,
    generate_run_id,
    get_flow_run_by_id,
    list_flow_runs_for_thread,
    serialize_flow_run,
    update_flow_run_context,
)
from services.email_agent_services.email_flows.nodes.load_thread_context_node import (
    execute_load_thread_context_node,
)

logger = get_logger()


async def preview_load_thread_context(
    *,
    agent_id: str,
    thread_id: str,
    trigger_message_id: str = "",
    persist_run_log: bool = True,
    message_limit: int = 10,
) -> Dict[str, Any]:
    """
    Run the Load Thread Context node and return the flow context preview.

    Optionally persists an email-flow-runs document with the node log entry.
    """
    normalized_agent_id = agent_id.strip()
    normalized_thread_id = thread_id.strip()

    try:
        ObjectId(normalized_agent_id)
    except InvalidId:
        return {
            "success": False,
            "status_code": 400,
            "message": "Invalid agent_id.",
        }

    agent = await get_email_ai_agent_by_id(normalized_agent_id)
    if not agent:
        return {
            "success": False,
            "status_code": 404,
            "message": "Email AI agent not found.",
        }

    if agent.get("status") != "active":
        return {
            "success": False,
            "status_code": 400,
            "message": "Agent is not active.",
        }

    team_id = (agent.get("team_id") or "").strip()
    run_id = generate_run_id() if persist_run_log else ""

    context = build_initial_flow_context(
        run_id=run_id,
        agent_id=normalized_agent_id,
        team_id=team_id,
        thread_id=normalized_thread_id,
        trigger_message_id=trigger_message_id.strip(),
        system_prompt=agent.get("system_prompt", "") or "",
    )

    if persist_run_log:
        await create_flow_run(
            run_id=run_id,
            agent_id=normalized_agent_id,
            team_id=team_id,
            thread_id=normalized_thread_id,
            trigger_message_id=trigger_message_id.strip(),
            context=context,
            preview=True,
        )

    context, node_log = await execute_load_thread_context_node(
        context,
        {"message_limit": message_limit},
        agent,
    )

    if persist_run_log:
        await append_flow_node_log(
            run_id,
            node_id=node_log["node_id"],
            node_type=node_log["node_type"],
            status=node_log["status"],
            started_at=node_log["started_at"],
            completed_at=node_log["completed_at"],
            duration_ms=node_log["duration_ms"],
            input_summary=node_log["input_summary"],
            output=node_log["output"],
            error=node_log.get("error"),
            context=context,
        )

        final_status = (
            FLOW_RUN_STATUS_FAILED
            if node_log["status"] == NODE_LOG_STATUS_FAILED
            else FLOW_RUN_STATUS_COMPLETED
        )
        await update_flow_run_context(
            run_id,
            context=context,
            current_node_id=node_log["node_id"],
            status=final_status,
        )

    response_data = {
        "run_id": run_id or None,
        "node_log": _serialize_node_log(node_log),
        "flow_context_preview": serialize_for_json(context),
    }

    if node_log["status"] == NODE_LOG_STATUS_FAILED:
        return {
            "success": False,
            "status_code": 400,
            "message": node_log.get("error") or "Load Thread Context failed.",
            "data": response_data,
        }

    response_data["downstream_hints"] = node_log["output"].get("downstream_hints", {})

    return {
        "success": True,
        "status_code": 200,
        "message": "Load Thread Context preview generated successfully.",
        "data": response_data,
    }


async def get_flow_run_detail(run_id: str) -> Dict[str, Any]:
    run_doc = await get_flow_run_by_id(run_id.strip())
    if not run_doc:
        return {
            "success": False,
            "status_code": 404,
            "message": "Flow run not found.",
        }

    return {
        "success": True,
        "status_code": 200,
        "message": "Flow run fetched successfully.",
        "data": serialize_flow_run(run_doc),
    }


async def list_thread_flow_runs(
    *,
    team_id: str,
    thread_id: str,
    limit: int = 20,
) -> Dict[str, Any]:
    runs = await list_flow_runs_for_thread(
        thread_id=thread_id,
        team_id=team_id,
        limit=limit,
    )
    return {
        "success": True,
        "status_code": 200,
        "message": "Flow runs fetched successfully.",
        "data": {
            "team_id": team_id.strip(),
            "thread_id": thread_id.strip(),
            "count": len(runs),
            "runs": runs,
        },
    }


def _serialize_node_log(node_log: Dict[str, Any]) -> Dict[str, Any]:
    return serialize_for_json({
        "node_id": node_log.get("node_id"),
        "node_type": node_log.get("node_type"),
        "status": node_log.get("status"),
        "started_at": node_log.get("started_at"),
        "completed_at": node_log.get("completed_at"),
        "duration_ms": node_log.get("duration_ms"),
        "input_summary": node_log.get("input_summary", {}),
        "output": node_log.get("output", {}),
        "error": node_log.get("error"),
    })
