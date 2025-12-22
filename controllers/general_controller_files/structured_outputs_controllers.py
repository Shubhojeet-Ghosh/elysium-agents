from typing import Dict, Any
from fastapi.responses import JSONResponse
from logging_config import get_logger
from services.claude_services import get_structured_output

logger = get_logger()


async def structured_outputs_controller(requestData: Dict[str, Any], authorized: bool):
    """
    Controller for Claude structured outputs endpoint.
    
    Expected requestData format:
    {
        "fields": [
            {"key_name": "email", "type": "str"},
            {"key_name": "demo_requested", "type": "bool"}
        ],
        "messages": [
            {
                "role": "user",
                "content": "Extract the key information from this email: ..."
            }
        ],
        "model": "claude-sonnet-4-5",  // optional, defaults to "claude-sonnet-4-5"
        "max_tokens": 4096  // optional, defaults to 4096
    }
    """
    try:
        logger.info("structured_outputs_controller invoked")
        
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"success": False, "message": "You are unauthorized to access this resource."},
            )

        # Extract required fields
        fields = requestData.get("fields")
        messages = requestData.get("messages")

        if not fields:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "fields is required in requestData."},
            )

        if not messages:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "messages is required in requestData."},
            )

        # Extract optional parameters
        model = requestData.get("model", "claude-sonnet-4-5")
        max_tokens = requestData.get("max_tokens", 4096)  # Default to 4096 if not provided

        # Prepare additional kwargs (for any other optional parameters)
        kwargs = {}
        if "temperature" in requestData:
            kwargs["temperature"] = requestData["temperature"]
        if "top_p" in requestData:
            kwargs["top_p"] = requestData["top_p"]

        logger.info(f"Calling get_structured_output with model '{model}', {len(fields)} fields, {len(messages)} messages, max_tokens={max_tokens}")

        # Call the Claude service function
        # Note: get_structured_output is synchronous, so we don't need await
        result = get_structured_output(
            fields=fields,
            messages=messages,
            model=model,
            max_tokens=max_tokens,
            **kwargs
        )

        # Extract data and usage from result
        structured_output = result.get("structured_output", {})
        usage_info = result.get("usage", {})

        logger.info(f"Successfully generated structured output. Input tokens: {usage_info.get('input_tokens', 0)}, Output tokens: {usage_info.get('output_tokens', 0)}")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Structured output generated successfully",
                "data": structured_output,
                "usage": usage_info
            },
        )

    except ValueError as e:
        logger.error(f"Validation error in structured_outputs_controller: {e}")
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Invalid request data", "error": str(e)},
        )
    except Exception as e:
        logger.error(f"Error in structured_outputs_controller: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "An error occurred while generating structured output", "error": str(e)},
        )

