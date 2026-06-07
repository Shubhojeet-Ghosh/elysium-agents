from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from config.email_flow_models import (
    GetFlowRunRequest,
    ListThreadFlowRunsRequest,
    PreviewLoadThreadContextRequest,
    ReprocessAgentThreadRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_engine import (
    queue_reprocess_agent_thread,
    run_reprocess_agent_thread_background,
)
from services.email_agent_services.email_flows.email_flow_preview_services import (
    get_flow_run_detail,
    list_thread_flow_runs,
    preview_load_thread_context,
)

logger = get_logger()


async def preview_load_thread_context_controller(
    request_data: PreviewLoadThreadContextRequest,
):
    """Test-only controller — production uses preview_load_thread_context() service directly."""
    try:
        result = await preview_load_thread_context(
            agent_id=request_data.agent_id,
            thread_id=request_data.thread_id,
            trigger_message_id=request_data.trigger_message_id,
            persist_run_log=request_data.persist_run_log,
            message_limit=request_data.message_limit,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)
        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to preview load thread context."),
                    "data": result.get("data"),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in preview_load_thread_context_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while previewing load thread context.",
            },
        )


async def get_flow_run_controller(request_data: GetFlowRunRequest):
    """Test-only controller — production uses get_flow_run_detail() service directly."""
    try:
        result = await get_flow_run_detail(request_data.run_id)
        status_code = result.get("status_code", 200 if result.get("success") else 404)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Flow run not found."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result["data"],
            },
        )

    except Exception as e:
        logger.error(f"Error in get_flow_run_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the flow run."},
        )


async def reprocess_agent_thread_controller(
    request_data: ReprocessAgentThreadRequest,
    background_tasks: BackgroundTasks,
):
    """Test-only — queues the flow pipeline and returns immediately."""
    try:
        queue_result = await queue_reprocess_agent_thread(
            agent_id=request_data.agent_id,
            thread_id=request_data.thread_id,
            trigger_message_id=request_data.trigger_message_id,
            force_reprocess=request_data.force_reprocess,
            message_limit=request_data.message_limit,
        )

        status_code = queue_result.get("status_code", 202 if queue_result.get("success") else 400)
        if not queue_result.get("success"):
            body = {
                "success": False,
                "message": queue_result.get("message"),
            }
            if queue_result.get("data") is not None:
                body["data"] = queue_result.get("data")
            return JSONResponse(status_code=status_code, content=body)

        run_id = queue_result["data"]["run_id"]
        background_tasks.add_task(
            run_reprocess_agent_thread_background,
            run_id=run_id,
            agent_id=request_data.agent_id,
            thread_id=request_data.thread_id,
            trigger_message_id=request_data.trigger_message_id,
            force_reprocess=request_data.force_reprocess,
            message_limit=request_data.message_limit,
        )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": queue_result.get("message"),
                "data": {
                    **queue_result["data"],
                    "poll_run_endpoint": "/elysium-agents/email-flows/v1/get-run",
                },
            },
        )

    except Exception as e:
        logger.error(f"Error in reprocess_agent_thread_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while queueing the thread reprocess.",
            },
        )


async def list_thread_flow_runs_controller(request_data: ListThreadFlowRunsRequest):
    """Test-only controller — production uses list_thread_flow_runs() service directly."""
    try:
        result = await list_thread_flow_runs(
            team_id=request_data.team_id,
            thread_id=request_data.thread_id,
            limit=request_data.limit,
        )
        status_code = result.get("status_code", 200)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in list_thread_flow_runs_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while listing flow runs."},
        )
