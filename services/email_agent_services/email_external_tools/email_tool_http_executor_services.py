from typing import Any, Dict

import httpx

from logging_config import get_logger
from services.email_agent_services.email_flows.email_flow_constants import (
    EMAIL_TOOLS_HTTP_TIMEOUT_SECONDS,
)

logger = get_logger()


async def execute_email_tool_http_call(
    *,
    endpoint_url: str,
    http_method: str,
    arguments: Dict[str, Any],
    timeout: float = EMAIL_TOOLS_HTTP_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """
    Execute a registered email tool via its configured HTTP endpoint.

    POST/PUT/PATCH send JSON body; GET sends query parameters.
    """
    normalized_url = (endpoint_url or "").strip()
    normalized_method = (http_method or "POST").strip().upper()
    safe_arguments = arguments or {}

    if not normalized_url:
        return {
            "success": False,
            "status_code": 400,
            "message": "Tool endpoint_url is not configured.",
            "response": None,
        }

    logger.info(
        f"Tool HTTP request: method={normalized_method} url={normalized_url} "
        f"arguments={safe_arguments}"
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if normalized_method == "GET":
                response = await client.get(normalized_url, params=safe_arguments)
            elif normalized_method == "POST":
                response = await client.post(normalized_url, json=safe_arguments)
            elif normalized_method == "PUT":
                response = await client.put(normalized_url, json=safe_arguments)
            elif normalized_method == "PATCH":
                response = await client.patch(normalized_url, json=safe_arguments)
            elif normalized_method == "DELETE":
                response = await client.request(
                    "DELETE",
                    normalized_url,
                    json=safe_arguments,
                )
            else:
                return {
                    "success": False,
                    "status_code": 400,
                    "message": f"Unsupported HTTP method: {normalized_method}",
                    "response": None,
                }

        response_body: Any
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"raw_text": response.text}

        success = 200 <= response.status_code < 300
        message = ""
        if isinstance(response_body, dict):
            message = response_body.get("message", "")

        logger.info(
            f"Tool HTTP response: method={normalized_method} url={normalized_url} "
            f"status_code={response.status_code} success={success} message={message}"
        )

        return {
            "success": success,
            "status_code": response.status_code,
            "message": message,
            "response": response_body,
        }

    except httpx.TimeoutException:
        logger.error(f"Tool HTTP call timed out: {normalized_method} {normalized_url}")
        return {
            "success": False,
            "status_code": 504,
            "message": "Tool HTTP call timed out.",
            "response": None,
        }
    except httpx.RequestError as exc:
        logger.error(
            f"Tool HTTP call failed: {normalized_method} {normalized_url}: {exc}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 502,
            "message": f"Tool HTTP call failed: {exc}",
            "response": None,
        }
    except Exception as exc:
        logger.error(
            f"Unexpected tool HTTP error: {normalized_method} {normalized_url}: {exc}",
            exc_info=True,
        )
        return {
            "success": False,
            "status_code": 500,
            "message": "Unexpected tool HTTP error.",
            "response": None,
        }
