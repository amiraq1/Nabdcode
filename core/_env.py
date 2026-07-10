"""Automatic .env loader."""
import os

for _env_path in [os.path.join(os.path.expanduser("~"), ".env"), ".env"]:
    if os.path.exists(_env_path):
        try:
            with open(_env_path, "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _v = _line.split("=", 1)
                        _k = _k.strip()
                        _v = _v.strip().strip("'").strip('"')
                        if _k and not os.getenv(_k):
                            os.environ[_k] = _v
        except Exception:
            pass
