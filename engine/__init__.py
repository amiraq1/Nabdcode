# Engine package initialization
from engine.deep_agent import classify_intent

__all__ = ["classify_intent", "ExecutionLoop"]


def __getattr__(name):
    # Lazy import to avoid a circular import with engine.loop (which imports
    # the split-out mixin modules that transitively trigger this package init).
    if name == "ExecutionLoop":
        from engine.loop import ExecutionLoop as _ExecutionLoop
        return _ExecutionLoop
    raise AttributeError(f"module 'engine' has no attribute {name!r}")
