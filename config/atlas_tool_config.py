"""
Atlas custom tool execution limits (agent chat tool-calling).
"""

from typing import Literal

# Max characters of each tool's HTTP response body injected into the LLM context.
# Applied per tool call, not across all tools in a turn.
ATLAS_TOOL_LLM_RESULT_MAX_CHARS: int = 48_000

# Max JSON characters stored/emitted per tool request or response payload.
# Applied independently to request_payload and response_payload.
ATLAS_TOOL_OBSERVABILITY_MAX_CHARS: int = 16_000

# Hard caps for agent tool_calling_config (user values are clamped during validation).
ABSOLUTE_MAX_TOOL_ROUNDS: int = 10
ABSOLUTE_MAX_TOOL_EXECUTIONS_PER_TURN: int = 20

ToolResultMessageRole = Literal["assistant", "system"]

# Default role for injecting tool HTTP results into the final chat model prompt.
DEFAULT_TOOL_RESULT_MESSAGE_ROLE: ToolResultMessageRole = "assistant"

# xAI Grok SDK only accepts system + user roles — tool results use system for grok models.
GROK_TOOL_RESULT_MESSAGE_ROLE: ToolResultMessageRole = "system"
GROK_MODEL_FAMILY = "grok"


def get_tool_result_message_role(model_name: str) -> ToolResultMessageRole:
    """Pick message role for tool results based on the agent's final response model."""
    from config.llm_models_config import get_model_config

    if get_model_config(model_name).get("family") == GROK_MODEL_FAMILY:
        return GROK_TOOL_RESULT_MESSAGE_ROLE
    return DEFAULT_TOOL_RESULT_MESSAGE_ROLE
