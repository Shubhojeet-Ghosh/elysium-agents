"""
Atlas Python plugin execution limits and source-file contract.
"""

PLUGIN_NAME_CONSTANT = "PLUGIN_NAME"
PLUGIN_DISPLAY_NAME_CONSTANT = "PLUGIN_DISPLAY_NAME"
PLUGIN_DESCRIPTION_CONSTANT = "PLUGIN_DESCRIPTION"
PLUGIN_INPUTS_CLASS = "PluginInputs"
PLUGIN_SECRETS_CLASS = "PluginSecrets"
PLUGIN_RUN_FUNCTION = "run"

ATLAS_PLUGIN_CODE_MAX_CHARS: int = 65_536
ATLAS_PLUGIN_MAX_SECRETS: int = 20
ATLAS_PLUGIN_TIMEOUT_SECONDS: float = 20.0
ATLAS_PLUGIN_MEMORY_LIMIT_BYTES: int = 256 * 1024 * 1024
MAX_AGENT_PLUGIN_IDS: int = 20

# User source may import these modules (and their submodules).
ATLAS_PLUGIN_ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "json",
        "datetime",
        "re",
        "math",
        "decimal",
        "typing",
        "collections",
        "itertools",
        "functools",
        "hashlib",
        "base64",
        "uuid",
        "urllib.parse",
        "httpx",
        "pymongo",
        "bson",
        "pymysql",
    }
)

ATLAS_PLUGIN_BANNED_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "__import__",
        "breakpoint",
    }
)
