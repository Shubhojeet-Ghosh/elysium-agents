from typing import Dict, Any

from fastapi import APIRouter, Depends

from controller.general_controller_files.chat_with_llm_models_controllers import chat_with_model_controller
from middlewares.application_passkey_auth import verify_application_passkey

elysium_chat_router = APIRouter(prefix="/elysium-chat", tags=["Elysium Chat"])


@elysium_chat_router.post("/v1/chat-with-model")
async def chat_with_model_route_v1(
    requestData: Dict[str, Any],
    authorized: bool = Depends(verify_application_passkey),
):
    return await chat_with_model_controller(requestData,authorized)
