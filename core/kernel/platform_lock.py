"""core/kernel/platform_lock.py — Cross-Platform Advisory File Lock.

Provides a unified, reliable file lock abstraction across POSIX, Linux,
Android Termux (fcntl), and Windows (msvcrt).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:
    fcntl = None  # Non-POSIX (e.g. Windows)

try:
    import msvcrt
except ImportError:
    msvcrt = None  # Non-Windows


class LockTimeoutError(TimeoutError):
    """Raised when PlatformFileLock fails to acquire within the timeout."""
    pass


class PlatformFileLock:
    """Cross-platform advisory file lock context manager.

    Parameters
    ----------
    lock_path:
        Path to the lock file.
    timeout:
        Maximum duration (seconds) to wait for lock acquisition.
    poll_interval:
        Interval (seconds) between non-blocking acquisition attempts.
    """

    def __init__(
        self,
        lock_path: str | Path,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._fd: Optional[int] = None
        self._is_locked: bool = False

    def acquire(self, timeout: float | None = None) -> bool:
        """Acquire the lock, polling until timeout expires.

        Returns True on success, or raises LockTimeoutError on timeout.
        """
        if self._is_locked:
            return True

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        max_timeout = self.timeout if timeout is None else timeout
        start_time = time.time()

        # Open file descriptor for locking
        flags = os.O_CREAT | os.O_RDWR
        # Set 0o600 mode on creation
        fd = os.open(str(self.lock_path), flags, 0o600)

        while True:
            try:
                if fcntl is not None:
                    # POSIX / Termux non-blocking exclusive lock
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    self._is_locked = True
                    return True
                elif msvcrt is not None:
                    # Windows non-blocking lock on byte 0
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    self._fd = fd
                    self._is_locked = True
                    return True
                else:
                    # Fallback (no platform lock module): lock held by open fd
                    self._fd = fd
                    self._is_locked = True
                    return True
            except (OSError, IOError, PermissionError):
                if time.time() - start_time >= max_timeout:
                    os.close(fd)
                    raise LockTimeoutError(
                        f"Failed to acquire file lock on '{self.lock_path}' within {max_timeout:.2f}s"
                    )
                time.sleep(self.poll_interval)

    def release(self) -> None:
        """Release the lock and close the file descriptor."""
        if not self._is_locked or self._fd is None:
            return

        fd = self._fd
        self._fd = None
        self._is_locked = False

        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (OSError, IOError):
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    @property
    def is_locked(self) -> bool:
        """Return True if the lock is currently held by this instance."""
        return self._is_locked

    def __enter__(self) -> "PlatformFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()
