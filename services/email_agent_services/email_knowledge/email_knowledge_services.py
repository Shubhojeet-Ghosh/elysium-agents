import uuid
from typing import Any, Dict

from logging_config import get_logger
from services.email_agent_services.email_knowledge.email_knowledge_mongo_services import (
    delete_knowledge_metadata,
    get_knowledge_by_id,
    insert_knowledge_metadata,
    list_team_knowledge_metadata,
)
from services.email_agent_services.email_knowledge.email_knowledge_qdrant_services import (
    delete_knowledge_from_qdrant,
    index_knowledge_text_in_qdrant,
)

logger = get_logger()


async def create_email_knowledge(
    team_id: str,
    title: str,
    knowledge_text: str,
) -> Dict[str, Any]:
    """Create team knowledge: chunk, embed, store in Qdrant, save metadata in Mongo."""
    normalized_team_id = team_id.strip()
    normalized_title = title.strip()
    normalized_text = knowledge_text.strip()

    if not normalized_text:
        return {
            "success": False,
            "status_code": 400,
            "message": "knowledge_text cannot be empty.",
        }

    knowledge_id = str(uuid.uuid4())

    try:
        qdrant_result = await index_knowledge_text_in_qdrant(
            team_id=normalized_team_id,
            knowledge_id=knowledge_id,
            knowledge_text=normalized_text,
        )

        if not qdrant_result.get("success"):
            errors = qdrant_result.get("errors", [])
            return {
                "success": False,
                "status_code": 500,
                "message": errors[0] if errors else "Failed to index knowledge in Qdrant.",
            }

        knowledge_data = await insert_knowledge_metadata(
            knowledge_id=knowledge_id,
            team_id=normalized_team_id,
            title=normalized_title,
            chunk_count=qdrant_result["total_chunks"],
            char_count=len(normalized_text),
        )

        logger.info(
            f"Created email knowledge {knowledge_id} for team {normalized_team_id}: "
            f"{qdrant_result['total_chunks']} chunks"
        )

        return {
            "success": True,
            "status_code": 201,
            "message": "Knowledge indexed successfully.",
            "data": knowledge_data,
        }

    except Exception as e:
        logger.error(f"Failed to create email knowledge: {e}", exc_info=True)
        await delete_knowledge_from_qdrant(normalized_team_id, knowledge_id)
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to create knowledge.",
        }


async def list_team_email_knowledge(team_id: str) -> Dict[str, Any]:
    """List all knowledge metadata for a team."""
    normalized_team_id = team_id.strip()

    try:
        knowledge_items = await list_team_knowledge_metadata(normalized_team_id)

        logger.info(
            f"Listed {len(knowledge_items)} knowledge items for team {normalized_team_id}"
        )

        return {
            "success": True,
            "status_code": 200,
            "message": "Team knowledge fetched successfully.",
            "data": {
                "team_id": normalized_team_id,
                "count": len(knowledge_items),
                "knowledge_items": knowledge_items,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to list knowledge for team {normalized_team_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to fetch team knowledge.",
        }


async def delete_email_knowledge(knowledge_id: str) -> Dict[str, Any]:
    """Delete knowledge by knowledge_id from both Qdrant and Mongo."""
    normalized_knowledge_id = knowledge_id.strip()

    try:
        knowledge_doc = await get_knowledge_by_id(normalized_knowledge_id)
        if not knowledge_doc:
            return {
                "success": False,
                "status_code": 404,
                "message": "Knowledge not found.",
            }

        team_id = knowledge_doc.get("team_id", "")

        qdrant_result = await delete_knowledge_from_qdrant(team_id, normalized_knowledge_id)
        if not qdrant_result.get("success"):
            errors = qdrant_result.get("errors", [])
            return {
                "success": False,
                "status_code": 500,
                "message": errors[0] if errors else "Failed to delete knowledge from Qdrant.",
            }

        deleted = await delete_knowledge_metadata(normalized_knowledge_id)
        if not deleted:
            return {
                "success": False,
                "status_code": 500,
                "message": "Failed to delete knowledge metadata.",
            }

        logger.info(f"Deleted email knowledge {normalized_knowledge_id} for team {team_id}")

        return {
            "success": True,
            "status_code": 200,
            "message": "Knowledge deleted successfully.",
            "data": {
                "knowledge_id": normalized_knowledge_id,
                "team_id": team_id,
            },
        }

    except Exception as e:
        logger.error(
            f"Failed to delete knowledge {normalized_knowledge_id}: {e}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Failed to delete knowledge.",
        }
