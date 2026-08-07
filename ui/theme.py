# ui/theme.py
"""Centralized Design System and Neon-Cyberpunk Theme for NABD OS Terminal UI."""

from rich.theme import Theme
from rich.style import Style
from rich import box

from ui.design.theme.semantic import SEMANTIC

# Selection highlight for keyboard navigation (Phase 1)
SELECTED_COLOR: str = "bright_cyan"

# Footer hint text color (Phase 4)
FOOTER_COLOR: str = "grey50"

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
    "success": SEMANTIC.success.hex,
    "error": SEMANTIC.error.hex,
    "warning": SEMANTIC.warning.hex,
    "info": SEMANTIC.info.hex,
    
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

# ───────────────────────────────────────────────────────
# Prompt HTML fragments (prompt_toolkit) — named Rich styles only, never
# raw hex in source. Consumed by main.py and ui/repl_termux.py so the
# "╭─ Ammar@NabdOS" prompt is defined exactly once.
# ───────────────────────────────────────────────────────

# '╭─ Ammar@NabdOS ~ ' in neon green (semantic prompt accent), bold
PROMPT_HTML_PREFIX: str = (
    "<style fg='green' bold='true'>╭─ Ammar@NabdOS ~ </style>"
)
# '╰─❯ ' in neon cyan (semantic secondary accent), bold
PROMPT_HTML_SUFFIX: str = (
    "<style fg='cyan' bold='true'>╰─❯ </style>"
)
# Placeholder hint text (muted)
PROMPT_HTML_PLACEHOLDER: str = "<style fg='grey'>Ask your question...</style>"
# Horizontal rule (muted)
PROMPT_HTML_HR: str = "<style color='grey'>%s</style>"
