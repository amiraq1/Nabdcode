# core/kernel/ — Decoupled leaf modules for breaking the SCC cycle.
#
# ARCHITECTURAL CONSTRAINT (Phase 6 DI):
#   This __init__.py MUST remain EMPTY. Barrel re-exports (e.g.
#   ``from core.kernel.errors import NabdError`` at the package level)
#   would re-create the strongly-connected-component cycle we are trying
#   to break.  Every consumer imports directly from the canonical module:
#
#     from core.kernel.errors import NabdError
#     from core.kernel.events  import EventBus, bus
#
