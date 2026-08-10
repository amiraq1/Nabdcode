import os
import shutil

from rich.console import Console
from rich.text import Text
from core.kernel.subprocess_guard import default_guard

# Force .env loading before reading OPENROUTER_MODEL for the banner.
try:
    import core._env  # noqa: F401
except Exception:
    pass

from ui.design.theme.semantic import SEMANTIC

console = Console()


def get_git_repository_name():
    try:
        result = default_guard.run_infra(["git", "rev-parse", "--show-toplevel"], timeout=1)
        if result[0] == 0:
            return os.path.basename(result[1].strip())
    except Exception:
        pass
    return "Local Workspace"


def _classic_logo_lines():
    """Return the original ASCII art lines (kept for the classic option)."""
    return [
        "█▄ █ ▄▀█ █▄▀ █▀▄ █▀▀ █▀█ █▀▄ █▀▀",  # السطر العلوي
        "█ ▀█ █▀█ █▄█ █▄▀ █▄▄ █▄█ █▄▀ ██▄"   # السطر السفلي
    ]


def render_logo(model_name=None, style="minimal"):
    """Render the NABD OS logo.

    style="minimal" (default): a compact world-mark ``◈ agent`` in the
    brand color, followed by the system metadata line.

    style="classic": the original ASCII art banner, preserved verbatim.
    """
    if model_name is None:
        model_name = os.getenv("OPENROUTER_MODEL", "ORCA-FLASH").split("/")[-1]

    repo_name = get_git_repository_name()
    metadata = f"Repo: {repo_name}  •  Model: {model_name}"
    columns, _ = shutil.get_terminal_size()

    # Hard ANSI reset — consistent Termux clear (through Rich)
    console.print("\033c", end="")

    if style == "classic":
        colors = [
            "[bold white]",  # Bold White
            "[grey35]",      # Dark Gray / Gray
        ]
        reset = "[/]"
        for line, color in zip(_classic_logo_lines(), colors):
            padding = max(0, (columns - len(line)) // 2)
            console.print(" " * padding + color + line + reset)
        console.print()
        console.print(metadata.center(columns))
        console.print("-" * columns)
        return

    # ── minimal (default) ──
    brand_style = SEMANTIC.brand.to_rich_style()
    # World mark: ◈ agent  (teal)
    padding = max(0, (columns - len("◈ agent")) // 2)
    mark = Text(" " * padding + "◈ agent", style=brand_style)
    console.print(mark)
    console.print()
    console.print(metadata.center(columns))
    console.print("-" * columns)


# Backwards-compatible alias (main.py calls draw()).
draw = render_logo
print_nabd_logo = render_logo


if __name__ == "__main__":
    render_logo()
