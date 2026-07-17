import logging
from pathlib import Path
from datetime import datetime, timezone


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes on every emit.

    Prevents the "0-byte log" symptom on Android/Termux where a process can be
    killed (SIGTERM/SIGKILL) before Python's buffered writes reach disk. Each
    record is pushed to storage immediately so ``tail -f`` reflects live errors
    even if the agent crashes mid-run.
    """

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self.flush()
        except Exception:
            pass


class Logger:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}.log"
        
        self._logger = logging.getLogger(f"AmmarAgent_{timestamp}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        
        if not self._logger.handlers:
            # Line-buffered, immediate-flush handler (no in-RAM buffering).
            file_handler = _FlushFileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def info(self, msg: str):
        self._logger.info(msg)

    def warning(self, msg: str):
        self._logger.warning(msg)

    def error(self, msg: str):
        self._logger.error(msg)

    def flush(self) -> None:
        """Push any buffered records to disk immediately.

        The backing handler already flushes on every emit (see _FlushFileHandler),
        but this gives callers an explicit, cheap way to force a write — e.g. the
        LLM router calls it after logging a provider failure so a sudden process
        death on Android/Termux never loses the last error.
        """
        for handler in list(self._logger.handlers):
            try:
                handler.flush()
            except Exception:
                pass

    def shutdown(self):
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)
