from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from config.settings import settings

from config.llm_models_config import resolve_model_handler, DEFAULT_MODEL
from config.structured_output_models import get_structured_output_model, get_available_model_keys
from services.open_ai_services import openai_structured_output

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


async def extract_structured_data_controller(requestData: Dict[str, Any], authorized: bool):
    """
    Generic controller for extracting structured information from text content.
    Uses a registry of Pydantic models to determine the extraction schema.
    
    Args:
        requestData: Dictionary containing:
            - extraction_type (str, required): The key identifying which structured output model to use
            - text_content (str, required): The text content to extract information from
            - model (str, optional): The OpenAI model to use for extraction (defaults to "gpt-4o-2024-08-06")
        authorized: Whether the request is authorized
        
    Returns:
        JSONResponse with extracted structured data
    """
    try:
        logger.info("extract_structured_data_controller invoked")
        
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "You are unauthorized to access this resource."},
            )
        
        # Extract required fields
        extraction_type = requestData.get("extraction_type")
        text_content = requestData.get("text_content")
        model = requestData.get("model", "gpt-4o-2024-08-06")
        
        # Validate extraction_type
        if not extraction_type:
            available_types = get_available_model_keys()
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "extraction_type is required.",
                    "available_types": available_types
                },
            )
        
        # Validate text_content
        if not text_content or not text_content.strip():
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "text_content is required and cannot be empty."},
            )
        
        # Get the Pydantic model class from registry
        try:
            response_format_class = get_structured_output_model(extraction_type)
        except ValueError as e:
            available_types = get_available_model_keys()
            logger.error(f"Invalid extraction_type '{extraction_type}'. Available types: {available_types}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": str(e),
                    "available_types": available_types
                },
            )
        
        # Build messages for extraction
        messages = [
            {
                "role": "system",
                "content": f"You are an expert at extracting structured information from text content. Analyze the provided text and extract information according to the {extraction_type} schema."
            },
            {
                "role": "user",
                "content": f"Extract structured information from the following content:\n\n{text_content}"
            }
        ]
        
        logger.info(f"Calling openai_structured_output with model '{model}' and extraction_type '{extraction_type}'")
        
        # Call the OpenAI structured output function
        result = await openai_structured_output(
            model=model,
            messages=messages,
            response_format=response_format_class
        )
        
        logger.info(f"Successfully extracted structured data using '{extraction_type}' extraction type")
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Structured data extracted successfully",
                "extraction_type": extraction_type,
                "structured_output": result
            },
        )
        
    except ValueError as e:
        logger.error(f"Validation error in extract_structured_data_controller: {e}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Invalid request data", "error": str(e)},
        )
    except Exception as e:
        logger.error(f"Error in extract_structured_data_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while extracting structured data", "error": str(e)},
        )