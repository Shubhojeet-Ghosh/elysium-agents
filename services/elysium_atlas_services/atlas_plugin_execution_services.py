import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from config.atlas_plugin_config import ATLAS_PLUGIN_TIMEOUT_SECONDS
from logging_config import get_logger
from services.elysium_atlas_services.atlas_plugin_secrets import decrypt_plugin_secret

logger = get_logger()

RUNNER_PATH = Path(__file__).resolve().parent / "atlas_plugin_sandbox_runner.py"
SANDBOX_ENV_KEEP = ("PATH", "SYSTEMROOT", "WINDIR", "SystemRoot", "TEMP", "TMP", "PATHEXT", "COMSPEC")


def _sandbox_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in SANDBOX_ENV_KEEP:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def decrypt_plugin_secrets(document: dict[str, Any]) -> dict[str, str]:
    """Decrypt stored plugin secrets; missing keys become empty strings."""
    secret_names = document.get("secret_names") or []
    stored = document.get("secrets") or {}
    decrypted: dict[str, str] = {}
    for name in secret_names:
        ciphertext = stored.get(name)
        if not ciphertext:
            decrypted[name] = ""
            continue
        try:
            decrypted[name] = decrypt_plugin_secret(ciphertext)
        except Exception:
            logger.error(
                f"Failed to decrypt plugin secret '{name}' for plugin '{document.get('name')}'",
                exc_info=True,
            )
            decrypted[name] = ""
    return decrypted


def _stringify_plugin_result(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        return json.dumps({"error": True, "message": payload.get("error") or "Plugin execution failed."})
    result = payload.get("result")
    if isinstance(result, str):
        return result
    return json.dumps(result)


def _sandbox_cwd() -> str:
    return str(Path(os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"))


def _run_plugin_subprocess(payload: str) -> subprocess.CompletedProcess:
    # subprocess.run (not asyncio.create_subprocess_exec): uvicorn on Windows uses
    # SelectorEventLoop, which raises NotImplementedError for subprocess transports.
    return subprocess.run(
        [sys.executable, "-I", "-B", str(RUNNER_PATH)],
        input=payload.encode("utf-8"),
        capture_output=True,
        timeout=ATLAS_PLUGIN_TIMEOUT_SECONDS,
        env=_sandbox_env(),
        cwd=_sandbox_cwd(),
        start_new_session=True,
        check=False,
    )


async def execute_atlas_plugin(plugin_document: dict[str, Any], arguments: dict[str, Any]) -> str:
    """Run plugin source in an isolated subprocess and return a stringified result for the LLM."""
    plugin_name = plugin_document.get("name", "unknown")
    python_code = plugin_document.get("python_code") or ""
    secrets = decrypt_plugin_secrets(plugin_document)
    payload = json.dumps(
        {
            "code": python_code,
            "inputs": arguments or {},
            "secrets": secrets,
        },
        ensure_ascii=False,
    )

    try:
        completed = await asyncio.to_thread(_run_plugin_subprocess, payload)
    except subprocess.TimeoutExpired:
        logger.warning(f"Plugin '{plugin_name}' timed out after {ATLAS_PLUGIN_TIMEOUT_SECONDS}s")
        return json.dumps({"error": True, "message": "Plugin execution timed out."})
    except Exception:
        logger.error(f"Failed to start plugin sandbox for '{plugin_name}'", exc_info=True)
        return json.dumps({"error": True, "message": "Plugin execution failed to start."})

    stderr = completed.stderr
    stdout = completed.stdout
    if stderr:
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if stderr_text:
            logger.info(f"Plugin '{plugin_name}' debug output:\n{stderr_text}")

    raw = (stdout or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        logger.error(f"Plugin '{plugin_name}' produced empty stdout (exit={completed.returncode})")
        return json.dumps({"error": True, "message": "Plugin execution failed."})

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(f"Plugin '{plugin_name}' returned non-JSON stdout")
        return json.dumps({"error": True, "message": "Plugin execution failed."})

    if not isinstance(parsed, dict):
        return json.dumps({"error": True, "message": "Plugin execution failed."})

    return _stringify_plugin_result(parsed)
