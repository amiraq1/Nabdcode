from __future__ import annotations

from typing import Any, Iterable

# Artificial termination tool for native FC. final_answer is NOT a real
# executable tool (it is intercepted by the loop and terminates the run), but
# without it in the FC schema the model has no way to "call" termination and
# will loop on exploration tools (e.g. file_system list) until the step ceiling.
# The loop's _extract_final_answer() already parses {"tool":"final_answer",
# "args":{"answer": ...}} — so routing is automatic once it is offered in the
# schema.
FINAL_ANSWER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "final_answer",
        "description": (
            "Conclude the task. Put the COMPLETE answer/report as clean Markdown "
            "in `answer`. Call this once evidence is gathered and verified — do NOT "
            "end by calling an exploration tool (file_system/list/read)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "description": "The final Markdown report."}
            },
            "required": ["answer"],
        },
    },
}


def build_openai_tools(
    registry: Any,
    exclude: Iterable[str] | None = None,
    allowed: Iterable[str] | None = None,
) -> list[dict]:
    """Build an OpenAI-style ``tools`` array from the tool registry.

    • exclude: tool names to omit (e.g. {"execute_shell"} for the Orchestrator).
    • allowed: if given, ONLY these names are included.
    Uses each tool's Pydantic args_schema when present; otherwise a permissive
    schema (the model relies on the tool description for argument shapes).
    """
    exclude = set(exclude or ())
    allowed_set = set(allowed) if allowed is not None else None
    tools: list[dict] = []
    try:
        items = list(registry)  # ToolRegistry.__iter__ -> (name, tool)
    except Exception:
        items = []
    for entry in items:
        try:
            name, tool = entry
        except Exception:
            continue
        if name in exclude:
            continue
        if allowed_set is not None and name not in allowed_set:
            continue
        params = {"type": "object", "properties": {}, "additionalProperties": True}
        schema = getattr(tool, "args_schema", None)
        if schema is not None and hasattr(schema, "model_json_schema"):
            try:
                params = schema.model_json_schema()
            except Exception:
                pass
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (getattr(tool, "description", "") or "")[:1024],
                    "parameters": params,
                },
            }
        )
    # Always offer final_answer for clean termination — it is intercepted by the
    # loop, not executed. Append AFTER the filter loop so an `allowed` whitelist
    # can never strip it (the model must always be able to stop). Only honor an
    # explicit exclude so a caller can opt out if needed.
    if "final_answer" not in exclude:
        tools.append(FINAL_ANSWER_SCHEMA)
    return tools
