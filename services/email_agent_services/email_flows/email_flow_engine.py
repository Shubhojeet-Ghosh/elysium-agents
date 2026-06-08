from typing import Any, Awaitable, Callable, Dict, List, Tuple

from bson.errors import InvalidId
from bson import ObjectId

from logging_config import get_logger
from services.email_agent_services.email_ai_agent_services import get_email_ai_agent_by_id
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_TOOLS_DEFAULT_MAX_CALLS,
    FLOW_RUN_STATUS_COMPLETED,
    FLOW_RUN_STATUS_FAILED,
    FLOW_RUN_STATUS_QUEUED,
    FLOW_RUN_STATUS_RUNNING,
    FLOW_RUN_STATUS_SKIPPED,
    MESSAGE_PROCESSING_STATUS_COMPLETED,
    MESSAGE_PROCESSING_STATUS_FAILED,
    NODE_LOG_STATUS_FAILED,
    NODE_LOG_STATUS_OK,
    NODE_LOG_STATUS_SKIPPED,
    REPLY_ACTION_MODE_DRAFT,
    REPLY_ACTION_MODE_AUTO_SEND,
    RUN_TYPE_PREVIEW,
    RUN_TYPE_REPROCESS,
)
from services.email_agent_services.email_flows.email_flow_mongo_services import (
    get_flow_by_id,
)
from services.email_agent_services.email_flows.email_flow_validation_services import (
    extract_call_external_tool_config,
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
    update_flow_run_context,
    update_flow_run_status,
    update_flow_run_trigger_message,
)
from services.email_agent_services.email_flows.nodes.load_thread_context_node import (
    execute_load_thread_context_node,
)
from services.email_agent_services.email_flows.nodes.read_kb_node import (
    execute_read_kb_node,
)
from services.email_agent_services.email_flows.nodes.ai_department_router_node import (
    execute_ai_department_router_node,
)
from services.email_agent_services.email_flows.nodes.ai_recipients_generator_node import (
    execute_ai_recipients_generator_node,
)
from services.email_agent_services.email_flows.nodes.generate_email_node import (
    execute_generate_email_node,
)
from services.email_agent_services.email_flows.nodes.read_tools_node import (
    execute_read_tools_node,
)
from services.email_agent_services.email_flows.nodes.call_external_tool_node import (
    execute_call_external_tool_node,
)
from services.email_agent_services.email_flows.nodes.save_gmail_draft_node import (
    execute_save_gmail_draft_node,
)
from services.email_agent_services.email_flows.nodes.send_email_node import (
    execute_send_email_node,
)
from services.email_agent_services.email_flows.nodes.stop_node import (
    execute_stop_node,
)
from services.email_agent_services.email_flows.email_flow_thread_data_services import (
    finalize_thread_ai_status,
)
from services.email_agent_services.email_flows.nodes.start_node import (
    execute_start_node,
    set_trigger_message_processing,
)

logger = get_logger()

NodeHandler = Callable[
    [Dict[str, Any], Dict[str, Any], Dict[str, Any]],
    Awaitable[Tuple[Dict[str, Any], Dict[str, Any]]],
]

# MVP pipeline — extend as each node ships
MVP_FLOW_PIPELINE: List[Tuple[str, str, Dict[str, Any]]] = [
    ("start", "start", {}),
    ("load_thread_context", "load_thread_context", {}),
    ("read_kb", "read_kb", {}),
    ("read_tools", "read_tools", {}),
    ("ai_department_router", "ai_department_router", {}),
    ("ai_recipients_generator", "ai_recipients_generator", {}),
    ("generate_email", "generate_email", {}),
]

NODE_HANDLERS: Dict[str, NodeHandler] = {
    "start": execute_start_node,
    "load_thread_context": execute_load_thread_context_node,
    "read_kb": execute_read_kb_node,
    "read_tools": execute_read_tools_node,
    "ai_department_router": execute_ai_department_router_node,
    "ai_recipients_generator": execute_ai_recipients_generator_node,
    "generate_email": execute_generate_email_node,
    "call_external_tool": execute_call_external_tool_node,
    "save_gmail_draft": execute_save_gmail_draft_node,
    "send_email": execute_send_email_node,
    "stop": execute_stop_node,
}


