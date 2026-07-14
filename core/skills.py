# core/skills.py
"""
High-Fidelity Agentic Skills Router & Verb Engine for Nabd OS.

Architectural DNA inspired by elite frontier CLI skills (design & agent-browser):
  1. Strict Audit-vs-Fix Split: Audit verbs (/design smell, checkup, review) generate report
     artifacts only and disallow code mutations in the same turn.
  2. 15 Frontend Design Verbs across 5 groups (Audit, Fix, Systems, Compose, Build/Ship).
  3. External CLI Discovery Stub: External binary verification gate (e.g. agent-browser CLI)
     ensuring safe delegation without fallback to unauthorized tools.
  4. Brief Sufficiency Gate: Non-blocking optional brief check.
"""

from __future__ import annotations

import os
import enum
import shutil
from dataclasses import dataclass
from typing import Dict, Final, List, Optional, Set, Any
from core.errors import PermissionDeniedError, ConfigurationError


class SkillExecutionMode(enum.Enum):
    """Execution mode enforcing strict separation of audit vs code mutation."""
    AUDIT = "audit"
    MUTATE = "mutate"


@dataclass(frozen=True)
class SkillVerbMetadata:
    name: str
    group: str
    mode: SkillExecutionMode
    description: str


# The 15 verified Design Sub-Tools across 5 Groups
AUDIT_VERBS: Final[Set[str]] = {"checkup", "smell", "review"}
FIX_VERBS: Final[Set[str]] = {"deslop"}
SYSTEMS_VERBS: Final[Set[str]] = {"typeset", "recolor", "motion", "interaction"}
COMPOSE_VERBS: Final[Set[str]] = {"relayout", "responsive"}
BUILD_SHIP_VERBS: Final[Set[str]] = {
    "redesign",
    "tokenize",
    "setup",
    "finish",
    "refine",
    "voice",
    "surface",
    "create",
}


class ExternalSkillStub:
    """Discovery stub for skills delegating to external CLI binaries (e.g. agent-browser)."""

    def __init__(
        self,
        binary_name: str,
        install_command: str,
        allowed_prefixes: Optional[List[str]] = None,
    ):
        self.binary_name = binary_name
        self.install_command = install_command
        self.allowed_prefixes = allowed_prefixes or [binary_name, f"npx {binary_name}"]

    def is_installed(self) -> bool:
        """Check if binary is available in PATH."""
        return shutil.which(self.binary_name) is not None

    def assert_ready(self) -> bool:
        """Raises ConfigurationError if external CLI is missing, enforcing no-fallback rule."""
        if not self.is_installed():
            raise ConfigurationError(
                f"External skill stub requires '{self.binary_name}'. Install via: '{self.install_command}'"
            )
        return True

    def verify_allowed_tool(self, command_line: str) -> bool:
        """Enforces allowed-tools security gate. Raises PermissionDeniedError if unauthorized."""
        clean = command_line.strip()
        for prefix in self.allowed_prefixes:
            if clean == prefix or clean.startswith(prefix + " "):
                return True
        raise PermissionDeniedError(
            f"Command '{clean}' blocked: external skill stub restricts execution to prefixes: {self.allowed_prefixes}. No fallback allowed."
        )

    def get_workflow_fetch_command(self, domain: str = "core", full: bool = True) -> List[str]:
        """Build argument vector array for pulling live instructions ('agent-browser skills get core --full')."""
        cmd = [self.binary_name, "skills", "get", domain]
        if full:
            cmd.append("--full")
        return cmd


