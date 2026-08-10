"""nabd_logo.py — NABD OS startup identity.

BRAND-3: Default mode shows only "◈ agent" in SEMANTIC.brand on black —
no ASCII art, no metadata, no separator.  The classic ASCII logo is
preserved via render_logo("classic").
"""
import os
import shutil

from rich.console import Console
from rich.text import Text
from core.kernel.subprocess_guard import default_guard
from ui.design.theme.semantic import SEMANTIC

# Force .env loading before reading OPENROUTER_MODEL for the banner.
try:
    import core._env  # noqa: F401
except Exception:
    pass

console = Console()


def get_git_repository_name():
    try:
        result = default_guard.run_infra(["git", "rev-parse", "--show-toplevel"], timeout=1)
        if result[0] == 0:
            return os.path.basename(result[1].strip())
    except Exception:
        pass
    return "Local Workspace"


def render_logo(mode: str = "minimal", model_name: str | None = None) -> None:
    """Render the startup identity.

    Args:
        mode: "minimal" (default) — shows only the ◈ agent mark in
              SEMANTIC.brand on black.
              "classic" — shows the original ASCII block art + metadata.
        model_name: Passed to classic mode only.
    """
    if mode == "classic":
        _draw_classic(model_name=model_name)
    else:
        _draw_minimal()


def _draw_minimal() -> None:
    """BRAND-3: minimal identity — ◈ agent in brand teal on black."""
    # Hard ANSI reset — consistent Termux clear (through Rich)
    console.print("\033c", end="")

    mark = Text()
    mark.append("◈ agent", style=f"bold {SEMANTIC.brand}")
    console.print(mark)


def _draw_classic(model_name: str | None = None) -> None:
    """Original ASCII block logo + metadata line + separator."""
    if model_name is None:
        model_name = os.getenv("OPENROUTER_MODEL", "ORCA-FLASH").split("/")[-1]
    logo_lines = [
        "█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀",  # السطر العلوي
        "█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄"   # السطر السفلي
    ]
    colors = [
        "[bold white]",  # Bold White
        "[grey35]",      # Dark Gray / Gray
    ]
    reset = "[/]"

    repo_name = get_git_repository_name()
    metadata = f"Repo: {repo_name}  •  Model: {model_name}"
    columns, _ = shutil.get_terminal_size()

    console.print("\033c", end="")

    for line, color in zip(logo_lines, colors):
        padding = max(0, (columns - len(line)) // 2)
        console.print(" " * padding + color + line + reset)

    console.print()
    console.print(metadata.center(columns))
    console.print("-" * columns)


def draw(model_name=None):
    """Backward-compatible entry point — calls minimal mode."""
    _draw_minimal()


# Aliases
print_nabd_logo = draw

if __name__ == "__main__":
    draw()