def build_flow_pipeline(
    agent: Dict[str, Any],
    *,
    flow_nodes: List[Dict[str, Any]] | None = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Return the node pipeline for this agent, including the resolved tail nodes."""
    pipeline = list(MVP_FLOW_PIPELINE)
    reply_action = agent.get("reply_action") or {}
    reply_mode = (
        reply_action.get("mode", REPLY_ACTION_MODE_DRAFT)
        if isinstance(reply_action, dict)
        else REPLY_ACTION_MODE_DRAFT
    )
    if (reply_mode or REPLY_ACTION_MODE_DRAFT).strip().lower() == REPLY_ACTION_MODE_DRAFT:
        pipeline.append(("save_gmail_draft", "save_gmail_draft", {}))
    elif (reply_mode or "").strip().lower() == REPLY_ACTION_MODE_AUTO_SEND:
        pipeline.append(("send_email", "send_email", {}))

    external_tool_config = None
    if flow_nodes:
        external_tool_config = extract_call_external_tool_config(flow_nodes)
    elif (agent.get("flow_id") or "").strip():
        # flow_nodes not passed — caller should load flow when possible
        pass

    if external_tool_config is not None:
        pipeline.append(("call_external_tool", "call_external_tool", external_tool_config))

    pipeline.append(("stop", "stop", {}))
    return pipeline


async def build_flow_pipeline_for_agent(
    agent: Dict[str, Any],
) -> List[Tuple[str, str, Dict[str, Any]]]:
    """Load linked workflow (if any) and build the runtime pipeline."""
    flow_nodes: List[Dict[str, Any]] | None = None
    flow_id = (agent.get("flow_id") or "").strip()
    if flow_id:
        flow = await get_flow_by_id(flow_id)
        if flow:
            flow_nodes = flow.get("nodes") or []
    return build_flow_pipeline(agent, flow_nodes=flow_nodes)


async def queue_reprocess_agent_thread(
    *,
    agent_id: str,
    thread_id: str,
    trigger_message_id: str = "",
    force_reprocess: bool = True,
    message_limit: int = 10,
    run_type: str = RUN_TYPE_REPROCESS,
) -> Dict[str, Any]:
    """
    Validate reprocess inputs and create a queued email-flow-runs document.

    Returns immediately with run_id for polling while the pipeline runs in background.
    """
    normalized_agent_id = agent_id.strip()
    normalized_thread_id = thread_id.strip()

    if not normalized_thread_id:
        return {
            "success": False,
            "status_code": 400,
            "message": "thread_id is required.",
        }

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

    team_id = (agent.get("team_id") or "").strip()
    run_id = generate_run_id()
    context = build_initial_flow_context(
        run_id=run_id,
        agent_id=normalized_agent_id,
        team_id=team_id,
        thread_id=normalized_thread_id,
        trigger_message_id=trigger_message_id.strip(),
        system_prompt=agent.get("system_prompt", "") or "",
        email_format_template=agent.get("email_format_template", "") or "",
    )

    await create_flow_run(
        run_id=run_id,
        agent_id=normalized_agent_id,
        team_id=team_id,
        thread_id=normalized_thread_id,
        trigger_message_id=trigger_message_id.strip(),
        context=context,
        preview=(run_type == RUN_TYPE_PREVIEW),
        run_type=run_type,
        status=FLOW_RUN_STATUS_QUEUED,
    )

    logger.info(
        f"Queued reprocess flow run_id={run_id} agent_id={normalized_agent_id} "
        f"thread_id={normalized_thread_id}"
    )

    return {
        "success": True,
        "status_code": 202,
        "message": "Thread reprocess in progress.",
        "data": {
            "run_id": run_id,
            "status": FLOW_RUN_STATUS_QUEUED,
            "agent_id": normalized_agent_id,
            "thread_id": normalized_thread_id,
            "trigger_message_id": trigger_message_id.strip(),
            "force_reprocess": force_reprocess,
            "message_limit": message_limit,
        },
    }


async def run_reprocess_agent_thread_background(
    *,
    run_id: str,
    agent_id: str,
    thread_id: str,
    trigger_message_id: str = "",
    force_reprocess: bool = True,
    message_limit: int = 10,
    run_type: str = RUN_TYPE_REPROCESS,
) -> None:
    """Background worker wrapper — logs unexpected failures on the flow run."""
    try:
        await run_agent_thread_flow(
            agent_id=agent_id,
            thread_id=thread_id,
            trigger_message_id=trigger_message_id,
            force_reprocess=force_reprocess,
            message_limit=message_limit,
            run_type=run_type,
            existing_run_id=run_id,
        )
    except Exception as exc:
        logger.error(
            f"Background reprocess failed run_id={run_id} thread_id={thread_id}: {exc}",
            exc_info=True,
        )
        await update_flow_run_status(
            run_id,
            status=FLOW_RUN_STATUS_FAILED,
            error=str(exc),
        )
        try:
            agent = await get_email_ai_agent_by_id(agent_id)
            if agent:
                await finalize_thread_ai_status(
                    thread_id=thread_id.strip(),
                    team_id=(agent.get("team_id") or "").strip(),
                    gmail_account_id=(agent.get("gmail_account_id") or "").strip(),
                    flow_run_id=run_id,
                    final_status=FLOW_RUN_STATUS_FAILED,
                    error=str(exc),
                )
        except Exception as finalize_error:
            logger.error(
                f"Failed to finalize thread ai_status run_id={run_id}: {finalize_error}",
                exc_info=True,
            )


async def run_agent_thread_flow(
    *,
    agent_id: str,
    thread_id: str,
    trigger_message_id: str = "",
    force_reprocess: bool = True,
    message_limit: int = 10,
    run_type: str = RUN_TYPE_REPROCESS,
    existing_run_id: str = "",
) -> Dict[str, Any]:
    """
    Execute the configured node pipeline for an agent + thread.

    Used by reprocess API and (later) sync trigger. Always persists logs on email-flow-runs.
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

    team_id = (agent.get("team_id") or "").strip()
    normalized_existing_run_id = (existing_run_id or "").strip()

    if normalized_existing_run_id:
        existing_run = await get_flow_run_by_id(normalized_existing_run_id)
        if not existing_run:
            return {
                "success": False,
                "status_code": 404,
                "message": "Queued flow run not found.",
            }
        run_id = normalized_existing_run_id
        context = existing_run.get("context") or build_initial_flow_context(
            run_id=run_id,
            agent_id=normalized_agent_id,
            team_id=team_id,
            thread_id=normalized_thread_id,
            trigger_message_id=trigger_message_id.strip(),
            system_prompt=agent.get("system_prompt", "") or "",
            email_format_template=agent.get("email_format_template", "") or "",
        )
        await update_flow_run_status(run_id, status=FLOW_RUN_STATUS_RUNNING)
    else:
        run_id = generate_run_id()
        context = build_initial_flow_context(
            run_id=run_id,
            agent_id=normalized_agent_id,
            team_id=team_id,
            thread_id=normalized_thread_id,
            trigger_message_id=trigger_message_id.strip(),
            system_prompt=agent.get("system_prompt", "") or "",
            email_format_template=agent.get("email_format_template", "") or "",
        )

        await create_flow_run(
            run_id=run_id,
            agent_id=normalized_agent_id,
            team_id=team_id,
            thread_id=normalized_thread_id,
            trigger_message_id=trigger_message_id.strip(),
            context=context,
            preview=(run_type == RUN_TYPE_PREVIEW),
            run_type=run_type,
        )

    node_logs: List[Dict[str, Any]] = []
    final_status = FLOW_RUN_STATUS_COMPLETED
    failed_node_id = ""

    flow_pipeline = await build_flow_pipeline_for_agent(agent)

    for node_id, node_type, base_config in flow_pipeline:
        handler = NODE_HANDLERS.get(node_type)
        if not handler:
            return {
                "success": False,
                "status_code": 500,
                "message": f"No handler registered for node type '{node_type}'.",
            }

        node_config = dict(base_config)
        if node_type == "start":
            node_config["force_reprocess"] = force_reprocess
            node_config["message_limit"] = max(message_limit, 10)
        if node_type == "load_thread_context":
            node_config["message_limit"] = message_limit
        if node_type == "read_kb":
            node_config.setdefault("limit", 5)
        if node_type == "read_tools":
            node_config.setdefault("max_tool_calls", EMAIL_TOOLS_DEFAULT_MAX_CALLS)
        if node_type == "call_external_tool":
            node_config.setdefault("max_tool_calls", EMAIL_TOOLS_DEFAULT_MAX_CALLS)

        context, node_log = await handler(context, node_config, agent)
        node_logs.append(node_log)

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

        if node_log["status"] == NODE_LOG_STATUS_SKIPPED and node_type == "start":
            final_status = FLOW_RUN_STATUS_SKIPPED
            failed_node_id = node_id
            break

        if node_log["status"] == NODE_LOG_STATUS_FAILED:
            final_status = FLOW_RUN_STATUS_FAILED
            failed_node_id = node_id
            break

        if node_type == "start" and node_log["status"] == NODE_LOG_STATUS_OK:
            resolved_trigger_id = context.get("trigger_message_id", "")
            if resolved_trigger_id:
                await update_flow_run_trigger_message(run_id, resolved_trigger_id)

    trigger_message_id_resolved = (context.get("trigger_message_id") or "").strip()

    if final_status == FLOW_RUN_STATUS_COMPLETED and trigger_message_id_resolved:
        await set_trigger_message_processing(
            trigger_message_id_resolved,
            flow_run_id=run_id,
            processing_status=MESSAGE_PROCESSING_STATUS_COMPLETED,
        )
    elif final_status == FLOW_RUN_STATUS_FAILED and trigger_message_id_resolved:
        await set_trigger_message_processing(
            trigger_message_id_resolved,
            flow_run_id=run_id,
            processing_status=MESSAGE_PROCESSING_STATUS_FAILED,
        )

    flow_error_message = ""
    if final_status == FLOW_RUN_STATUS_FAILED:
        flow_error_message = next(
            (log.get("error") for log in reversed(node_logs) if log.get("error")),
            "Flow run failed.",
        )

    gmail_account_id = (agent.get("gmail_account_id") or "").strip()
    await finalize_thread_ai_status(
        thread_id=normalized_thread_id,
        team_id=team_id,
        gmail_account_id=gmail_account_id,
        flow_run_id=run_id,
        final_status=final_status,
        error=flow_error_message,
    )

    await update_flow_run_context(
        run_id,
        context=context,
        current_node_id=failed_node_id or flow_pipeline[-1][0],
        status=final_status,
    )

    serialized_logs = serialize_for_json(node_logs)

    if final_status == FLOW_RUN_STATUS_FAILED:
        error_message = flow_error_message or "Flow run failed."
        return {
            "success": False,
            "status_code": 400,
            "message": error_message,
            "data": {
                "run_id": run_id,
                "status": final_status,
                "nodes_executed": [log["node_id"] for log in node_logs],
                "node_logs": serialized_logs,
                "flow_context": serialize_for_json(context),
            },
        }

    if final_status == FLOW_RUN_STATUS_SKIPPED:
        skip_reason = ""
        if node_logs:
            skip_reason = node_logs[-1].get("output", {}).get("skip_reason", "")
        return {
            "success": False,
            "status_code": 409,
            "message": skip_reason or "Flow run skipped.",
            "data": {
                "run_id": run_id,
                "status": final_status,
                "nodes_executed": [log["node_id"] for log in node_logs],
                "node_logs": serialized_logs,
                "flow_context": serialize_for_json(context),
            },
        }

    return {
        "success": True,
        "status_code": 200,
        "message": "Flow run completed successfully.",
        "data": {
            "run_id": run_id,
            "status": final_status,
            "nodes_executed": [log["node_id"] for log in node_logs],
            "node_logs": serialized_logs,
            "flow_context": serialize_for_json(context),
        },
    }
