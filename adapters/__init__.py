# adapters/__init__.py
"""
Adapters package for Nabd OS.
Provides lightweight, zero-dependency bridges to external services and binaries.
"""
from adapters.lightpanda_adapter import LightpandaAdapter

__all__ = ["LightpandaAdapter"]
