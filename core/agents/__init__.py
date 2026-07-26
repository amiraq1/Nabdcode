"""Core agent implementations for the NABD Orchestrator-Workers pipeline.

Each specialized worker (Coder, Verifier) lives in its own module to keep
``core/multi_agent_orchestrator.py`` as a thin Coordinator (Instability <= 0.5).
"""
