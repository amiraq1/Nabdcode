# core/errors.py
"""
High-Fidelity Typed Exception Taxonomy for Nabd OS.

Architectural DNA inspired by elite frontier CLI error taxonomies (10 typed subclasses):
  Provides explicit failure classification across Auth, Sandbox, MCP, Streams, Telemetry, and Taste.
"""

from __future__ import annotations


class NabdError(Exception):
    """Base exception class for all typed Nabd OS errors."""
    def __init__(self, message: str = "", code: str = "NABD_ERR", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


class AuthenticationError(NabdError):
    """Raised when OAuth, API key, or credential validation fails."""
    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, code="AUTH_ERR", **kwargs)


class PermissionDeniedError(NabdError):
    """Raised when access to a resource, file path, or secure file mode is denied."""
    def __init__(self, message: str = "Permission denied", **kwargs):
        super().__init__(message, code="PERM_DENIED", **kwargs)


class SandboxExecutionError(NabdError):
    """Raised when a command or subshell execution fails within the sandbox containment boundary."""
    def __init__(self, message: str = "Sandbox command execution failed", **kwargs):
        super().__init__(message, code="SANDBOX_ERR", **kwargs)


class MCPConnectionError(NabdError):
    """Raised when connection handshake or transport initialization fails for an MCP server."""
    def __init__(self, message: str = "MCP server connection failed", **kwargs):
        super().__init__(message, code="MCP_CONN_ERR", **kwargs)


class MCPToolCallError(NabdError):
    """Raised when an MCP tool invocation encounters an error or returns a failure status."""
    def __init__(self, message: str = "MCP tool invocation failed", **kwargs):
        super().__init__(message, code="MCP_TOOL_ERR", **kwargs)


class StreamTruncationError(NabdError):
    """Raised when an SSE or network stream terminates prematurely or fails reassembly."""
    def __init__(self, message: str = "Stream truncated unexpectedly", **kwargs):
        super().__init__(message, code="STREAM_TRUNCATED", **kwargs)


class TastePipelineError(NabdError):
    """Raised when taste preference profiling or learning pipeline fails."""
    def __init__(self, message: str = "Taste pipeline processing error", **kwargs):
        super().__init__(message, code="TASTE_ERR", **kwargs)


class ConfigurationError(NabdError):
    """Raised when system configuration or schema validation is invalid."""
    def __init__(self, message: str = "Invalid system configuration", **kwargs):
        super().__init__(message, code="CONFIG_ERR", **kwargs)


class RateLimitExceededError(NabdError):
    """Raised when LLM provider or external service rate limits are hit."""
    def __init__(self, message: str = "Rate limit exceeded", **kwargs):
        super().__init__(message, code="RATE_LIMIT", **kwargs)


class TelemetryExportError(NabdError):
    """Raised when OpenTelemetry batch flushing or telemetry export fails."""
    def __init__(self, message: str = "Telemetry export failed", **kwargs):
        super().__init__(message, code="TELEMETRY_ERR", **kwargs)


__all__ = [
    "NabdError",
    "AuthenticationError",
    "PermissionDeniedError",
    "SandboxExecutionError",
    "MCPConnectionError",
    "MCPToolCallError",
    "StreamTruncationError",
    "TastePipelineError",
    "ConfigurationError",
    "RateLimitExceededError",
    "TelemetryExportError",
]
