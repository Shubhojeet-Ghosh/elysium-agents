from fastapi import APIRouter, BackgroundTasks, Depends

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
from controllers.elysium_atlas_controller_files.atlas_kb_item_controllers import (
    create_custom_text_controller,
    create_file_controller,
    create_qa_pair_controller,
    create_urls_controller,
    delete_custom_text_controller,
    delete_file_controller,
    delete_qa_pair_controller,
    delete_url_controller,
    finalize_file_controller,
    generate_presigned_urls_controller,
    get_custom_text_controller,
    get_file_controller,
    get_qa_pair_controller,
    get_url_controller,
    list_custom_texts_controller,
    list_files_controller,
    list_qa_pairs_controller,
    list_urls_controller,
    reindex_item_controller,
    search_kb_items_controller,
    update_custom_text_controller,
    update_qa_pair_controller,
    update_url_controller,
)
from middlewares.jwt_middleware import authorize_user

atlas_kb_items_router = APIRouter(prefix="/elysium-atlas/kb-items", tags=["Elysium Atlas - Knowledge Items"])


@atlas_kb_items_router.post("/v1/reindex-item")
async def reindex_item_route(
    body: ReindexItemRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await reindex_item_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/search-items")
async def search_kb_items_route(body: SearchKbItemsRequest, user: dict = Depends(authorize_user)):
    return await search_kb_items_controller(body, user)


@atlas_kb_items_router.post("/v1/list-urls")
async def list_urls_route(body: PaginationRequest, user: dict = Depends(authorize_user)):
    return await list_urls_controller(body, user)


@atlas_kb_items_router.post("/v1/get-url")
async def get_url_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await get_url_controller(body, user)


@atlas_kb_items_router.post("/v1/create-urls")
async def create_urls_route(
    body: CreateUrlsRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await create_urls_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/update-url")
async def update_url_route(
    body: UpdateUrlRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await update_url_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/delete-url")
async def delete_url_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await delete_url_controller(body, user)


@atlas_kb_items_router.post("/v1/list-files")
async def list_files_route(body: PaginationRequest, user: dict = Depends(authorize_user)):
    return await list_files_controller(body, user)


@atlas_kb_items_router.post("/v1/get-file")
async def get_file_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await get_file_controller(body, user)


@atlas_kb_items_router.post("/v1/create-file")
async def create_file_route(body: CreateFileRequest, user: dict = Depends(authorize_user)):
    return await create_file_controller(body, user)


@atlas_kb_items_router.post("/v1/generate-presigned-urls")
async def generate_presigned_urls_route(body: GenerateKbPresignedUrlsRequest, user: dict = Depends(authorize_user)):
    return await generate_presigned_urls_controller(body, user)


@atlas_kb_items_router.post("/v1/finalize-file")
async def finalize_file_route(
    body: FinalizeFileRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await finalize_file_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/delete-file")
async def delete_file_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await delete_file_controller(body, user)


@atlas_kb_items_router.post("/v1/list-custom-texts")
async def list_custom_texts_route(body: PaginationRequest, user: dict = Depends(authorize_user)):
    return await list_custom_texts_controller(body, user)


@atlas_kb_items_router.post("/v1/get-custom-text")
async def get_custom_text_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await get_custom_text_controller(body, user)


@atlas_kb_items_router.post("/v1/create-custom-text")
async def create_custom_text_route(
    body: CreateCustomTextRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await create_custom_text_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/update-custom-text")
async def update_custom_text_route(
    body: UpdateCustomTextRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await update_custom_text_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/delete-custom-text")
async def delete_custom_text_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await delete_custom_text_controller(body, user)


@atlas_kb_items_router.post("/v1/list-qa-pairs")
async def list_qa_pairs_route(body: PaginationRequest, user: dict = Depends(authorize_user)):
    return await list_qa_pairs_controller(body, user)


@atlas_kb_items_router.post("/v1/get-qa-pair")
async def get_qa_pair_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await get_qa_pair_controller(body, user)


@atlas_kb_items_router.post("/v1/create-qa-pair")
async def create_qa_pair_route(
    body: CreateQaPairRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await create_qa_pair_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/update-qa-pair")
async def update_qa_pair_route(
    body: UpdateQaPairRequest,
    user: dict = Depends(authorize_user),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    return await update_qa_pair_controller(body, user, background_tasks)


@atlas_kb_items_router.post("/v1/delete-qa-pair")
async def delete_qa_pair_route(body: KbIdRequest, user: dict = Depends(authorize_user)):
    return await delete_qa_pair_controller(body, user)
