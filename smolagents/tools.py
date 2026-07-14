"""Smolagents tools package for Nabd Agent OS."""

from __future__ import annotations

from typing import Any, Dict


class Tool:
    """Base class for smolagents Tool wrapper."""
    name: str = ""
    description: str = ""
    inputs: Dict[str, Any] = {}
    output_type: str = "string"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def forward(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class FinalAnswerTool(Tool):
    """Provides a final answer to the given task or problem."""

    name = "final_answer"
    description = "Provides a final answer to the given problem."
    inputs = {
        "answer": {
            "type": "string",
            "description": "The final answer to the problem.",
        }
    }
    output_type = "string"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def forward(self, answer: Any = "", *args: Any, **kwargs: Any) -> str:
        if args and not answer:
            return str(args[0])
        return str(answer)

    def __call__(self, answer: Any = "", *args: Any, **kwargs: Any) -> str:
        return self.forward(answer, *args, **kwargs)
