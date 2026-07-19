# core/dag/nodes/ — Specialized DAG pipeline node implementations.
#
# ARCHITECTURAL CONSTRAINT (Phase 6 DI / Kernel Island):
#   This __init__.py MUST remain EMPTY of re-exports. Every consumer imports
#   directly from canonical node modules:
#
#     from core.dag.nodes.sentinel import SentinelNode
#
