# ui/theme.py
"""Centralized Design System and Neon-Cyberpunk Theme for NABD OS Terminal UI."""

from typing import Dict
from rich.theme import Theme
from rich.style import Style
from rich import box

# ───────────────────────────────────────────────────────
# Existing & Core Palette Definitions
# ───────────────────────────────────────────────────────

COLORS: Dict[str, str] = {
    "background": "#000000",        # --bg
    "surface": "#0a0a0a",           # --bg-elevated
    "primary": "#5945B1",           # --purple (شارات EDIT / READ / SHELL / SEARCH / TODOS)
    "primary_dim": "#4a3a94",       # --purple-dim
    "agent_violet": "#6943FF",      # --agent-violet
    "success": "#3ecf8e",           # --success
    "warning": "#e0b23c",           # pending/warning
    "danger": "#e0524a",            # error glyph
    "error": "#e0524a",             # error glyph
    "text_main": "#f2f2f2",         # --text-primary
    "text_muted": "#7a7a7a",        # --text-dim
    "text_dim": "#4d4d4d",          # --text-faint
    "accent_cyan": "#6fd3d6",       # --accent-cyan
    "accent_violet": "#9d8cff",     # --accent-violet
    "diff_add_bg": "#04473A",       # --diff-add-bg
    "diff_add_fg": "#4CC88E",       # --diff-add-fg
    "diff_del_bg": "#5C0112",       # --diff-del-bg
    "diff_del_fg": "#E16B7A",       # --diff-del-fg
    "border": "#1a1a1a",
}

ACTION_COLORS: Dict[str, str] = {
    "READ": "#0891B2",        # ice blue / teal (cyan-600)
    "EDIT": "#0891B2",        # ice blue / teal
    "SHELL": "#0891B2",       # ice blue / teal
    "SEARCH": "#0891B2",      # ice blue / teal
    "TODOS": "#0891B2",       # ice blue / teal
    "EXPLORE": "#0891B2",     # ice blue / teal
    "GIT": "#059669", # dark green / emerald
    "FINAL ANSWER": "#7C3AED", # violet / purple
    "WARNING": "#D97706",     # orange
    "THINKING": "#6943FF",    # --agent-violet
    "KILL(shell)": "#5C0112", # --diff-del-bg
    "USER": "#0891B2",        # ice blue / teal
    "SYSTEM": "#9d8cff",      # --accent-violet
}

# 🎨 1. لوحة ألوان النيون (Neon Palette)
PALETTE = {
    # Core neon colors
    "neon_green": "#00ff9d",
    "neon_cyan": "#00fff7", 
    "neon_purple": "#bf5af2",
    "neon_pink": "#ff2d95",
    "neon_amber": "#ffcc00",
    "neon_blue": "#00a8ff",
    
    # Semantic colors
    "success": "#00ff9d",
    "error": "#ff3333",
    "warning": "#ffcc00",
    "info": "#00fff7",
    
    # Backgrounds
    "panel_bg": "#0d1117",      # GitHub dark
    "panel_border": "#30363d",
    "prompt_bg": "#161b22",
}

NEON_CYAN = "bright_cyan"
NEON_MAGENTA = "bright_magenta"
NEON_LIME = "bright_green"
MUTED_PURPLE = "medium_purple4"
SILVER_TEXT = "grey82"

# 📐 2. أنماط الإطارات (Bento Box Borders)
BOX_THOUGHT = box.ROUNDED
BOX_EXECUTION = box.HEAVY_EDGE
BOX_EVIDENCE = box.MINIMAL_DOUBLE_HEAD
BOX_FINAL = box.DOUBLE

# ───────────────────────────────────────────────────────
# Panel Styles (Box variations)
# ───────────────────────────────────────────────────────

PANEL_STYLES = {
    "tool_start": {
        "border_style": "neon_cyan",
        "title": "[bold neon_cyan]▶ TOOL START[/bold neon_cyan]",
        "padding": (0, 1),
    },
    "tool_complete": {
        "border_style": "neon_green", 
        "title": "[bold neon_green]✓ TOOL COMPLETE[/bold neon_green]",
        "padding": (0, 1),
    },
    "final_answer": {
        "border_style": "neon_purple",
        "title": "[bold neon_purple]◆ FINAL ANSWER[/bold neon_purple]",
        "padding": (1, 2),
    },
    "error": {
        "border_style": "bold red",
        "title": "[bold red]✖ ERROR ENGINE[/bold red]",
        "padding": (1, 2),
    },
    "warning": {
        "border_style": "neon_amber",
        "title": "[bold neon_amber]⚠ WARNING[/bold neon_amber]",
        "padding": (1, 2),
    },
    "search_results": {
        "border_style": "neon_amber",
        "title": "[bold neon_amber]🔍 SEARCH RESULTS[/bold neon_amber]",
        "padding": (0, 1),
    },
}

# ───────────────────────────────────────────────────────
# Rich Theme Instance (CUSTOM_THEME & nabd_theme combined)
# ───────────────────────────────────────────────────────

CUSTOM_THEME = Theme({
    # Neon variants
    "neon_green": Style(color=PALETTE["neon_green"], bold=True),
    "neon_cyan": Style(color=PALETTE["neon_cyan"], bold=True),
    "neon_purple": Style(color=PALETTE["neon_purple"], bold=True),
    "neon_pink": Style(color=PALETTE["neon_pink"], bold=True),
    "neon_amber": Style(color=PALETTE["neon_amber"], bold=True),
    "neon_blue": Style(color=PALETTE["neon_blue"], bold=True),
    "white": Style(color="#ffffff"),
    
    # Status badges
    "success": Style(color=PALETTE["success"], bold=True),
    "error": Style(color=PALETTE["error"], bold=True),
    "warning": Style(color=PALETTE["warning"], bold=True),
    "info": Style(color=PALETTE["info"], bold=True),
    
    # UI elements
    "prompt": Style(color=PALETTE["neon_green"], bold=True),
    "thought": Style(color=PALETTE["neon_cyan"], dim=True),
    "todo_item": Style(color=PALETTE["neon_pink"]),

    # Bento Box legacy definitions
    "bento.thought.border": Style(color=MUTED_PURPLE, dim=True),
    "bento.thought.text": Style(color=SILVER_TEXT, italic=True),
    "bento.execution.border": Style(color=NEON_CYAN, bold=True),
    "bento.execution.title": Style(color=NEON_CYAN, bold=True, reverse=True),
    "bento.evidence.border": Style(color=NEON_MAGENTA),
    "bento.evidence.title": Style(color=NEON_MAGENTA, bold=True),
    "bento.final.border": Style(color=NEON_LIME, bold=True),
    "bento.final.title": Style(color="black", bgcolor=NEON_LIME, bold=True),
    "system.warning": Style(color="bright_yellow", bold=True),
    "system.error": Style(color="bright_red", bold=True),
})

# Backward compatibility alias
nabd_theme = CUSTOM_THEME

# ───────────────────────────────────────────────────────
# Prompt Styling (prompt_toolkit)
# ───────────────────────────────────────────────────────

PROMPT_STYLE = {
    "prompt": [
        ("class:prompt", "╭─ Ammar@NabdOS ~ "),
    ],
    "continuation": [
        ("class:prompt", "│ "),
    ],
}
