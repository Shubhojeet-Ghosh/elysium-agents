"""
Isolated Atlas plugin runner.

Executed as a child process with a stripped environment. Does not import
config.settings (no APPLICATION_PASSKEY / JWT / Mongo URI in this process).
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from services.elysium_atlas_services.atlas_plugin_parser import PluginParseError, parse_plugin_source


class PluginSecretValues:
    """Attribute and dict access for decrypted plugin secrets."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)
        for key, value in self._values.items():
            setattr(self, key, value)

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)

    def keys(self):
        return self._values.keys()

    def __contains__(self, key: object) -> bool:
        return key in self._values


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _apply_memory_limit() -> None:
    try:
        import resource

        from config.atlas_plugin_config import ATLAS_PLUGIN_MEMORY_LIMIT_BYTES

        resource.setrlimit(
            resource.RLIMIT_AS,
            (ATLAS_PLUGIN_MEMORY_LIMIT_BYTES, ATLAS_PLUGIN_MEMORY_LIMIT_BYTES),
        )
    except (ImportError, ValueError, OSError):
        return


def _drop_project_from_sys_path() -> None:
    project = str(_PROJECT_ROOT)
    sys.path[:] = [entry for entry in sys.path if entry != project]


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, default=_json_default, ensure_ascii=False))
    sys.stdout.flush()


def _run_user_code(code: str, inputs: dict[str, Any], secrets: dict[str, str]) -> Any:
    parse_plugin_source(code)
    _drop_project_from_sys_path()
    namespace: dict[str, Any] = {"__name__": "atlas_plugin"}
    exec(compile(code, "<atlas_plugin>", "exec"), namespace, namespace)
    run_fn = namespace.get("run")
    if not callable(run_fn):
        raise RuntimeError("Plugin file must define a callable run(inputs, secrets).")

    secret_values = PluginSecretValues(secrets)
    result = run_fn(inputs or {}, secret_values)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return result


def main() -> int:
    _apply_memory_limit()
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw else {}
        code = payload.get("code") or ""
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}
        secrets = {str(key): "" if value is None else str(value) for key, value in secrets.items()}

        captured_stdout = sys.stdout
        sys.stdout = sys.stderr
        try:
            result = _run_user_code(code, inputs, secrets)
        finally:
            sys.stdout = captured_stdout

        if result is None:
            result = {}
        if not isinstance(result, (dict, list, str, int, float, bool)):
            result = {"result": str(result)}

        _emit({"ok": True, "result": result})
        return 0
    except PluginParseError as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit({"ok": False, "error": str(exc) or "Plugin execution failed."})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
