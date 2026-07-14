"""Automatic .env loader with key validation and logging."""
import os
import re
import logging

logger = logging.getLogger("EnvLoader")
KEY_VALIDATOR = re.compile(r'^[A-Z][A-Z0-9_]*$')


def load_env_secure(file_path: str = ".env") -> None:
    for env_path in [os.path.join(os.path.expanduser("~"), ".env"), file_path]:
        if not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as ef:
                for line in ef:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip().strip("'").strip('"')
                    if KEY_VALIDATOR.match(key) and val:
                        if not os.getenv(key):
                            os.environ[key] = val
                    else:
                        logger.warning(f"Malformed or unauthorized env key blocked: {key}")
        except Exception as e:
            logger.error(f"Failed to read env file {env_path}: {e}")


load_env_secure()
