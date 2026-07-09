from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Current workspace root
WORKSPACE_ROOT = Path.cwd().resolve()

# ---------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------

JSON_PATTERN = re.compile(
    r"```json\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)

BASH_PATTERN = re.compile(
    r"```(?:bash|sh)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)

# ── Normalization ───────────────────────────────────────────────────────────

_COMMAND_MAX_LENGTH: int = 4096


def normalize(text: str) -> str:
    """
    Normalize user-facing input:
      - NFKC (Unicode homoglyph prevention)
      - Strip ASCII control characters except \n, \t
    Returns the normalized string.  Non-strings are returned as-is.
    """
    if not isinstance(text, str):
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in normalized if ch == "\n" or ch == "\t" or not unicodedata.category(ch).startswith("C"))


# ---------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------


@dataclass(slots=True)
class ToolCall:
    tool: str
    args: dict[str, Any]


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    data: dict[str, Any] | None
    error: str | None = None

    def __iter__(self):
        return iter((self.ok, self.data, self.error))


# ---------------------------------------------------------------------
# Tool Schemas & Gatekeeper
# ---------------------------------------------------------------------

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "execute_shell": {
        "required": {
            "command": str,
        },
        "optional": {
            "timeout": int,
        },
        "constraints": {
            "command": {
                "max_length": 4096,
            },
        },
    },
    "web_search": {
        "required": {
            "query": str,
        },
        "optional": {
            "limit": int,
        },
    },
    "file_system": {
        "required": {
            "action": str,
            "path": str,
        },
        "optional": {
            "content": str,
            "old_text": str,
            "new_text": str,
        },
        "actions": {
            "read": [],
            "write": [
                "content",
            ],
            "append": [
                "content",
            ],
            "replace": [
                "old_text",
                "new_text",
            ],
        },
    },
    "search_memory": {
        "required": {
            "query": str,
        },
        "optional": {
            "limit": int,
        },
    },
}


def _validate_path(path: str) -> bool:
    try:
        workspace_root = Path.cwd().resolve()
        resolved = (workspace_root / path).resolve()
        resolved.relative_to(workspace_root)
        return True
    except Exception:
        return False


def validate_tool_call(payload: Any) -> ValidationResult:
    if isinstance(payload, str):
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError as e:
            return ValidationResult(
                False,
                None,
                f"Invalid JSON: {e.msg}",
            )
    else:
        obj = payload

    if not isinstance(obj, dict):
        return ValidationResult(
            False,
            None,
            "Root must be a JSON object.",
        )

    tool = obj.get("tool")
    args = obj.get("args")

    if not isinstance(tool, str):
        return ValidationResult(
            False,
            None,
            "'tool' must be a string.",
        )

    if not isinstance(args, dict):
        return ValidationResult(
            False,
            None,
            "'args' must be an object.",
        )

    schema = TOOL_SCHEMAS.get(tool)

    if schema is None:
        return ValidationResult(
            False,
            None,
            f"Unknown tool '{tool}'.",
        )

    required = schema["required"]
    optional = schema.get("optional", {})
    allowed = set(required) | set(optional)

    for key in args:
        if key not in allowed:
            return ValidationResult(
                False,
                None,
                f"Unexpected argument '{key}'.",
            )

    for key, typ in required.items():
        if key not in args:
            return ValidationResult(
                False,
                None,
                f"Missing required argument '{key}'.",
            )

        if not isinstance(args[key], typ):
            return ValidationResult(
                False,
                None,
                f"Argument '{key}' must be {typ.__name__}.",
            )

    for key, typ in optional.items():
        if key in args and not isinstance(args[key], typ):
            return ValidationResult(
                False,
                None,
                f"Argument '{key}' must be {typ.__name__}.",
            )

    # ── Constraints (max_length, etc.) ──────────────────────────────────────
    constraints = schema.get("constraints", {})
    for arg_key, constraint_set in constraints.items():
        if arg_key in args:
            if "max_length" in constraint_set:
                max_len = constraint_set["max_length"]
                val = args[arg_key]
                if isinstance(val, str) and len(val) > max_len:
                    return ValidationResult(
                        False,
                        None,
                        f"Argument '{arg_key}' exceeds maximum length ({len(val)} > {max_len}).",
                    )

    if tool == "file_system":
        action = args.get("action")
        valid_actions = schema["actions"]

        if action not in valid_actions:
            return ValidationResult(
                False,
                None,
                f"Unsupported action '{action}'.",
            )

        for field in valid_actions[action]:
            if field not in args:
                return ValidationResult(
                    False,
                    None,
                    f"Action '{action}' requires '{field}'.",
                )

        if not _validate_path(args["path"]):
            return ValidationResult(
                False,
                None,
                "Path escapes workspace.",
            )

    return ValidationResult(
        True,
        obj,
        None,
    )


# ---------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------


def _validate_payload(payload: Any) -> ToolCall | None:
    """
    Validate a JSON tool payload using the strict schema gatekeeper.
    """
    res = validate_tool_call(payload)
    if not res.ok or not res.data:
        return None

    return ToolCall(
        tool=res.data["tool"],
        args=res.data["args"],
    )


# ---------------------------------------------------------------------
# JSON Strategy
# ---------------------------------------------------------------------


def _parse_json(text: str) -> ToolCall | None:
    match = JSON_PATTERN.search(text)
    if not match:
        return None

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    return _validate_payload(payload)


# ---------------------------------------------------------------------
# Bash Strategy
# ---------------------------------------------------------------------


def _parse_bash(text: str) -> ToolCall | None:
    match = BASH_PATTERN.search(text)
    if not match:
        return None

    command = match.group(1).strip()
    if not command:
        return None

    return ToolCall(
        tool="execute_shell",
        args={
            "command": command,
        },
    )


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def extract_json_from_response(text: str) -> str | None:
    """
    Extract raw JSON string from an LLM response.
    """
    if not text or not text.strip():
        return None
    text = normalize(text)
    match = JSON_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    text_stripped = text.strip()
    if text_stripped.startswith("{") and text_stripped.endswith("}"):
        return text_stripped
    return None


def extract_command(text: str) -> ToolCall | None:
    """
    Parse an LLM response and extract a tool call.

    Priority:

        1. JSON Tool Call
        2. Bash Code Block (Legacy)

    Returns:
        ToolCall | None
    """
    if not text or not text.strip():
        return None

    text = normalize(text)

    parsers = (
        _parse_json,
        _parse_bash,
    )

    for parser in parsers:
        result = parser(text)
        if result is not None:
            return result

    return None
