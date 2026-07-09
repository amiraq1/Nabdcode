import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

class SessionManager:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.session_id = f"sess_{uuid.uuid4().hex[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        self.messages: List[Dict[str, Any]] = []
        self.file_path = self.root / f"{self.session_id}.json"

    def save(self) -> bool:
        try:
            data = {
                "session_id": self.session_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "messages": self.messages
            }
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            import sys
            print(f"[SessionManager] Failed to save session {self.session_id}: {e}", file=sys.stderr)
            return False

    def load(self, session_id: str) -> bool:
        target_path = self.root / f"{session_id}.json"
        if not target_path.exists():
            return False
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.session_id = data.get("session_id", session_id)
                self.messages = data.get("messages", [])
                self.file_path = target_path
            return True
        except Exception as e:
            import sys
            print(f"[SessionManager] Failed to load session {session_id}: {e}", file=sys.stderr)
            return False

    @staticmethod
    def get_latest_session(root: Path) -> Optional[str]:
        """Return the session_id of the most recent session file, or None."""
        root = Path(root)
        if not root.exists():
            return None
        sess_files = sorted(root.glob("sess_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not sess_files:
            return None
        return sess_files[0].stem

    MAX_SESSIONS: int = 50

    def enforce_retention_policy(self, max_sessions: int = MAX_SESSIONS) -> int:
        """Delete oldest session files beyond max_sessions. Returns number deleted."""
        sess_files = sorted(self.root.glob("sess_*.json"), key=lambda f: f.stat().st_mtime)
        if len(sess_files) <= max_sessions:
            return 0
        to_delete = sess_files[:-max_sessions]
        for f in to_delete:
            f.unlink()
        return len(to_delete)
