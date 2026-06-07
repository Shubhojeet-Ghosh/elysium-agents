from fastapi.responses import JSONResponse

from config.email_knowledge_models import (
    CreateEmailKnowledgeRequest,
    DeleteEmailKnowledgeRequest,
    ListTeamEmailKnowledgeRequest,
    QueryEmailKnowledgeRequest,
)
from logging_config import get_logger
from services.email_agent_services.email_knowledge.email_knowledge_query_services import (
    retrieve_relevant_knowledge_chunks,
)
from services.email_agent_services.email_knowledge.email_knowledge_services import (
    create_email_knowledge,
    delete_email_knowledge,
    list_team_email_knowledge,
)

logger = get_logger()


async def create_email_knowledge_controller(request_data: CreateEmailKnowledgeRequest):
    try:
        result = await create_email_knowledge(
            team_id=request_data.team_id,
            title=request_data.title,
            knowledge_text=request_data.knowledge_text,
        )

        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to create knowledge."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "knowledge": result.get("data"),
            },
        )

    except Exception as e:
        logger.error(f"Error in create_email_knowledge_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while creating knowledge.",
            },
        )


async def list_team_email_knowledge_controller(request_data: ListTeamEmailKnowledgeRequest):
    try:
        result = await list_team_email_knowledge(team_id=request_data.team_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to fetch team knowledge."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "team_id": result["data"]["team_id"],
                "count": result["data"]["count"],
                "knowledge_items": result["data"]["knowledge_items"],
            },
        )

    except Exception as e:
        logger.error(f"Error in list_team_email_knowledge_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while fetching team knowledge.",
            },
        )


async def delete_email_knowledge_controller(request_data: DeleteEmailKnowledgeRequest):
    try:
        result = await delete_email_knowledge(knowledge_id=request_data.knowledge_id)
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to delete knowledge."),
                },
            )

        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "knowledge_id": result["data"]["knowledge_id"],
                "team_id": result["data"]["team_id"],
            },
        )

    except Exception as e:
        logger.error(f"Error in delete_email_knowledge_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while deleting knowledge.",
            },
        )


async def query_email_knowledge_controller(request_data: QueryEmailKnowledgeRequest):
    try:
        result = await retrieve_relevant_knowledge_chunks(
            knowledge_id=request_data.knowledge_id,
            query=request_data.query,
        )
        status_code = result.get("status_code", 200 if result.get("success") else 400)

        if not result.get("success"):
            return JSONResponse(
                status_code=status_code,
                content={
                    "success": False,
                    "message": result.get("message", "Failed to retrieve relevant chunks."),
                },
            )

        data = result.get("data", {})
        return JSONResponse(
            status_code=status_code,
            content={
                "success": True,
                "message": result.get("message"),
                "knowledge_id": data.get("knowledge_id"),
                "team_id": data.get("team_id"),
                "title": data.get("title"),
                "query": data.get("query"),
                "chunk_count": data.get("chunk_count"),
                "chunks": data.get("chunks"),
            },
        )

    except Exception as e:
        logger.error(f"Error in query_email_knowledge_controller: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An error occurred while retrieving relevant chunks.",
            },
        )