class SkillRouter:
    """Routes slash-commands and skill verbs while enforcing Audit-vs-Fix execution safety gates."""

    def __init__(self):
        self._verbs: Dict[str, SkillVerbMetadata] = {}
        self._register_default_design_verbs()

    def _register_default_design_verbs(self) -> None:
        for verb in AUDIT_VERBS:
            self._verbs[verb] = SkillVerbMetadata(
                name=verb,
                group="Audit",
                mode=SkillExecutionMode.AUDIT,
                description=f"Generate read-only {verb}-report analysis artifact without file mutations.",
            )
        for verb in FIX_VERBS:
            self._verbs[verb] = SkillVerbMetadata(
                name=verb,
                group="Fix",
                mode=SkillExecutionMode.MUTATE,
                description=f"Remove AI slop and apply direct fix for {verb}.",
            )
        for verb in SYSTEMS_VERBS:
            self._verbs[verb] = SkillVerbMetadata(
                name=verb,
                group="Systems",
                mode=SkillExecutionMode.MUTATE,
                description=f"Execute design systems update for {verb}.",
            )
        for verb in COMPOSE_VERBS:
            self._verbs[verb] = SkillVerbMetadata(
                name=verb,
                group="Compose",
                mode=SkillExecutionMode.MUTATE,
                description=f"Execute composition and responsive layout update for {verb}.",
            )
        for verb in BUILD_SHIP_VERBS:
            self._verbs[verb] = SkillVerbMetadata(
                name=verb,
                group="BuildShip",
                mode=SkillExecutionMode.MUTATE,
                description=f"Execute build and ship workflow for {verb}.",
            )

    def parse_verb(self, command: str) -> Optional[SkillVerbMetadata]:
        """Parse command line (e.g. '/design smell' or 'smell') and return verb metadata."""
        if not command:
            return None
        parts = command.strip().split()
        for p in parts:
            clean = p.lstrip("/").lower()
            if clean in self._verbs:
                return self._verbs[clean]
        return None

    def assert_mutation_allowed(self, verb_name: str) -> bool:
        """Raises PermissionDeniedError if the active verb is in AUDIT mode."""
        meta = self._verbs.get(verb_name.lower())
        if meta and meta.mode == SkillExecutionMode.AUDIT:
            raise PermissionDeniedError(
                f"Skill verb '{verb_name}' operates in AUDIT mode: code mutation is forbidden in this turn."
            )
        return True

    @staticmethod
    def check_brief_sufficiency(brief_path: str = ".commandcode/design/brief.md") -> bool:
        """Brief Sufficiency Gate: Checks optional brief existence without blocking."""
        return os.path.exists(brief_path)


@dataclass(frozen=True)
class SkillManifest:
    name: str
    description: str
    path: str
    allowed_tools: List[str]


