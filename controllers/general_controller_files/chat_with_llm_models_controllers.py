from fastapi.responses import JSONResponse
from logging_config import get_logger
from config.settings import settings

from config.llm_models_config import resolve_model_handler, DEFAULT_MODEL

logger = get_logger()


async def chat_with_model_controller(requestData, authorized):
    try:
        logger.info("chat_with_model_controller invoked")
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "You are unauthorized to access this resource."},
            )

        # Extract model and user message
        model = requestData.get("model") or DEFAULT_MODEL
        user_message = requestData.get("message")

        if not user_message:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Message is required."},
            )

        # Resolve handler from registry (defaults if unknown model)
        handler, config = resolve_model_handler(model)

        # Build standard messages
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": user_message},
        ]

        # Build payload; allow passthrough for optional params like temperature, top_p, etc.
        chat_payload = {
            "model": model,
            "messages": messages,
        }
       
        if "temperature" in requestData:
            chat_payload["temperature"] = requestData["temperature"]

        stream = False
        if "stream" in requestData:
            stream = bool(requestData["stream"])
            chat_payload["stream"] = stream

        logger.info(f"Resolved model '{model}' with handler '{handler.__name__}'")

        if stream:
            print(f"[chat_with_model_controller] Streaming enabled for model '{model}'")
        logger.info(f"Inference for model '{model}' started")
        # Call model-specific handler
        response_obj = await handler(chat_payload)

        # If streaming, iterate over async generator and print chunks
        response_text = ""
        if stream and hasattr(response_obj, "__aiter__"):
            async for chunk in response_obj:
                response_text += chunk
                # print(f"{chunk}", end="", flush=True)
            print(f"[chat_with_model_controller] Streaming completed for model '{model}'")
        else:
            response_text = response_obj

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Chat with model successful", "response": response_text},
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while chatting with the model", "error": str(e)},
        )