import logging
from pathlib import Path
from datetime import datetime

class Logger:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}.log"
        
        self._logger = logging.getLogger(f"AmmarAgent_{timestamp}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        
        if not self._logger.handlers:
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def info(self, msg: str):
        self._logger.info(msg)

    def warning(self, msg: str):
        self._logger.warning(msg)

    def error(self, msg: str):
        self._logger.error(msg)

    def shutdown(self):
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)
