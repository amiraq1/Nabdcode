"""Centralized UI state system.

Every future widget consumes a UIState (Idle, Thinking, Running, ...) instead of
inventing its own status logic. Each state exposes: semantic color, icon,
spinner type, priority, and an animation profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict

from ui.design.animation import AnimationProfile, Spinner
from ui.design.icons import Icon
from ui.design.theme.color import Color
from ui.design.theme.semantic import SEMANTIC


class UIState(Enum):
    """Canonical UI states (Phase 1+ state vocabulary)."""

    IDLE = auto()
    THINKING = auto()
    PLANNING = auto()
    RUNNING = auto()
    STREAMING = auto()
    WAITING = auto()
    SUCCESS = auto()
    COMPLETED = auto()
    WARNING = auto()
    ERROR = auto()
    CANCELLED = auto()
    LOADING = auto()
    BUSY = auto()
    DISABLED = auto()


@dataclass(frozen=True)
class StateRecord:
    state: UIState
    label: str
    color: Color
    icon: Icon
    spinner: Spinner
    priority: int
    animation_profile: AnimationProfile


_UI_STATES: Dict[UIState, StateRecord] = {
    UIState.IDLE:      StateRecord(UIState.IDLE, "idle",      SEMANTIC.idle,      Icon.IDLE,      Spinner.NONE,     10, AnimationProfile.NONE),
    UIState.THINKING:  StateRecord(UIState.THINKING, "thinking", SEMANTIC.thinking, Icon.THINKING,  Spinner.DOTS,     80, AnimationProfile.THINKING),
    UIState.PLANNING:  StateRecord(UIState.PLANNING, "planning", SEMANTIC.thinking, Icon.PLANNING,  Spinner.BRAILLE,  70, AnimationProfile.PROGRESS),
    UIState.RUNNING:   StateRecord(UIState.RUNNING, "running",  SEMANTIC.running,   Icon.RUNNING,   Spinner.LINE,     90, AnimationProfile.STREAMING),
    UIState.STREAMING: StateRecord(UIState.STREAMING, "streaming", SEMANTIC.running, Icon.STREAMING, Spinner.WAVE,   85, AnimationProfile.STREAMING),
    UIState.WAITING:   StateRecord(UIState.WAITING, "waiting",  SEMANTIC.warning,   Icon.WAITING,   Spinner.ELAPSE,  60, AnimationProfile.PULSE),
    UIState.SUCCESS:   StateRecord(UIState.SUCCESS, "success",  SEMANTIC.success,   Icon.SUCCESS,   Spinner.NONE,     30, AnimationProfile.NONE),
    UIState.COMPLETED: StateRecord(UIState.COMPLETED, "completed", SEMANTIC.success, Icon.CHECK,     Spinner.NONE,     20, AnimationProfile.NONE),
    UIState.WARNING:   StateRecord(UIState.WARNING, "warning",  SEMANTIC.warning,   Icon.WARNING,   Spinner.PULSE,    50, AnimationProfile.PULSE),
    UIState.ERROR:     StateRecord(UIState.ERROR, "error",    SEMANTIC.error,     Icon.ERROR,     Spinner.NONE,    100, AnimationProfile.NONE),
    UIState.CANCELLED: StateRecord(UIState.CANCELLED, "cancelled", SEMANTIC.disabled, Icon.CANCEL,    Spinner.NONE,     40, AnimationProfile.NONE),
    UIState.LOADING:   StateRecord(UIState.LOADING, "loading",  SEMANTIC.accent,    Icon.STREAMING, Spinner.BRAILLE,  65, AnimationProfile.PROGRESS),
    UIState.BUSY:      StateRecord(UIState.BUSY, "busy",     SEMANTIC.running,   Icon.RUNNING,   Spinner.LINE,     88, AnimationProfile.STREAMING),
    UIState.DISABLED:  StateRecord(UIState.DISABLED, "disabled", SEMANTIC.disabled, Icon.IDLE,      Spinner.NONE,     5, AnimationProfile.NONE),
}

UI_STATES: Dict[UIState, StateRecord] = dict(_UI_STATES)


def state_of(state: UIState) -> StateRecord:
    """Resolve a UIState to its full StateRecord."""
    return _UI_STATES[state]
