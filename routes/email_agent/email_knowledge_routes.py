from fastapi import APIRouter

from config.email_knowledge_models import (
    CreateEmailKnowledgeRequest,
    DeleteEmailKnowledgeRequest,
    ListTeamEmailKnowledgeRequest,
    QueryEmailKnowledgeRequest,
)
from controllers.email_agent_controller_files.email_knowledge_controllers import (
    create_email_knowledge_controller,
    delete_email_knowledge_controller,
    list_team_email_knowledge_controller,
    query_email_knowledge_controller,
)

email_knowledge_router = APIRouter(
    prefix="/email-knowledge",
    tags=["Email Knowledge"],
)


@email_knowledge_router.post("/v1/create")
async def create_email_knowledge_route(request_data: CreateEmailKnowledgeRequest):
    """Chunk knowledge text, embed, store in Qdrant, save metadata in Mongo."""
    return await create_email_knowledge_controller(request_data)


@email_knowledge_router.post("/v1/list-team-knowledge")
async def list_team_email_knowledge_route(request_data: ListTeamEmailKnowledgeRequest):
    """List all knowledge metadata for a team. Public — no JWT required."""
    return await list_team_email_knowledge_controller(request_data)


@email_knowledge_router.post("/v1/delete")
async def delete_email_knowledge_route(request_data: DeleteEmailKnowledgeRequest):
    """Delete knowledge by knowledge_id from Qdrant and Mongo."""
    return await delete_email_knowledge_controller(request_data)


@email_knowledge_router.post("/v1/query")
async def query_email_knowledge_route(request_data: QueryEmailKnowledgeRequest):
    """Test endpoint: retrieve top 5 relevant chunks for a query. Public — no JWT required."""
    return await query_email_knowledge_controller(request_data)
