"""Team knowledge item HTTP controllers."""

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from config.atlas_kb_item_models import (
    CreateCustomTextRequest,
    CreateFileRequest,
    CreateQaPairRequest,
    CreateUrlsRequest,
    FinalizeFileRequest,
    GenerateKbPresignedUrlsRequest,
    KbIdRequest,
    PaginationRequest,
    ReindexItemRequest,
    SearchKbItemsRequest,
    UpdateCustomTextRequest,
    UpdateQaPairRequest,
    UpdateUrlRequest,
)
from config.kb_item_constants import SOURCE_TYPE_FILE, SOURCE_TYPE_URL
from logging_config import get_logger
from services.elysium_atlas_services.kb_item.kb_index_service import index_kb_item
from services.elysium_atlas_services.kb_item.kb_item_services import (
    create_custom_text_for_team,
    create_file_item_for_team,
    create_qa_pair_for_team,
    create_url_items_for_team,
    delete_custom_text_item,
    delete_file_item,
    delete_qa_pair_item,
    delete_url_item,
    finalize_file_item,
    generate_file_presigned_urls,
    get_custom_text_item,
    get_file_item,
    get_kb_item_team_id,
    get_qa_pair_item,
    get_url_item,
    list_custom_texts_for_team,
    list_files_for_team,
    list_qa_pairs_for_team,
    list_response_key_for_source_type,
    list_urls_for_team,
    reindex_kb_item,
    search_kb_items_for_team,
    update_custom_text_item,
    update_qa_pair_item,
    update_url_item,
)
from services.elysium_atlas_services.team_auth_services import (
    can_user_modify_team_agents,
    is_user_member_of_team,
    parse_session_team_context,
)

logger = get_logger()


def _list_response(message: str, key: str, result: dict) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message,
            key: result["data"],
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "total_pages": result["total_pages"],
            "has_next": result["has_next"],
            "has_prev": result["has_prev"],
        },
    )


async def _require_team_member(user_data: dict):
    if user_data is None or user_data.get("success") is False:
        return JSONResponse(status_code=401, content={"success": False, "message": "Unauthorized"})
    ctx = parse_session_team_context(user_data)
    if ctx is None:
        return JSONResponse(status_code=403, content={"success": False, "message": "No team context."})
    user_id, team_id = ctx
    if not await is_user_member_of_team(user_id, team_id):
        return JSONResponse(status_code=403, content={"success": False, "message": "Not a team member."})
    return user_id, team_id


async def _require_team_admin(user_data: dict):
    member = await _require_team_member(user_data)
    if isinstance(member, JSONResponse):
        return member
    user_id, team_id = member
    if not await can_user_modify_team_agents(user_id, team_id):
        return JSONResponse(status_code=403, content={"success": False, "message": "Admin access required."})
    return user_id, team_id


async def _require_kb_read(user_data: dict, kb_id: str, source_type: str):
    member = await _require_team_member(user_data)
    if isinstance(member, JSONResponse):
        return member
    user_id, team_id = member
    item_team = await get_kb_item_team_id(kb_id, source_type)
    if not item_team:
        return JSONResponse(status_code=404, content={"success": False, "message": "Item not found."})
    if item_team != team_id:
        return JSONResponse(status_code=403, content={"success": False, "message": "Forbidden."})
    return user_id, team_id


def _schedule_index(background_tasks: BackgroundTasks, kb_id: str, source_type: str) -> None:
    background_tasks.add_task(index_kb_item, kb_id, source_type)


async def search_kb_items_controller(body: SearchKbItemsRequest, user: dict) -> JSONResponse:
    auth = await _require_team_member(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    result = await search_kb_items_for_team(
        team_id,
        body.source_type,
        body.search_query,
        body.page,
        body.limit,
    )
    items_key = list_response_key_for_source_type(body.source_type)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Search completed successfully.",
            "source_type": body.source_type,
            "search_query": body.search_query,
            items_key: result["data"],
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "total_pages": result["total_pages"],
            "has_next": result["has_next"],
            "has_prev": result["has_prev"],
        },
    )


# --- URLs ---