class SkillLoader:
    """Discovers and parses local SKILL.md prompt-instruction modules (findSkillMdFiles / discoverSkillsLocally)."""

    @staticmethod
    def find_skill_md_files(search_dir: str) -> List[str]:
        """Recursively scan search_dir for SKILL.md files."""
        found = []
        if not os.path.exists(search_dir):
            return found
        for root, _, files in os.walk(search_dir):
            if "SKILL.md" in files:
                found.append(os.path.join(root, "SKILL.md"))
        return found

    @staticmethod
    def parse_skill_frontmatter(file_path: str) -> Optional[SkillManifest]:
        """Parse YAML-like frontmatter from SKILL.md."""
        if not os.path.exists(file_path):
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            return None

        name = "unknown"
        desc = ""
        allowed = []

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1]
                for line in frontmatter.splitlines():
                    clean = line.strip()
                    if clean.startswith("name:"):
                        name = clean.split("name:", 1)[1].strip()
                    elif clean.startswith("description:"):
                        desc = clean.split("description:", 1)[1].strip()
                    elif clean.startswith("allowed-tools:"):
                        raw_tools = clean.split("allowed-tools:", 1)[1].strip()
                        allowed = [t.strip() for t in raw_tools.split(",") if t.strip()]

        return SkillManifest(name=name, description=desc, path=file_path, allowed_tools=allowed)

    @staticmethod
    def load_reference_doc(skill_dir: str, verb_name: str) -> Optional[str]:
        """Load matching references/<verb>.md relative to skill directory."""
        ref_path = os.path.join(skill_dir, "references", f"{verb_name.lower()}.md")
        if not os.path.exists(ref_path):
            return None
        try:
            with open(ref_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None


class ReviewInspector:
    """
    Scored Critique & Design Review Inspector for Nabd OS (references/review.md alignment).
    Evaluates visual spacing, RTL logical properties, and 3-beat reduced motion rules.
    Enforces Report-Only restriction without mutating target code files.
    """

    @staticmethod
    def audit_visual_rhythm(html_content: str) -> Dict[str, Any]:
        """Audit spacing rhythm, RTL logical properties, and reduced-motion compliance."""
        issues = []
        score = 100

        if "margin-left" in html_content or "padding-right" in html_content:
            issues.append(
                "⚠️ Flagged static directional properties. Use CSS Logical Properties (inline-start) for RTL."
            )
            score -= 15

        if "animation" in html_content and "prefers-reduced-motion" not in html_content:
            issues.append(
                "⚠️ Missing reduced-motion media query guarding the 3-beat animation logic."
            )
            score -= 10

        return {"score": max(0, score), "critique": issues}

    def generate_review_report(self, file_path: str, file_content: str) -> str:
        """Generate critique report artifact strictly in REPORT-ONLY mode."""
        audit_results = self.audit_visual_rhythm(file_content)

        report = [
            f"# 📊 DESIGN AUDIT REPORT: {file_path}",
            f"**Overall Compliance Score:** {audit_results['score']}/100",
            "\n## 🔍 Architectural Findings:",
        ]

        if not audit_results["critique"]:
            report.append("✅ Fully verified against the 12-layer visual design gauntlet.")
        else:
            report.extend(audit_results["critique"])

        report.append(
            "\n*NOTE: This turn is strictly REPORT-ONLY. Apply 'redesign' or 'refine' to execute mutations.*"
        )
        return "\n".join(report)


class DeslopInspector:
    """
    AI Slop Detection Engine for Nabd OS (references/deslop.md alignment).
    Flags generic AI-generated design clichés:
      - Blue-violet / indigo gradients signaling nothing.
      - Boilerplate drop-shadows and generic tech hues.
    """

    @staticmethod
    def detect_slop(code_content: str) -> List[str]:
        findings = []
        lower = code_content.lower()
        if "linear-gradient" in lower and ("indigo" in lower or "violet" in lower or "6a5acd" in lower):
            findings.append(
                "⚠️ Detected generic AI tech gradient (indigo/violet). Replace with intentional, domain-specific color story."
            )
        if "box-shadow: 0 4px 6px" in lower or "box-shadow: 0 10px 15px" in lower:
            findings.append(
                "⚠️ Detected boilerplate generic card drop-shadow. Use multi-layered ambient shadow or subtle border."
            )
        return findings


class ColorInspector:
    """
    Color Harmony & OKLCH Inspector for Nabd OS (references/color.md alignment).
    Enforces intentional color palettes and 60-30-10 distribution rules.
    """

    @staticmethod
    def audit_color_palette(css_content: str) -> Dict[str, Any]:
        has_oklch = "oklch(" in css_content.lower()
        issues = []
        score = 100
        if not has_oklch:
            issues.append(
                "💡 Recommendation: Prefer modern OKLCH color space for uniform perceptual lightness."
            )
            score -= 10
        return {"score": max(0, score), "has_oklch": has_oklch, "recommendations": issues}


# ── Phase 6: Native Skills Loader (Declarative Markdown + YAML) ────────────
#
# A declarative skill is a directory under ``<roots>/.nabd/skills`` that
# contains a ``SKILL.md`` file. The skill metadata lives in a YAML block
# delimited by ``+++`` fences (TOML-style frontmatter, but parsed as YAML so
# operators can write either mapping syntax). Example:
#
#     +++
#     name: git-status
#     description: Show the working tree status compactly
#     allowed_tools: ["git", "ls"]
#     command: git status --short
#     context: |
#       Run this before committing.
#     +++
#
# The loader is fully fail-silent: malformed YAML, missing fields, or missing
# directories all yield an empty list / None rather than raising. This keeps
# the zero-trust architecture intact — a bad skill definition simply never
# surfaces.

import re as _re
from pathlib import Path
from dataclasses import field as _field
from typing import List as _List

try:  # PyYAML is a standard dependency; import lazily-guarded for safety.
    import yaml as _yaml
except Exception:  # pragma: no cover — yaml is always present in this env
    _yaml = None


@dataclass
class Skill:
    """A declarative, directory-scoped agent skill.

    Fields:
      • name         — stable identifier used by the ``/skill <name>`` command.
      • description  — human/LLM-readable summary injected into the prompt.
      • allowed_tools — tool patterns granted as explicit ALLOW rules for the
                        duration of execution (merged into shell_permissions).
      • command      — the shell command executed via ShellTool (still subject
                        to Phase 2.1 heuristics inside ShellTool.execute()).
      • context      — free-form guidance surfaced to the model as DATA.
    """

    name: str = ""
    description: str = ""
    allowed_tools: _List[str] = _field(default_factory=list)
    command: str = ""
    context: str = ""
    goal: str = ""
    success_criteria: str = ""

    @property
    def dir(self) -> Optional[str]:  # noqa: D401 - kept for back-compat ergonomics
        return getattr(self, "_dir", None)


# Matches a ``+++ ... +++`` fenced block at the very top of the file.
_FRONTMATTER_RE = _re.compile(r"^\s*\+\+\+(.*?)\+\+\+", _re.DOTALL)


def _coerce_allowed_tools(raw: Any) -> _List[str]:
    """Normalize the ``allowed_tools`` field into a list of strings.

    Accepts a YAML list, a comma/space separated string, or None. Fail-silent:
    anything unparseable degrades to an empty allowlist.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        return [t.strip() for t in raw.replace(",", " ").split() if t.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(t).strip() for t in raw if str(t).strip()]
    return []


def _parse_skill_md(skill_dir: Path) -> Optional[Skill]:
    """Parse a ``SKILL.md`` into a ``Skill`` or None on any failure.

    Fail-silent: missing file, no ``+++`` block, malformed YAML, or a non-mapping
    block all return None so the discovery scan never raises.
    """
    md_path = skill_dir / "SKILL.md"
    if not md_path.is_file():
        return None
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return None

    if _yaml is None:
        return None
    try:
        data = _yaml.safe_load(match.group(1))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    # ``name`` defaults to the directory name when omitted/missing.
    name = str(data.get("name") or skill_dir.name).strip()
    if not name:
        name = skill_dir.name

    skill = Skill(
        name=name,
        description=str(data.get("description") or "").strip(),
        allowed_tools=_coerce_allowed_tools(data.get("allowed_tools")),
        command=str(data.get("command") or "").strip(),
        context=str(data.get("context") or "").strip(),
        goal=str(data.get("goal") or "").strip(),
        success_criteria=str(data.get("success_criteria") or data.get("goal") or "").strip(),
    )
    # Stash the source directory for diagnostics (not part of the public schema).
    object.__setattr__(skill, "_dir", str(skill_dir))
    return skill


def discover_skills(cwd: Path) -> _List[Skill]:
    """Scan the workspace and home ``.nabd/skills`` roots for declared skills.

    Roots (in priority order, workspace first):
      1. ``<cwd>/.nabd/skills``  — project-local, version-controllable skills.
      2. ``<home>/.nabd/skills`` — user-global skills.

    Returns a list of ``Skill`` objects (may be empty). Duplicate names are
    de-duplicated keeping the first (workspace) occurrence. Fully fail-silent:
    unreadable directories or malformed files are skipped individually.
    """
    roots: _List[Path] = []
    try:
        roots.append(Path(cwd).resolve() / ".nabd" / "skills")
    except Exception:
        pass
    try:
        roots.append(Path.home() / ".nabd" / "skills")
    except Exception:
        pass

    result: _List[Skill] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        try:
            subdirs = sorted(p for p in root.iterdir() if p.is_dir())
        except Exception:
            continue
        for sub in subdirs:
            try:
                skill = _parse_skill_md(sub)
            except Exception:
                continue
            if skill is None:
                continue
            if skill.name in seen:
                continue
            seen.add(skill.name)
            result.append(skill)
    return result


def find_skill(skills: _List[Skill], name: str) -> Optional[Skill]:
    """Return the skill whose ``name`` matches (case-insensitive), or None."""
    target = (name or "").strip().lower()
    for skill in skills:
        if skill.name.lower() == target:
            return skill
    return None


def format_skill_context(skills: _List[Skill]) -> str:
    """Render discovered skills into a ``<workspace_skills>`` XML block.

    Returns an empty string when there are no skills, so callers can append the
    result unconditionally without polluting the prompt.
    """
    if not skills:
        return ""
    lines = ["<workspace_skills>"]
    for s in skills:
        tools = ", ".join(s.allowed_tools) if s.allowed_tools else "(none)"
        lines.append(f"- {s.name}: {s.description} [tools: {tools}]")
    lines.append("</workspace_skills>")
    return "\n".join(lines)


def execute_skill(
    skill: Skill,
    state: Any = None,
    evidence_log: Any = None,
    args: str = "",
) -> Any:
    """Execute a skill's command through the hardened ``ShellTool``.

    ``args`` (free-form, e.g. a target file path) is substituted into any
    ``{placeholder}`` tokens in the skill command before execution, so skills
    like ``reviewer`` can be parameterized (``command: python3 ... {target_file}``).
    Substitution is purely textual — the resulting command still flows through
    ``ShellTool.execute()`` and is subject to the Phase 2.1 heuristics, so a
    malicious or obfuscated ``args`` value cannot bypass the security floor.

    Security posture (zero-trust preserved):
      • The skill's ``allowed_tools`` are appended to
        ``RuntimeState.shell_permissions`` as explicit ALLOW rules so the
        PermissionEngine consults them. This is subject to the non-overridable
        Phase 2.1 advanced heuristics, which still run FIRST.
      • The command is dispatched via ``ShellTool.execute()`` — the same code
        path the agent uses — so the Phase 2.1 obfuscation/exfiltration sweep
        (base64/hex/eval blocks) is enforced, and a ``ToolResult`` is produced.
      • If an ``evidence_log`` is supplied, the outcome is recorded into it so
        the run leaves a verifiable trace in the ledger.

    Returns the ``ToolResult`` from ``ShellTool.execute()`` (never raises on
    skill/command failure; only the tool's own error result is returned).
    """
    # 0. Parameterize the command via textual {placeholder} substitution.
    command = skill.command
    if args:
        command = _re.sub(r"\{[^}]+\}", args.strip(), command)

    # 1. Integrate allowed_tools as explicit ALLOW rules for this session.
    if state is not None:
        perms = getattr(state, "shell_permissions", None)
        if perms is not None:
            for tool in skill.allowed_tools:
                try:
                    perms.add_allow(tool)
                except Exception:
                    pass

    # 2. Lazily import ShellTool to avoid a module-load cycle
    #    (tools.shell -> core.security -> core.* ; keep skills import light).
    try:
        from tools.shell import ShellTool
    except Exception:
        from tools.models import ToolResult

        return ToolResult(
            success=False, stderr="ShellTool unavailable.", returncode=-1, status="error"
        )

    result = ShellTool().execute(command=command)

    # 3. Append evidence if a ledger is available.
    if evidence_log is not None:
        try:
            evidence_log.record(
                tool="execute_shell",
                command_or_path=command,
                success=bool(getattr(result, "success", False)),
                output_snippet=getattr(result, "output", "")
                or getattr(result, "stderr", ""),
            )
        except Exception:
            pass

    return result



