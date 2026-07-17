# engine/events.py — BRIDGE (Phase 6 DI)
#
# Backward-compatible re-export shim.  The canonical EventBus
# now lives at ``core/kernel/events.py``.  This file is preserved so
# every existing ``from engine.events import bus`` keeps working
# without editing 25+ files in one commit.
#
# NEW CODE should import directly from the canonical module:
#
#   from core.kernel.events import EventBus, bus
#

from core.kernel.events import EventBus, bus

__all__ = [
    "EventBus",
    "bus",
]
