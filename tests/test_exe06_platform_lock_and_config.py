#!/usr/bin/env python3
"""
tests/test_exe06_platform_lock_and_config.py — PlatformFileLock & ConfigManager Tests
=====================================================================================
Validates EXE-06 requirements:
  1. Cross-platform PlatformFileLock provides exclusive mutual exclusion.
  2. Lock timeout handling raises LockTimeoutError cleanly without hang.
  3. ConfigManager atomic persistence eliminates TOCTOU permission windows.
  4. Concurrent writes to ConfigManager produce consistent, uncorrupted state.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.config import ConfigManager
from core.kernel.platform_lock import LockTimeoutError, PlatformFileLock


class TestPlatformLockAndConfig(unittest.TestCase):
    """Test suite for PlatformFileLock and ConfigManager atomic operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="nabd_lock_test_")
        self.config_dir = Path(self.tmpdir) / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.config_dir / "test.lock"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_platform_file_lock_mutual_exclusion(self):
        """When Lock 1 is held, Lock 2 cannot acquire and raises LockTimeoutError."""
        lock1 = PlatformFileLock(self.lock_path, timeout=1.0)
        lock2 = PlatformFileLock(self.lock_path, timeout=0.2)

        # 1. Lock 1 acquires
        self.assertTrue(lock1.acquire())
        self.assertTrue(lock1.is_locked)

        # 2. Lock 2 attempts to acquire and must time out
        with self.assertRaises(LockTimeoutError):
            lock2.acquire()

        self.assertFalse(lock2.is_locked)

        # 3. Lock 1 releases
        lock1.release()
        self.assertFalse(lock1.is_locked)

        # 4. Lock 2 can now acquire
        self.assertTrue(lock2.acquire())
        self.assertTrue(lock2.is_locked)
        lock2.release()

    def test_platform_file_lock_context_manager(self):
        """PlatformFileLock works reliably with python context manager syntax."""
        with PlatformFileLock(self.lock_path, timeout=1.0) as lock:
            self.assertTrue(lock.is_locked)

        self.assertFalse(lock.is_locked)

    def test_config_manager_atomic_save_and_load(self):
        """ConfigManager atomically persists and transparently loads encrypted keys."""
        mgr = ConfigManager(config_dir=self.config_dir)

        mgr.set_api_key("openrouter", "sk-or-v1-testkey123")
        mgr.set_api_key("anthropic", "sk-ant-testkey456")

        # Verify on-disk file contains encrypted representation (ciphertext)
        raw_text = (self.config_dir / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("sk-or-v1-testkey123", raw_text)
        self.assertNotIn("sk-ant-testkey456", raw_text)

        # Verify in-memory retrieval decrypts correctly
        self.assertEqual(mgr.get_api_key("openrouter"), "sk-or-v1-testkey123")
        self.assertEqual(mgr.get_api_key("anthropic"), "sk-ant-testkey456")
        all_keys = mgr.get_all_api_keys()
        self.assertEqual(all_keys["openrouter"], "sk-or-v1-testkey123")
        self.assertEqual(all_keys["anthropic"], "sk-ant-testkey456")

    def test_config_manager_concurrent_writes(self):
        """Concurrent threads writing to ConfigManager do not corrupt json data."""
        mgr = ConfigManager(config_dir=self.config_dir)
        thread_count = 8
        errors = []

        def _worker(idx: int):
            try:
                mgr.set_api_key(f"provider_{idx}", f"secret_token_{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

        # Verify all keys exist without corruption
        all_keys = mgr.get_all_api_keys()
        self.assertEqual(len(all_keys), thread_count)
        for i in range(thread_count):
            self.assertEqual(all_keys.get(f"provider_{i}"), f"secret_token_{i}")


if __name__ == "__main__":
    unittest.main()
