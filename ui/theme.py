# ui/theme.py
"""Centralized Design System for Nabd OS."""

from typing import Dict
from rich.theme import Theme
from rich.style import Style
from rich import box

# الألوان الأساسية للواجهة مستخرجة من صور نظام التصميم
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

# خريطة الألوان الخاصة بكل فعل (Action) مستخرجة بدقة
ACTION_COLORS: Dict[str, str] = {
    "READ": "#5945B1",        # --purple
    "EDIT": "#5945B1",        # --purple
    "SHELL": "#5945B1",       # --purple
    "SEARCH": "#5945B1",      # --purple
    "TODOS": "#5945B1",       # --purple
    "EXPLORE": "#5945B1",     # --purple
    "THINKING": "#6943FF",    # --agent-violet
    "KILL(shell)": "#5C0112", # --diff-del-bg
    "USER": "#3ecf8e",        # --success
    "SYSTEM": "#9d8cff",      # --accent-violet
}

# 🎨 1. لوحة ألوان النيون (Neon Palette)
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

# 🎭 3. قاموس الأنماط المركزي (Rich Theme)
nabd_theme = Theme({
    # منطقة التفكير (The Thought Box)
    "bento.thought.border": Style(color=MUTED_PURPLE, dim=True),
    "bento.thought.text": Style(color=SILVER_TEXT, italic=True),
    
    # منطقة التنفيذ (The Execution Box)
    "bento.execution.border": Style(color=NEON_CYAN, bold=True),
    "bento.execution.title": Style(color=NEON_CYAN, bold=True, reverse=True),
    
    # منطقة الأدلة (The Evidence Box)
    "bento.evidence.border": Style(color=NEON_MAGENTA),
    "bento.evidence.title": Style(color=NEON_MAGENTA, bold=True),
    
    # منطقة الإجابة النهائية (The Crown Jewel)
    "bento.final.border": Style(color=NEON_LIME, bold=True),
    "bento.final.title": Style(color="black", bgcolor=NEON_LIME, bold=True),
    
    # ألوان أساسية للمحرك
    "system.warning": Style(color="bright_yellow", bold=True),
    "system.error": Style(color="bright_red", bold=True),
})
