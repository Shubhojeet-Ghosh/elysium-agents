import asyncio
import datetime
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from bson import ObjectId
from bson.errors import InvalidId

from config.atlas_tool_config import (
    ATLAS_TOOL_LLM_RESULT_MAX_CHARS,
    ATLAS_TOOL_OBSERVABILITY_MAX_CHARS,
)
from logging_config import get_logger
from services.elysium_atlas_services.atlas_tool_secrets import decrypt_tool_token
from services.mongo_services import get_collection

logger = get_logger()

COLLECTION_NAME = "atlas_tools"
TOOL_CALL_MODEL = "deepseek-v4-pro"
TOOL_HTTP_TIMEOUT_SECONDS = 30.0


async def get_active_tools_by_ids(tool_ids: list[str]) -> list[dict[str, Any]]:
    """Load active atlas_tools documents for execution (includes encrypted auth)."""
    if not tool_ids:
        return []

    object_ids: list[ObjectId] = []
    for tool_id in tool_ids:
        try:
            object_ids.append(ObjectId(tool_id))
        except InvalidId:
            logger.warning(f"Skipping invalid tool_id during chat tool load: {tool_id}")

    if not object_ids:
        return []

    collection = get_collection(COLLECTION_NAME)
    cursor = collection.find({"_id": {"$in": object_ids}, "is_active": True})
    documents = await cursor.to_list(length=len(object_ids))
    return documents


