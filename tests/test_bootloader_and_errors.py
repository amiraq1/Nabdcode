# tests/test_bootloader_and_errors.py
import unittest
from core.errors import (
    NabdError,
    AuthenticationError,
    PermissionDeniedError,
    SandboxExecutionError,
    MCPConnectionError,
    MCPToolCallError,
    StreamTruncationError,
    TastePipelineError,
    ConfigurationError,
    RateLimitExceededError,
    TelemetryExportError,
)
from core.bootloader import NabdBootloader


class TestBootloaderAndErrors(unittest.TestCase):
    def test_10_typed_error_taxonomy(self):
        errors = [
            AuthenticationError("auth fail"),
            PermissionDeniedError("perm fail"),
            SandboxExecutionError("sandbox fail"),
            MCPConnectionError("mcp conn fail"),
            MCPToolCallError("mcp tool fail"),
            StreamTruncationError("stream fail"),
            TastePipelineError("taste fail"),
            ConfigurationError("config fail"),
            RateLimitExceededError("rate fail"),
            TelemetryExportError("telemetry fail"),
        ]
        self.assertEqual(len(errors), 10)
        for err in errors:
            self.assertIsInstance(err, NabdError)
            self.assertIsNotNone(err.code)
            self.assertTrue(str(err))

    def test_bootloader_pipeline(self):
        bootloader = NabdBootloader(telemetry_enabled=True)
        self.assertFalse(bootloader.boot_complete)

        success = bootloader.boot()
        self.assertTrue(success)
        self.assertTrue(bootloader.boot_complete)
        self.assertIn("os", bootloader.fingerprint)
        self.assertIn("python_version", bootloader.fingerprint)


if __name__ == "__main__":
    unittest.main()