async def list_urls_controller(body: PaginationRequest, user: dict) -> JSONResponse:
    auth = await _require_team_member(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    result = await list_urls_for_team(team_id, body.page, body.limit)
    return _list_response("URLs fetched successfully.", "urls", result)


async def get_url_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_kb_read(user, body.kb_id, SOURCE_TYPE_URL)
    if isinstance(auth, JSONResponse):
        return auth
    item = await get_url_item(body.kb_id)
    return JSONResponse(status_code=200, content={"success": True, "item": item})


async def create_urls_controller(
    body: CreateUrlsRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    user_id, team_id = auth
    items, err = await create_url_items_for_team(team_id, user_id, body.urls)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    for item in items or []:
        _schedule_index(background_tasks, item["kb_id"], SOURCE_TYPE_URL)
    return JSONResponse(
        status_code=200,
        content={"success": True, "message": "URL items created. Indexing started.", "items": items},
    )


async def update_url_controller(
    body: UpdateUrlRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    payload, err = await update_url_item(body.kb_id, team_id, body.url)
    if err:
        return JSONResponse(status_code=404 if "not found" in err.lower() else 400, content={"success": False, "message": err})
    _schedule_index(background_tasks, body.kb_id, SOURCE_TYPE_URL)
    return JSONResponse(status_code=200, content={"success": True, "message": "URL updated. Re-indexing started.", **payload})


async def delete_url_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    if not await delete_url_item(body.kb_id, team_id):
        return JSONResponse(status_code=404, content={"success": False, "message": "URL item not found."})
    return JSONResponse(status_code=200, content={"success": True, "message": "URL item deleted."})


# --- Files ---


async def list_files_controller(body: PaginationRequest, user: dict) -> JSONResponse:
    auth = await _require_team_member(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    result = await list_files_for_team(team_id, body.page, body.limit)
    return _list_response("Files fetched successfully.", "files", result)


async def get_file_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_kb_read(user, body.kb_id, SOURCE_TYPE_FILE)
    if isinstance(auth, JSONResponse):
        return auth
    item = await get_file_item(body.kb_id)
    return JSONResponse(status_code=200, content={"success": True, "item": item})


async def create_file_controller(body: CreateFileRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    user_id, team_id = auth
    payload, err = await create_file_item_for_team(team_id, user_id, body.file_name)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    return JSONResponse(status_code=200, content={"success": True, "message": "File item created.", **payload})


async def generate_presigned_urls_controller(body: GenerateKbPresignedUrlsRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    files = [{"file_name": f.file_name, "filetype": f.filetype} for f in body.files]
    urls, err = await generate_file_presigned_urls(team_id, body.kb_id, files)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    return JSONResponse(status_code=200, content={"success": True, "presigned_urls": urls})


async def finalize_file_controller(
    body: FinalizeFileRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    payload, err = await finalize_file_item(team_id, body.kb_id, body.file_key)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    _schedule_index(background_tasks, body.kb_id, SOURCE_TYPE_FILE)
    return JSONResponse(status_code=200, content={"success": True, "message": "File finalized. Indexing started.", **payload})


async def delete_file_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    if not await delete_file_item(body.kb_id, team_id):
        return JSONResponse(status_code=404, content={"success": False, "message": "File item not found."})
    return JSONResponse(status_code=200, content={"success": True, "message": "File item deleted."})


# --- Custom text ---


async def list_custom_texts_controller(body: PaginationRequest, user: dict) -> JSONResponse:
    auth = await _require_team_member(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    result = await list_custom_texts_for_team(team_id, body.page, body.limit)
    return _list_response("Custom texts fetched successfully.", "custom_texts", result)


async def get_custom_text_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_kb_read(user, body.kb_id, "custom_text")
    if isinstance(auth, JSONResponse):
        return auth
    item = await get_custom_text_item(body.kb_id)
    return JSONResponse(status_code=200, content={"success": True, "item": item})


async def create_custom_text_controller(
    body: CreateCustomTextRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    user_id, team_id = auth
    payload, err = await create_custom_text_for_team(team_id, user_id, body.custom_text_alias, body.content)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    _schedule_index(background_tasks, payload["kb_id"], "custom_text")
    return JSONResponse(status_code=200, content={"success": True, "message": "Custom text created. Indexing started.", **payload})


async def update_custom_text_controller(
    body: UpdateCustomTextRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    payload, err = await update_custom_text_item(body.kb_id, team_id, body.custom_text_alias, body.content)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    _schedule_index(background_tasks, body.kb_id, "custom_text")
    return JSONResponse(status_code=200, content={"success": True, "message": "Custom text updated. Re-indexing started.", **payload})


async def delete_custom_text_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    if not await delete_custom_text_item(body.kb_id, team_id):
        return JSONResponse(status_code=404, content={"success": False, "message": "Custom text not found."})
    return JSONResponse(status_code=200, content={"success": True, "message": "Custom text deleted."})


# --- Q&A ---


async def list_qa_pairs_controller(body: PaginationRequest, user: dict) -> JSONResponse:
    auth = await _require_team_member(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    result = await list_qa_pairs_for_team(team_id, body.page, body.limit)
    return _list_response("Q&A pairs fetched successfully.", "qa_pairs", result)


async def get_qa_pair_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_kb_read(user, body.kb_id, "qa_pair")
    if isinstance(auth, JSONResponse):
        return auth
    item = await get_qa_pair_item(body.kb_id)
    return JSONResponse(status_code=200, content={"success": True, "item": item})


async def create_qa_pair_controller(
    body: CreateQaPairRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    user_id, team_id = auth
    payload, err = await create_qa_pair_for_team(team_id, user_id, body.qna_alias, body.question, body.answer)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    _schedule_index(background_tasks, payload["kb_id"], "qa_pair")
    return JSONResponse(status_code=200, content={"success": True, "message": "Q&A created. Indexing started.", **payload})


async def update_qa_pair_controller(
    body: UpdateQaPairRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    payload, err = await update_qa_pair_item(body.kb_id, team_id, body.qna_alias, body.question, body.answer)
    if err:
        return JSONResponse(status_code=400, content={"success": False, "message": err})
    _schedule_index(background_tasks, body.kb_id, "qa_pair")
    return JSONResponse(status_code=200, content={"success": True, "message": "Q&A updated. Re-indexing started.", **payload})


async def delete_qa_pair_controller(body: KbIdRequest, user: dict) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    if not await delete_qa_pair_item(body.kb_id, team_id):
        return JSONResponse(status_code=404, content={"success": False, "message": "Q&A item not found."})
    return JSONResponse(status_code=200, content={"success": True, "message": "Q&A item deleted."})


# --- Reindex ---


async def reindex_item_controller(
    body: ReindexItemRequest, user: dict, background_tasks: BackgroundTasks
) -> JSONResponse:
    auth = await _require_team_admin(user)
    if isinstance(auth, JSONResponse):
        return auth
    _, team_id = auth
    ok, err = await reindex_kb_item(body.kb_id, team_id, body.source_type)
    if not ok:
        return JSONResponse(status_code=404, content={"success": False, "message": err or "Item not found."})
    _schedule_index(background_tasks, body.kb_id, body.source_type)
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "Re-indexing started.",
            "kb_id": body.kb_id,
            "status": "indexing",
        },
    )
