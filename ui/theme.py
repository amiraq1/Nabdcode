# ui/theme.py
"""Centralized Design System for Nabd OS."""

from typing import Dict

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
