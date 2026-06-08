from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from config.email_flow_models import (
    CreateEmailFlowRequest,
    GetFlowForAgentRequest,
    GetFlowRequest,
    GetFlowRunRequest,
    ListTeamEmailFlowsRequest,
    ListThreadFlowRunsRequest,
    PreviewLoadThreadContextRequest,
    ReprocessAgentThreadRequest,
    UpdateEmailFlowRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_edit_services import (
    create_team_email_flow,
    update_team_email_flow,
)
from services.email_agent_services.email_flows.email_flow_engine import (
    queue_reprocess_agent_thread,
    run_reprocess_agent_thread_background,
)
from services.email_agent_services.email_flows.email_flow_mongo_services import (
    get_flow_detail,
    get_flow_for_agent_detail,
    list_team_email_flows,
)
from services.email_agent_services.email_flows.email_flow_preview_services import (
    get_flow_run_detail,
    list_thread_flow_runs,
    preview_load_thread_context,
)

logger = get_logger()


def _unauthorized_response(user_data: dict) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={
            "success": False,
            "message": user_data.get("message", "Unauthorized"),
        },
    )


def _get_authenticated_team(user_data: dict) -> dict | JSONResponse:
    if not user_data or user_data.get("success") is False:
        return _unauthorized_response(user_data)

    team_id = user_data.get("team_id")
    if not team_id:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": "Invalid token: team_id missing."},
        )

    return {"team_id": team_id.strip()}


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


async def list_team_email_flows_controller(
    request_data: ListTeamEmailFlowsRequest,
    user_data: dict,
):
    try:
        auth = _get_authenticated_team(user_data)
        if isinstance(auth, JSONResponse):
            return auth

        token_team_id = auth["team_id"]
        if request_data.team_id.strip() != token_team_id:
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "message": "team_id does not match your authenticated team.",
                },
            )

        result = await list_team_email_flows(token_team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to list email flows."),
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
        logger.error(f"Error in list_team_email_flows_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while listing email flows."},
        )


async def get_flow_for_agent_controller(
    request_data: GetFlowForAgentRequest,
    user_data: dict,
):
    try:
        auth = _get_authenticated_team(user_data)
        if isinstance(auth, JSONResponse):
            return auth

        result = await get_flow_for_agent_detail(
            agent_id=request_data.agent_id,
            team_id=auth["team_id"],
        )
        status_code = result.get("status_code", 200 if result.get("success") else 404)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email flow."),
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
        logger.error(f"Error in get_flow_for_agent_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the email flow."},
        )


async def get_flow_controller(
    request_data: GetFlowRequest,
    user_data: dict,
):
    try:
        auth = _get_authenticated_team(user_data)
        if isinstance(auth, JSONResponse):
            return auth

        result = await get_flow_detail(
            flow_id=request_data.flow_id,
            team_id=auth["team_id"],
        )
        status_code = result.get("status_code", 200 if result.get("success") else 404)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch email flow."),
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
        logger.error(f"Error in get_flow_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while fetching the email flow."},
        )


async def create_email_flow_controller(
    request_data: CreateEmailFlowRequest,
    user_data: dict,
):
    try:
        auth = _get_authenticated_team(user_data)
        if isinstance(auth, JSONResponse):
            return auth

        token_team_id = auth["team_id"]
        if request_data.team_id.strip() != token_team_id:
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "message": "team_id does not match your authenticated team.",
                },
            )

        result = await create_team_email_flow(
            team_id=token_team_id,
            name=request_data.name,
            description=request_data.description,
        )
        status_code = result.get("status_code", 201 if result.get("success") else 400)

        if not result.get("success"):
            body = {
                "success": False,
                "message": result.get("message", "Failed to create email workflow."),
            }
            if result.get("data") is not None:
                body["data"] = result.get("data")
            return JSONResponse(status_code=status_code, content=body)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_flow_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while creating the email workflow."},
        )


async def update_email_flow_controller(
    request_data: UpdateEmailFlowRequest,
    user_data: dict,
):
    try:
        auth = _get_authenticated_team(user_data)
        if isinstance(auth, JSONResponse):
            return auth

        nodes_payload = [node.model_dump() for node in request_data.nodes]

        result = await update_team_email_flow(
            team_id=auth["team_id"],
            flow_id=request_data.flow_id,
            name=request_data.name,
            description=request_data.description,
            nodes=nodes_payload,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            body = {
                "success": False,
                "message": result.get("message", "Failed to update email workflow."),
            }
            if result.get("data") is not None:
                body["data"] = result.get("data")
            return JSONResponse(status_code=status_code, content=body)

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "data": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in update_email_flow_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while updating the email workflow."},
        )
