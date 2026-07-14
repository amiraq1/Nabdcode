"""Stage 1 (Lifecycle) — Automated Skill Scaffolding.

Generates compliant BaseSkill subclasses into the skills/ package so new
capabilities can be bootstrapped without hand-writing boilerplate. All writes
are atomic and guarded so a failed scaffold never corrupts the package or
crashes the OS.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any, Dict


def _to_snake_case(name: str) -> str:
    """Sanitize an arbitrary skill name into a safe snake_case file stem."""
    # Normalize unicode, drop accents, lower-case.
    normalized = unicodedata.normalize("NFKD", name)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = normalized.lower()
    # Replace any non-alphanumeric run with a single underscore.
    spaced = re.sub(r"[^a-z0-9]+", "_", lowered)
    # Strip leading/trailing underscores and collapse doubles.
    stripped = re.sub(r"_+", "_", spaced).strip("_")
    return stripped or "skill"


def _to_pascal_case(stem: str) -> str:
    """Convert a snake_case stem to PascalCase for the class name."""
    return "".join(part[:1].upper() + part[1:] for part in stem.split("_") if part)


_TEMPLATE = '''"""Auto-generated NABD OS skill: {class_name}."""

from typing import Any

from .base_skill import BaseSkill


class {class_name}(BaseSkill):
    """{description}"""

    def __init__(self, mcp_context: Any = None) -> None:
        super().__init__(
            name="{skill_name}",
            description={description!r},
            mcp_context=mcp_context,
        )

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Implement the skill's behavior here.

        The adapter layer may inject the MCP context registry as the
        ``mcp_context`` keyword argument (read-only access to PersistentMemory
        and the active execution session). Query it safely like so:

            ctx = kwargs.get("mcp_context") or getattr(self, "mcp_context", None)
            if ctx is not None:
                # Read-only, best-effort — never rely on it being present.
                focus = ctx.short_term_context        # current session focus
                lessons = ctx.lessons_learned         # past insights
                status = ctx.execution_status         # live session status
                # If the context is missing or raises, fall back gracefully to
                # standard, context-blind execution.
        """
        raise NotImplementedError("Implement {class_name}.execute")
'''


class SkillScaffolder:
    """Scaffolds new skills into the skills/ package."""

    def __init__(self, skills_dir: str = "skills") -> None:
        self.skills_dir = skills_dir

    def create_skill(self, skill_name: str, description: str) -> Dict[str, Any]:
        """Generate and write a compliant BaseSkill subclass.

        Returns:
            {"success": True, "path": "<file>"} on success, or
            {"success": False, "error": "<reason>"} on failure.
        """
        try:
            stem = _to_snake_case(skill_name)
            if not stem:
                return {"success": False, "error": "skill_name sanitized to empty"}
            # Avoid shadowing the package's own base module.
            if stem in ("base_skill", "__init__"):
                return {"success": False, "error": f"reserved name: {stem!r}"}

            class_name = _to_pascal_case(stem) + "Skill"
            file_path = os.path.join(self.skills_dir, f"{stem}.py")

            if os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"file already exists: {file_path}",
                }

            content = _TEMPLATE.format(
                class_name=class_name,
                skill_name=stem,
                description=description,
            )

            os.makedirs(self.skills_dir, exist_ok=True)
            # Atomic write: stage to a temp file, then replace.
            tmp_path = f"{file_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, file_path)

            return {"success": True, "path": file_path}
        except Exception as exc:  # noqa: BLE001 - containment boundary
            return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