def build_openai_tools_definitions(tool_documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored tool documents to OpenAI/DeepSeek tools array."""
    tools: list[dict[str, Any]] = []
    for document in tool_documents:
        parameters = document.get("parameters") or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": document["name"],
                    "description": document.get("description") or "",
                    "parameters": parameters,
                },
            }
        )
    return tools


def _build_auth_headers_and_query(auth: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}

    if auth.get("type") != "api_key":
        return headers, query_params

    encrypted = auth.get("token_encrypted")
    if not encrypted:
        return headers, query_params

    token = decrypt_tool_token(encrypted)
    param_name = auth.get("param_name") or ""
    location = auth.get("location")

    if location == "header" and param_name:
        prefix = auth.get("token_prefix", "Bearer")
        if prefix and prefix != "none":
            headers[param_name] = f"{prefix} {token}"
        else:
            headers[param_name] = token
    elif location == "query" and param_name:
        query_params[param_name] = token

    return headers, query_params


def _stringify_tool_response(response: httpx.Response) -> str:
    try:
        body = response.json()
        payload: Any = body
    except Exception:
        payload = response.text or ""

    if response.status_code >= 400:
        return json.dumps(
            {
                "error": True,
                "status_code": response.status_code,
                "body": payload,
            }
        )

    if isinstance(payload, str):
        return payload
    return json.dumps(payload)


def cap_tool_result_for_llm(tool_name: str, tool_result: str) -> str:
    """Truncate a single tool's raw response before it is wrapped for the LLM."""
    max_chars = ATLAS_TOOL_LLM_RESULT_MAX_CHARS
    if len(tool_result) <= max_chars:
        return tool_result

    logger.warning(
        f"Tool '{tool_name}' result truncated from {len(tool_result)} to {max_chars} chars for LLM input"
    )
    return (
        f"{tool_result[:max_chars]}\n\n"
        f"[Tool result truncated at {max_chars} characters for LLM context limit.]"
    )


def format_tool_result_for_llm(tool_name: str, tool_result: str) -> str:
    """Plain-text tool output for the final chat model (no OpenAI tool role)."""
    capped_result = cap_tool_result_for_llm(tool_name, tool_result)
    return f"This is the tool call result/s : {capped_result}"


async def execute_atlas_tool(tool_document: dict[str, Any], arguments: dict[str, Any]) -> str:
    """Execute an external HTTP tool call and return a stringified response for the LLM."""
    method = str(tool_document.get("http_method", "GET")).upper()
    url = tool_document.get("api_url", "")
    tool_name = tool_document.get("name", "unknown")

    auth_headers, auth_query = _build_auth_headers_and_query(tool_document.get("auth") or {})
    headers = {
        "Accept": "application/json",
        **auth_headers,
    }

    safe_arguments = {
        key: value
        for key, value in (arguments or {}).items()
        if value is not None
    }

    try:
        async with httpx.AsyncClient(timeout=TOOL_HTTP_TIMEOUT_SECONDS) as client:
            if method in {"GET", "DELETE"}:
                response = await client.request(
                    method,
                    url,
                    params={**auth_query, **safe_arguments},
                    headers=headers,
                )
            else:
                headers["Content-Type"] = "application/json"
                response = await client.request(
                    method,
                    url,
                    params=auth_query or None,
                    json=safe_arguments,
                    headers=headers,
                )
    except httpx.TimeoutException:
        logger.warning(f"Tool '{tool_name}' timed out calling {url}")
        return json.dumps({"error": True, "message": "Tool request timed out."})
    except httpx.HTTPError as exc:
        logger.error(f"Tool '{tool_name}' HTTP error: {exc}", exc_info=True)
        return json.dumps({"error": True, "message": "Tool request failed."})

    logger.info(f"Tool '{tool_name}' responded with status={response.status_code}")
    return _stringify_tool_response(response)


def _tools_by_name(tool_documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {document["name"]: document for document in tool_documents if document.get("name")}


def parse_tool_result_payload(tool_result: str) -> Any:
    """Parse a tool HTTP result string into JSON when possible."""
    if not tool_result:
        return tool_result
    try:
        return json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return tool_result


def cap_observability_payload(value: Any) -> tuple[Any, bool]:
    """Cap a JSON-serializable payload for Mongo/socket (does not affect the LLM prompt)."""
    if value is None:
        return None, False
    serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(serialized) <= ATLAS_TOOL_OBSERVABILITY_MAX_CHARS:
        return value, False
    logger.warning(
        f"Tool observability payload truncated from {len(serialized)} "
        f"to {ATLAS_TOOL_OBSERVABILITY_MAX_CHARS} chars"
    )
    return serialized[:ATLAS_TOOL_OBSERVABILITY_MAX_CHARS], True


def build_tool_call_observability_record(
    *,
    tool_name: str,
    request_payload: dict[str, Any],
    tool_result: str,
    execution_kind: str = "http",
) -> dict[str, Any]:
    """Structured tool call record for persistence and monitor emit."""
    capped_request, request_truncated = cap_observability_payload(request_payload)
    capped_response, response_truncated = cap_observability_payload(
        parse_tool_result_payload(tool_result)
    )
    return {
        "tool_name": tool_name,
        "request_payload": capped_request,
        "response_payload": capped_response,
        "request_payload_truncated": request_truncated,
        "response_payload_truncated": response_truncated,
        "status": "error" if _is_tool_result_error(tool_result) else "success",
        "execution_kind": execution_kind,
        "created_at": datetime.datetime.now(datetime.timezone.utc),
    }


async def _notify_tool_call_observer(
    on_tool_call: Callable[[dict[str, Any]], Awaitable[None]],
    record: dict[str, Any],
) -> None:
    try:
        await on_tool_call(record)
    except Exception:
        logger.error(
            f"Tool call observer failed for tool '{record.get('tool_name')}'",
            exc_info=True,
        )


async def run_agent_tool_calling_round(
    messages: list[dict[str, Any]],
    tool_ids: list[str],
    *,
    plugin_ids: list[str] | None = None,
    tool_calling_config: dict[str, Any] | None = None,
    temperature: float = 0.3,
    on_tool_call: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> list[dict[str, Any]] | None:
    """
    Run multi-round tool orchestration via DeepSeek for this chat turn.

    Returns messages to insert before the current user message on the final response
    call (assistant role, plain text — compatible with Claude and other chat APIs).
    Returns None when no tools or plugins run this turn.

    on_tool_call is fired in the background after each HTTP or plugin execution (success or
    error) so persist/emit cannot block the orchestration loop.
    """
    from config.atlas_tool_calling_config import normalize_tool_calling_config
    from services.deepseek_services import deepseek_chat_completion_with_tools
    from services.elysium_atlas_services.atlas_plugin_execution_services import execute_atlas_plugin
    from services.elysium_atlas_services.atlas_plugin_services import get_active_plugins_by_ids

    config = normalize_tool_calling_config(tool_calling_config)
    if not config.get("enabled"):
        return None

    max_rounds = config["max_rounds"]
    max_executions = config["max_executions_per_turn"]
    parallel_calls = config["parallel_calls_per_round"]
    stop_on_error = config["stop_on_error"]

    tool_documents = await get_active_tools_by_ids(tool_ids)
    plugin_documents = await get_active_plugins_by_ids(plugin_ids or [])
    if not tool_documents and not plugin_documents:
        return None

    tools = build_openai_tools_definitions(tool_documents + plugin_documents)
    tools_lookup = _tools_by_name(tool_documents)
    plugins_lookup = _tools_by_name(plugin_documents)
    working_messages = list(messages)
    final_turn_messages: list[dict[str, Any]] = []
    executions = 0

    for round_index in range(max_rounds):
        tool_response = await deepseek_chat_completion_with_tools(
            {
                "model": TOOL_CALL_MODEL,
                "messages": working_messages,
                "tools": tools,
                "temperature": temperature,
            }
        )

        tool_calls = tool_response.get("tool_calls") or []
        if not tool_calls:
            logger.info(f"Tool calling finished after round {round_index}: no further tool_calls")
            break

        assistant_message = tool_response.get("assistant_message")
        if assistant_message:
            working_messages.append(assistant_message)
        else:
            working_messages.append(
                {
                    "role": "assistant",
                    "content": tool_response.get("content"),
                    "tool_calls": tool_calls,
                }
            )

        calls_to_run = tool_calls if parallel_calls else tool_calls[:1]
        round_stop = False

        for tool_call in calls_to_run:
            if executions >= max_executions:
                logger.info(
                    f"Tool calling stopped: max_executions_per_turn={max_executions} reached"
                )
                round_stop = True
                break

            function_name = tool_call.get("function", {}).get("name")
            raw_arguments = tool_call.get("function", {}).get("arguments") or "{}"
            tool_call_id = tool_call.get("id") or f"call_{executions}"

            parsed_arguments: dict[str, Any] = {}
            tool_document = tools_lookup.get(function_name)
            plugin_document = plugins_lookup.get(function_name)
            execution_kind = "http"
            if not tool_document and not plugin_document:
                logger.warning(f"LLM requested unknown tool '{function_name}'; skipping execution")
                tool_result = json.dumps({"error": True, "message": f"Unknown tool: {function_name}"})
            else:
                try:
                    parsed_arguments = (
                        json.loads(raw_arguments)
                        if isinstance(raw_arguments, str)
                        else raw_arguments
                    )
                    if not isinstance(parsed_arguments, dict):
                        parsed_arguments = {}
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON arguments for tool '{function_name}': {raw_arguments}")
                    parsed_arguments = {}

                if plugin_document:
                    execution_kind = "plugin"
                    tool_result = await execute_atlas_plugin(plugin_document, parsed_arguments)
                else:
                    tool_result = await execute_atlas_tool(tool_document, parsed_arguments)

            executions += 1
            resolved_tool_name = function_name or "unknown"
            if on_tool_call:
                observability_record = build_tool_call_observability_record(
                    tool_name=resolved_tool_name,
                    request_payload=parsed_arguments,
                    tool_result=tool_result,
                    execution_kind=execution_kind,
                )
                asyncio.create_task(
                    _notify_tool_call_observer(on_tool_call, dict(observability_record))
                )
            capped_result = cap_tool_result_for_llm(resolved_tool_name, tool_result)
            working_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": capped_result,
                }
            )
            final_turn_messages.append(
                _build_tool_result_message(resolved_tool_name, tool_result)
            )

            if stop_on_error and _is_tool_result_error(tool_result):
                logger.info(f"Tool calling stopped after error from tool '{function_name}'")
                round_stop = True
                break

        logger.info(
            f"Tool calling round {round_index + 1}/{max_rounds} complete "
            f"(executions={executions}, tool_calls={len(calls_to_run)})"
        )

        if round_stop or executions >= max_executions:
            break

    return final_turn_messages or None


def _is_tool_result_error(tool_result: str) -> bool:
    try:
        payload = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(payload, dict) and payload.get("error") is True


def _build_tool_result_message(tool_name: str, tool_result: str) -> dict[str, Any]:
    """Assistant message with stringified tool output (Claude-safe — no tool role or tool_call_id)."""
    return {
        "role": "assistant",
        "content": format_tool_result_for_llm(tool_name, tool_result),
    }
