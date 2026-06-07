import re
from typing import Any, Dict, List

from services.email_agent_services.email_tool_definitions.email_tool_definitions_constants import (
    ALLOWED_INPUT_TYPES,
)

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def normalize_tool_name(name: str) -> str:
    return name.strip().lower()


def validate_tool_name(name: str) -> str | None:
    """Return an error message if invalid, else None."""
    normalized = normalize_tool_name(name)
    if not normalized:
        return "name cannot be empty."
    if len(normalized) > 64:
        return "name must be at most 64 characters."
    if not _NAME_PATTERN.match(normalized):
        return "name must be snake_case (lowercase letters, numbers, underscores; start with a letter)."
    return None


def build_input_schema(inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert friendly input definitions into JSON Schema for LLM tool calling."""
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for input_def in inputs:
        field_name = input_def["name"].strip()
        field_type = input_def["type"].strip().lower()
        field_description = input_def["description"].strip()

        properties[field_name] = {
            "type": field_type,
            "description": field_description,
        }

        if input_def.get("required", False):
            required.append(field_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def validate_inputs(inputs: List[Dict[str, Any]]) -> str | None:
    """Return an error message if invalid, else None."""
    if not inputs:
        return None

    seen_names: set[str] = set()

    for input_def in inputs:
        field_name = input_def.get("name", "").strip()
        field_type = input_def.get("type", "").strip().lower()
        field_description = input_def.get("description", "").strip()

        if not field_name:
            return "Each input must have a name."
        if field_name in seen_names:
            return f"Duplicate input name: {field_name}"
        seen_names.add(field_name)

        if field_type not in ALLOWED_INPUT_TYPES:
            return (
                f"Invalid input type '{field_type}' for '{field_name}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_INPUT_TYPES))}"
            )
        if not field_description:
            return f"Input '{field_name}' must have a description."

    return None


def build_llm_tool_definition(tool: Dict[str, Any]) -> Dict[str, Any]:
    """Build OpenAI-compatible tool definition from a stored tool document."""
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}, "required": []}),
        },
    }
