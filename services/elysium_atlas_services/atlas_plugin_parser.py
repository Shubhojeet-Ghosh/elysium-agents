"""Parse and validate Atlas plugin Python source (AST only — does not execute run())."""

from __future__ import annotations

import ast
from typing import Any

from config.atlas_plugin_config import (
    ATLAS_PLUGIN_ALLOWED_MODULES,
    ATLAS_PLUGIN_BANNED_NAMES,
    ATLAS_PLUGIN_CODE_MAX_CHARS,
    ATLAS_PLUGIN_MAX_SECRETS,
    PLUGIN_DESCRIPTION_CONSTANT,
    PLUGIN_DISPLAY_NAME_CONSTANT,
    PLUGIN_INPUTS_CLASS,
    PLUGIN_NAME_CONSTANT,
    PLUGIN_RUN_FUNCTION,
    PLUGIN_SECRETS_CLASS,
)
from config.atlas_tool_models import (
    TOOL_NAME_PATTERN,
    ToolParameterInput,
    build_tool_parameters_schema,
)


class PluginParseError(ValueError):
    """Raised when plugin source is syntactically valid Python but not a valid plugin."""


def _is_allowed_module(module_name: str) -> bool:
    if module_name in ATLAS_PLUGIN_ALLOWED_MODULES:
        return True
    return any(
        module_name == allowed or module_name.startswith(f"{allowed}.")
        for allowed in ATLAS_PLUGIN_ALLOWED_MODULES
    )


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _assignment_target_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    return None


