from typing import Any, Dict


def format_tool_for_llm(tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a stored email-tools document into OpenAI function-calling format.

    Used later when the email agent LLM decides whether to invoke a tool.
    """
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {}),
        },
    }
