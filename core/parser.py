from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Optional

from core.sanitize import sanitize

# Pinned workspace root — set once by AppContext.build(), never re-evaluated.
# Falls back to Path.cwd() if not explicitly set.
_WORKSPACE_ROOT: Optional[Path] = None


def pin_workspace_root(root: Path) -> None:
    """Pin the workspace root for all subsequent path validation.

    Called once by AppContext.build() at startup.  After this, all
    _validate_path calls use this value regardless of later chdir calls.
    """
    global _WORKSPACE_ROOT
    _WORKSPACE_ROOT = root.resolve()


def get_workspace_root() -> Path:
    """Return the pinned workspace root, or cwd as fallback."""
    return _WORKSPACE_ROOT.resolve() if _WORKSPACE_ROOT else Path.cwd().resolve()

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
      - Strip ANSI sequences and illegal control characters except \n, \t
    Returns the normalized string.  Non-strings are returned as-is.
    """
    if not isinstance(text, str):
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return sanitize(normalized)


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
    "todo_write": {
        "required": {
            "todos": list,
        },
        "optional": {},
    },
    "termux_monitor": {
        "required": {},
        "optional": {},
    },
    "browser_action": {
        "required": {
            "action": str,
        },
        "optional": {
            "url": str,
        },
        "actions": {
            "navigate": [
                "url",
            ],
            "get_text": [],
        },
    },
}


def _validate_path(path: str) -> bool:
    try:
        root = get_workspace_root()
        resolved = (root / path).resolve()
        resolved.relative_to(root)
        return True
    except Exception:
        return False


def validate_tool_call(payload: Any, available_tools: Optional[dict[str, Any]] = None) -> ValidationResult:
    if isinstance(payload, str):
        payload_clean = sanitize(payload)
        try:
            obj = json.loads(payload_clean)
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

    if "arguments" in obj and "args" not in obj:
        obj["args"] = obj.pop("arguments")

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

    schema_dict = available_tools if available_tools is not None else TOOL_SCHEMAS
    schema = schema_dict.get(tool)

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

    if tool == "browser_action":
        action = args.get("action")
        valid_actions = schema["actions"]

        if action not in valid_actions:
            return ValidationResult(
                False,
                None,
                f"Unsupported browser action '{action}'. Must be one of {list(valid_actions.keys())}.",
            )

        for field in valid_actions[action]:
            if field not in args or not args[field]:
                return ValidationResult(
                    False,
                    None,
                    f"Action '{action}' requires non-empty argument '{field}'.",
                )

    if tool == "todo_write":
        todos = args.get("todos", [])
        if not isinstance(todos, list):
            return ValidationResult(False, None, "Argument 'todos' must be a list.")
        for item in todos:
            if not isinstance(item, dict) or "task" not in item or "status" not in item:
                return ValidationResult(False, None, "Each item in 'todos' must have 'task' and 'status'.")
            if item["status"] not in {"pending", "in_progress", "done"}:
                return ValidationResult(False, None, f"Invalid todo status: {item['status']}.")

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
        inner = sanitize(match.group(1), strip_control=True)
        payload = json.loads(inner)
    except json.JSONDecodeError:
        return None

    return _validate_payload(payload)


# ---------------------------------------------------------------------
# Bash Strategy
# ---------------------------------------------------------------------

TOOL_NAMES_IN_CODE: Final[tuple[str, ...]] = (
    "todo_write",
    "file_system",
    "evidence_log",
    "shell",
    "execute_shell",
)


def _is_hallucinated_python_tool_call(cmd: str) -> bool:
    c = cmd.strip()
    if not c.startswith("python "):
        return False
    if "import " in c and "(" in c and ")" in c:
        return True
    if any(
        f" {t}(" in c or f" {t}." in c or c.startswith(f"python {t}.")
        for t in TOOL_NAMES_IN_CODE
    ):
        return True
    return False


def _parse_bash(text: str) -> ToolCall | None:
    match = BASH_PATTERN.search(text)
    if not match:
        return None

    candidate = match.group(1).strip()
    if not candidate:
        return None

    if _is_hallucinated_python_tool_call(candidate):
        return None

    payload = {"tool": "execute_shell", "args": {"command": candidate}}
    res = validate_tool_call(payload)
    if not res.ok or not res.data:
        return None

    return ToolCall(
        tool="execute_shell",
        args={"command": candidate},
    )


# ---------------------------------------------------------------------
# Forgiving parser (small / fallback model hallucinations)
# ---------------------------------------------------------------------
#
# Fallback models frequently bury a real tool call inside markdown essays,
# conversational prose, or legacy Python-style helper calls.  The functions
# below try to recover that call instead of giving up (which would otherwise
# force the casual/verify path).  They are intentionally tolerant — they never
# raise, and they only emit a ToolCall after the strict schema gatekeeper has
# approved it.

_FORGIVING_JSON_FENCE = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)

_LEGACY_SHELL_PATTERN = re.compile(
    r"(?:shell|execute_shell)\s*\(\s*(?:cmd|command)\s*=\s*[\"'](.+?)[\"']\s*\)",
    re.IGNORECASE | re.DOTALL,
)


def extract_first_json_object(text: str) -> str | None:
    """
    Recover a raw JSON object string from a messy response.

    Strategy:
        1. Markdown ```json (or bare ```) fences first.
        2. Otherwise scan for the first balanced ``{...}`` block that contains
           the key ``"tool"`` (or ``'tool'``), which is the signature of a
           tool call emitted in prose.

    Returns the raw JSON string (still needs schema validation) or ``None``.
    """
    if not text:
        return None

    m = _FORGIVING_JSON_FENCE.search(text)
    if m:
        return m.group(1).strip()

    start = text.find("{")
    while start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    if '"tool"' in candidate or "'tool'" in candidate:
                        return candidate
                    break
        start = text.find("{", start + 1)
    return None


def extract_legacy_shell(text: str) -> dict[str, Any] | None:
    """
    Catch legacy ``shell(cmd="...")`` / ``execute_shell(command="...")`` style
    calls that small models emit instead of JSON tool calls.

    Returns a validated-compatible payload dict, or ``None`` if absent.
    """
    m = _LEGACY_SHELL_PATTERN.search(text)
    if not m:
        return None
    return {"tool": "execute_shell", "args": {"command": m.group(1).strip()}}


def _forgiving_json_tool_call(text: str) -> ToolCall | None:
    """Run the forgiving JSON scan and validate through the strict gatekeeper."""
    raw = extract_first_json_object(text)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return _validate_payload(payload)


def _forgiving_legacy_shell(text: str) -> ToolCall | None:
    """Run the legacy-shell scan and validate through the strict gatekeeper."""
    payload = extract_legacy_shell(text)
    if not payload:
        return None
    return _validate_payload(payload)


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
        1. JSON Tool Call (clean ```json fence via strict matcher)
        2. Bash Code Block (with hallucinated Python tool call guard)
        3. Forgiving JSON scan (tool call buried in prose / markdown essay)
        4. Forgiving legacy-shell scan (shell(cmd=...) / execute_shell(command=...))
        5. None  -> caller runs the casual/verify path, never crashes
    """
    if not text or not text.strip():
        return None

    text = normalize(text)

    # Priority 1: JSON tool calls (clean fence)
    result = _parse_json(text)
    if result is not None:
        return result

    # Priority 2: Bash blocks (with hallucinated Python guard)
    result = _parse_bash(text)
    if result is not None:
        return result

    # Priority 3: Forgiving JSON scan — recover a tool call buried in prose.
    result = _forgiving_json_tool_call(text)
    if result is not None:
        return result

    # Priority 4: Legacy shell-style call emitted by small fallback models.
    return _forgiving_legacy_shell(text)
