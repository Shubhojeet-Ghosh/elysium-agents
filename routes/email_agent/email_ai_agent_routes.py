from fastapi import APIRouter, BackgroundTasks, Depends

from config.email_ai_agent_models import (
    CreateEmailAiAgentRequest,
    GetEmailThreadRequest,
    ListTeamEmailAiAgentsRequest,
    ListTeamEmailThreadsRequest,
    TriggerAgentSyncRequest,
)
from controllers.email_agent_controller_files.email_ai_agent_controllers import (
    create_email_ai_agent_controller,
    get_email_thread_controller,
    list_team_email_ai_agents_controller,
    list_team_email_threads_controller,
    trigger_agent_sync_controller,
)
from middlewares.jwt_middleware import authorize_user

email_ai_agent_router = APIRouter(
    prefix="/email-ai-agents",
    tags=["Email AI Agents"],
)


@email_ai_agent_router.post("/v1/create")
async def create_email_ai_agent_route(
    request_data: CreateEmailAiAgentRequest,
    user: dict = Depends(authorize_user),
):
    """Create an email AI agent with a name and linked Gmail inbox."""
    return await create_email_ai_agent_controller(request_data, user)


@email_ai_agent_router.post("/v1/list-team-agents")
async def list_team_email_ai_agents_route(request_data: ListTeamEmailAiAgentsRequest):
    """List all email AI agents for a team."""
    return await list_team_email_ai_agents_controller(request_data)


@email_ai_agent_router.post("/v1/trigger-sync")
async def trigger_agent_sync_route(
    request_data: TriggerAgentSyncRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(authorize_user),
):
    """Start a background sync of Gmail threads for an agent (inbound + outbound)."""
    return await trigger_agent_sync_controller(request_data, user, background_tasks)


@email_ai_agent_router.post("/v1/list-team-threads")
async def list_team_email_threads_route(
    request_data: ListTeamEmailThreadsRequest,
    user: dict = Depends(authorize_user),
):
    """List email thread summaries for a team (snippet only)."""
    return await list_team_email_threads_controller(request_data, user)


@email_ai_agent_router.post("/v1/get-thread")
async def get_email_thread_route(
    request_data: GetEmailThreadRequest,
    user: dict = Depends(authorize_user),
):
    """Get a full email thread with complete message bodies."""
    return await get_email_thread_controller(request_data, user)
