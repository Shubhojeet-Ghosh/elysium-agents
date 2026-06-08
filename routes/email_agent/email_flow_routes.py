from fastapi import APIRouter, BackgroundTasks, Depends

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
from controllers.email_agent_controller_files.email_flow_controllers import (
    create_email_flow_controller,
    get_flow_controller,
    get_flow_for_agent_controller,
    get_flow_run_controller,
    list_team_email_flows_controller,
    list_thread_flow_runs_controller,
    preview_load_thread_context_controller,
    reprocess_agent_thread_controller,
    update_email_flow_controller,
)
from middlewares.jwt_middleware import authorize_user

email_flow_router = APIRouter(
    prefix="/email-flows",
    tags=["Email Flows"],
)


@email_flow_router.post("/v1/reprocess-thread")
async def reprocess_agent_thread_route(
    request_data: ReprocessAgentThreadRequest,
    background_tasks: BackgroundTasks,
):
    """
    **Test only — public, no JWT.**

    Queue a full flow reprocess on an existing thread (fire-and-forget).
    Returns immediately with run_id — poll GET /v1/get-run for progress.
    """
    return await reprocess_agent_thread_controller(request_data, background_tasks)


@email_flow_router.post("/v1/preview-load-thread-context")
async def preview_load_thread_context_route(
    request_data: PreviewLoadThreadContextRequest,
):
    """
    **Test only — public, no JWT.**

    Thin HTTP wrapper around preview_load_thread_context() service.
    Production runs the same service from sync → run_flow, not this route.
    """
    return await preview_load_thread_context_controller(request_data)


@email_flow_router.post("/v1/get-run")
async def get_flow_run_route(request_data: GetFlowRunRequest):
    """
    **Test only — public, no JWT.**

    Inspect email-flow-runs logs while developing node handlers.
    """
    return await get_flow_run_controller(request_data)


@email_flow_router.post("/v1/list-thread-runs")
async def list_thread_flow_runs_route(request_data: ListThreadFlowRunsRequest):
    """
    **Test only — public, no JWT.**

    List preview/production flow runs for a thread.
    """
    return await list_thread_flow_runs_controller(request_data)


@email_flow_router.post("/v1/list-team-flows")
async def list_team_email_flows_route(
    request_data: ListTeamEmailFlowsRequest,
    user: dict = Depends(authorize_user),
):
    """List workflow summaries for a team (email flows page)."""
    return await list_team_email_flows_controller(request_data, user)


@email_flow_router.post("/v1/create")
async def create_email_flow_route(
    request_data: CreateEmailFlowRequest,
    user: dict = Depends(authorize_user),
):
    """Create a new custom team workflow with a minimal valid scaffold graph."""
    return await create_email_flow_controller(request_data, user)


@email_flow_router.post("/v1/update")
async def update_email_flow_route(
    request_data: UpdateEmailFlowRequest,
    user: dict = Depends(authorize_user),
):
    """Save workflow name and/or graph. Validates structure and syncs linked agent config."""
    return await update_email_flow_controller(request_data, user)


@email_flow_router.post("/v1/get-flow")
async def get_flow_route(
    request_data: GetFlowRequest,
    user: dict = Depends(authorize_user),
):
    """Get a workflow by flow_id — full graph JSON for the canvas (use when clicking a flow card)."""
    return await get_flow_controller(request_data, user)


@email_flow_router.post("/v1/get-flow-for-agent")
async def get_flow_for_agent_route(
    request_data: GetFlowForAgentRequest,
    user: dict = Depends(authorize_user),
):
    """Get the workflow currently linked to an email AI agent (hydrated for @xyflow/react)."""
    return await get_flow_for_agent_controller(request_data, user)
