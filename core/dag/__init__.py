# core/dag/ — Decoupled DAG execution engine package.
#
# ARCHITECTURAL CONSTRAINT (Phase 6 DI / Kernel Island):
#   This __init__.py MUST remain EMPTY of re-exports. Barrel re-exports
#   would re-create the strongly-connected-component (SCC) cycle.
#   Every consumer imports directly from the canonical module:
#
#     from core.dag.context import NabdExecutionContext
#     from core.dag.base import Edge, BaseNode
#
