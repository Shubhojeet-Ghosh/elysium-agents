"""List KB items attached to an agent (by source type)."""

from fastapi.responses import JSONResponse

from config.atlas_agent_models import ListAgentAttachedKbItemsRequest
from config.kb_item_constants import (
    SOURCE_TYPE_CUSTOM_TEXT,
    SOURCE_TYPE_FILE,
    SOURCE_TYPE_QA_PAIR,
    SOURCE_TYPE_URL,
)
from logging_config import get_logger
from services.elysium_atlas_services.kb_item.kb_attachment_service import list_agent_attached_kb_items
from services.elysium_atlas_services.kb_item.kb_item_services import list_response_key_for_source_type
from services.elysium_atlas_services.team_auth_services import can_user_read_agent

logger = get_logger()

_LIST_MESSAGES: dict[str, str] = {
    SOURCE_TYPE_URL: "Attached URLs fetched successfully.",
    SOURCE_TYPE_FILE: "Attached files fetched successfully.",
    SOURCE_TYPE_CUSTOM_TEXT: "Attached custom texts fetched successfully.",
    SOURCE_TYPE_QA_PAIR: "Attached Q&A pairs fetched successfully.",
}


async def _require_agent_read(user_data: dict, agent_id: str) -> str | JSONResponse:
    if user_data is None or user_data.get("success") is False:
        return JSONResponse(
            status_code=401,
            content={"success": False, "message": (user_data or {}).get("message", "Unauthorized")},
        )

    user_id = user_data.get("user_id")
    if not user_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "user_id is required."})
    if not agent_id:
        return JSONResponse(status_code=400, content={"success": False, "message": "agent_id is required."})
    if not await can_user_read_agent(str(user_id), agent_id):
        return JSONResponse(
            status_code=403,
            content={"success": False, "message": "You are not authorized to access this agent."},
        )
    return str(user_id)


async def _list_attached_kb_items_controller(
    body: ListAgentAttachedKbItemsRequest,
    user: dict,
    source_type: str,
) -> JSONResponse:
    auth = await _require_agent_read(user, body.agent_id)
    if isinstance(auth, JSONResponse):
        return auth

    logger.info(
        f"Listing attached {source_type} items for agent_id={body.agent_id}, "
        f"page={body.page}, limit={body.limit}"
    )

    result = await list_agent_attached_kb_items(
        body.agent_id,
        source_type,
        body.page,
        body.limit,
    )
    items_key = list_response_key_for_source_type(source_type)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": _LIST_MESSAGES[source_type],
            "agent_id": body.agent_id,
            items_key: result["data"],
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "total_pages": result["total_pages"],
            "has_next": result["has_next"],
            "has_prev": result["has_prev"],
        },
    )


async def list_attached_urls_controller(body: ListAgentAttachedKbItemsRequest, user: dict) -> JSONResponse:
    return await _list_attached_kb_items_controller(body, user, SOURCE_TYPE_URL)


async def list_attached_files_controller(body: ListAgentAttachedKbItemsRequest, user: dict) -> JSONResponse:
    return await _list_attached_kb_items_controller(body, user, SOURCE_TYPE_FILE)


async def list_attached_custom_texts_controller(body: ListAgentAttachedKbItemsRequest, user: dict) -> JSONResponse:
    return await _list_attached_kb_items_controller(body, user, SOURCE_TYPE_CUSTOM_TEXT)


async def list_attached_qa_pairs_controller(body: ListAgentAttachedKbItemsRequest, user: dict) -> JSONResponse:
    return await _list_attached_kb_items_controller(body, user, SOURCE_TYPE_QA_PAIR)
