from fastapi import APIRouter, BackgroundTasks

from config.email_flow_models import (
    GetFlowRunRequest,
    ListThreadFlowRunsRequest,
    PreviewLoadThreadContextRequest,
    ReprocessAgentThreadRequest,
)
from controllers.email_agent_controller_files.email_flow_controllers import (
    get_flow_run_controller,
    list_thread_flow_runs_controller,
    preview_load_thread_context_controller,
    reprocess_agent_thread_controller,
)

email_flow_router = APIRouter(
    prefix="/email-flows",
    tags=["Email Flows (test)"],
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