def _scan_security(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_module(alias.name):
                    raise PluginParseError(f"Import of '{alias.name}' is not allowed in plugins.")
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                raise PluginParseError("Relative imports are not allowed in plugins.")
            module_name = node.module or ""
            if not module_name or not _is_allowed_module(module_name):
                raise PluginParseError(
                    f"Import from '{module_name or '.'}' is not allowed in plugins."
                )
        elif isinstance(node, ast.Name) and node.id in ATLAS_PLUGIN_BANNED_NAMES:
            raise PluginParseError(f"Use of '{node.id}' is not allowed in plugins.")
        elif isinstance(node, ast.Attribute) and node.attr in ATLAS_PLUGIN_BANNED_NAMES:
            raise PluginParseError(f"Use of '{node.attr}' is not allowed in plugins.")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ATLAS_PLUGIN_BANNED_NAMES:
                raise PluginParseError(f"Call to '{func.id}' is not allowed in plugins.")
            if isinstance(func, ast.Attribute) and func.attr in ATLAS_PLUGIN_BANNED_NAMES:
                raise PluginParseError(f"Call to '{func.attr}' is not allowed in plugins.")


def _extract_constants(tree: ast.Module) -> dict[str, str]:
    wanted = {
        PLUGIN_NAME_CONSTANT,
        PLUGIN_DISPLAY_NAME_CONSTANT,
        PLUGIN_DESCRIPTION_CONSTANT,
    }
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        name = _assignment_target_name(node.targets[0])
        if name not in wanted:
            continue
        value = _constant_string(node.value)
        if value is None:
            raise PluginParseError(f"{name} must be a string constant.")
        found[name] = value.strip()
    missing = [key for key in wanted if key not in found or not found[key]]
    if missing:
        raise PluginParseError(
            "Plugin file must define non-empty string constants: "
            + ", ".join(sorted(missing))
            + "."
        )
    return found


def _class_by_name(tree: ast.Module, class_name: str) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _extract_module_bindings(tree: ast.Module) -> dict[str, ast.AST]:
    """Collect top-level assignment value nodes for static resolution in PluginInputs."""
    bindings: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = _assignment_target_name(node.targets[0])
            if name:
                bindings[name] = node.value
            continue
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            name = _assignment_target_name(node.target)
            if name:
                bindings[name] = node.value
    return bindings


def _resolve_static_value(
    node: ast.AST,
    bindings: dict[str, ast.AST],
    *,
    stack: set[str] | None = None,
) -> Any:
    """
    Resolve a static plugin value from literals, string concatenation, containers,
    and references to other module-level constants. Does not execute plugin code.
    """
    if stack is None:
        stack = set()

    string_value = _constant_string(node)
    if string_value is not None:
        return string_value

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in stack:
            raise PluginParseError(f"Circular reference to '{node.id}' in plugin constants.")
        if node.id not in bindings:
            raise PluginParseError(
                f"PluginInputs references unknown module constant '{node.id}'."
            )
        stack.add(node.id)
        try:
            return _resolve_static_value(bindings[node.id], bindings, stack=stack)
        finally:
            stack.discard(node.id)

    if isinstance(node, ast.List):
        return [_resolve_static_value(item, bindings, stack=stack) for item in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_resolve_static_value(item, bindings, stack=stack) for item in node.elts)

    if isinstance(node, ast.Dict):
        resolved: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is None:
                raise PluginParseError("Dict unpacking is not allowed in PluginInputs values.")
            key = _resolve_static_value(key_node, bindings, stack=stack)
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise PluginParseError("PluginInputs dict keys must be static scalar values.")
            resolved[key] = _resolve_static_value(value_node, bindings, stack=stack)
        return resolved

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = _resolve_static_value(node.operand, bindings, stack=stack)
        if isinstance(operand, (int, float)):
            return +operand if isinstance(node.op, ast.UAdd) else -operand

    raise PluginParseError(
        "PluginInputs values must be built from literals, containers, and module-level constants."
    )


def _class_assignments(class_node: ast.ClassDef) -> list[tuple[str, ast.AST]]:
    assignments: list[tuple[str, ast.AST]] = []
    for node in class_node.body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = _assignment_target_name(node.targets[0])
            if name:
                assignments.append((name, node.value))
            continue
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            name = _assignment_target_name(node.target)
            if name:
                assignments.append((name, node.value))
            continue
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            continue
        raise PluginParseError(
            f"Class {class_node.name} may only contain simple attribute assignments."
        )
    return assignments


def _parse_inputs(tree: ast.Module) -> list[ToolParameterInput]:
    class_node = _class_by_name(tree, PLUGIN_INPUTS_CLASS)
    if class_node is None:
        return []

    module_bindings = _extract_module_bindings(tree)
    parameters: list[ToolParameterInput] = []
    names: list[str] = []
    for attr_name, value_node in _class_assignments(class_node):
        if not TOOL_NAME_PATTERN.match(attr_name):
            raise PluginParseError(
                f"PluginInputs attribute '{attr_name}' must start with a lowercase letter "
                "and contain only lowercase letters, numbers, and underscores."
            )
        try:
            raw = _resolve_static_value(value_node, module_bindings)
        except PluginParseError:
            raise
        except Exception as exc:
            raise PluginParseError(
                f"PluginInputs.{attr_name} must be a dict of type/description/required "
                f"built from literals or module-level constants."
            ) from exc
        if not isinstance(raw, dict):
            raise PluginParseError(f"PluginInputs.{attr_name} must be a dict.")
        payload = {"name": attr_name, **raw}
        try:
            parameters.append(ToolParameterInput.model_validate(payload))
        except Exception as exc:
            raise PluginParseError(
                f"Invalid PluginInputs.{attr_name}: {exc}"
            ) from exc
        names.append(attr_name)

    if len(names) != len(set(names)):
        raise PluginParseError("PluginInputs attribute names must be unique.")
    return parameters


def _parse_secret_names(tree: ast.Module) -> list[str]:
    class_node = _class_by_name(tree, PLUGIN_SECRETS_CLASS)
    if class_node is None:
        return []

    names: list[str] = []
    for attr_name, _value_node in _class_assignments(class_node):
        if not TOOL_NAME_PATTERN.match(attr_name):
            raise PluginParseError(
                f"PluginSecrets attribute '{attr_name}' must start with a lowercase letter "
                "and contain only lowercase letters, numbers, and underscores."
            )
        names.append(attr_name)

    if len(names) != len(set(names)):
        raise PluginParseError("PluginSecrets attribute names must be unique.")
    if len(names) > ATLAS_PLUGIN_MAX_SECRETS:
        raise PluginParseError(
            f"PluginSecrets cannot declare more than {ATLAS_PLUGIN_MAX_SECRETS} secrets."
        )
    return names


def _has_run_function(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == PLUGIN_RUN_FUNCTION:
            return True
    return False


def parse_plugin_source(python_code: str) -> dict[str, Any]:
    """
    Validate plugin source and return denormalized metadata.

    Returns:
        dict with name, display_name, description, parameters schema, secret_names.
    """
    if not isinstance(python_code, str) or not python_code.strip():
        raise PluginParseError("python_code is required.")
    if len(python_code) > ATLAS_PLUGIN_CODE_MAX_CHARS:
        raise PluginParseError(
            f"python_code cannot exceed {ATLAS_PLUGIN_CODE_MAX_CHARS} characters."
        )

    try:
        tree = ast.parse(python_code)
    except SyntaxError as exc:
        raise PluginParseError(f"Plugin file has a syntax error: {exc.msg}.") from exc

    if not isinstance(tree, ast.Module):
        raise PluginParseError("Plugin file must be a Python module.")

    _scan_security(tree)
    constants = _extract_constants(tree)
    name = constants[PLUGIN_NAME_CONSTANT]
    display_name = constants[PLUGIN_DISPLAY_NAME_CONSTANT]
    description = constants[PLUGIN_DESCRIPTION_CONSTANT]

    if not TOOL_NAME_PATTERN.match(name):
        raise PluginParseError(
            "PLUGIN_NAME must start with a lowercase letter and contain only "
            "lowercase letters, numbers, and underscores (max 64 characters)."
        )
    if len(display_name) > 128:
        raise PluginParseError("PLUGIN_DISPLAY_NAME cannot exceed 128 characters.")
    if len(description) > 2048:
        raise PluginParseError("PLUGIN_DESCRIPTION cannot exceed 2048 characters.")
    if not _has_run_function(tree):
        raise PluginParseError("Plugin file must define a top-level run(inputs, secrets) function.")

    parameters = _parse_inputs(tree)
    secret_names = _parse_secret_names(tree)

    return {
        "name": name,
        "display_name": display_name,
        "description": description,
        "parameters": build_tool_parameters_schema(parameters),
        "secret_names": secret_names,
    }
