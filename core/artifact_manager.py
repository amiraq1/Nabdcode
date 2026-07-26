"""Artifact Manager — persistent, capped, atomic artifact storage and tool output offloading.

Provides NABD OS with structured artifact tracking, automatic disk retention,
and context protection via intelligent tool output offloading (replacing multi-thousand line
raw tool dumps with scannable summaries linked to persistent artifact files).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _safe_filename(name: str) -> str:
    """Turn a human-readable name into a safe, alphanumeric filename."""
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", name.strip())
    return cleaned[:60] or "artifact"


class ArtifactManager:
    """Thread-safe, atomic manager for structured artifacts and context offloading.

    Attributes:
        root_dir: Directory where artifacts and manifest.json are stored.
        max_inline_chars: Threshold above which tool outputs are automatically offloaded to disk.
        max_total_bytes: Maximum total bytes allowed across all artifacts before pruning older entries.
        max_age_days: Maximum retention age in days before pruning.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        root_dir: Path | str,
        max_inline_chars: int = 1500,
        max_total_bytes: int = 50_000_000,
        max_age_days: int = 30,
    ) -> None:
        self._lock = threading.RLock()
        self.root_dir = Path(root_dir)
        self.data_dir = self.root_dir / "data"
        self.manifest_path = self.root_dir / "manifest.json"
        self.max_inline_chars = max(10, max_inline_chars)
        self.max_total_bytes = max(100, max_total_bytes)
        self.max_age_days = max(1, max_age_days)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            if not self.manifest_path.exists():
                self._atomic_write_manifest({"version": self.SCHEMA_VERSION, "artifacts": {}})
        except Exception:
            pass

    @staticmethod
    def _atomic_write(path: Path, content: str | bytes) -> None:
        tmp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            if isinstance(content, str):
                tmp_path.write_text(content, encoding="utf-8")
            else:
                tmp_path.write_bytes(content)
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise

    def _atomic_write_manifest(self, data: Dict[str, Any]) -> None:
        raw = json.dumps(data, indent=2, ensure_ascii=False)
        self._atomic_write(self.manifest_path, raw)

    def _load_manifest(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_dirs()
            if not self.manifest_path.exists():
                return {"version": self.SCHEMA_VERSION, "artifacts": {}}
            try:
                data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "artifacts" not in data:
                    return {"version": self.SCHEMA_VERSION, "artifacts": {}}
                return data
            except Exception:
                # Fallback on corruption without crashing
                return {"version": self.SCHEMA_VERSION, "artifacts": {}}

    def create_artifact(
        self,
        name: str,
        content: str | bytes,
        category: str = "report",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create and store an artifact, returning its record."""
        with self._lock:
            self._ensure_dirs()
            manifest = self._load_manifest()
            artifacts = manifest.setdefault("artifacts", {})

            # Generate unique ID and path
            ts_compact = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            art_id = f"art_{ts_compact}_{uuid.uuid4().hex[:6]}"
            safe_name = _safe_filename(name)
            file_name = f"{art_id}_{safe_name}"
            file_path = self.data_dir / file_name

            # Write content atomically
            self._atomic_write(file_path, content)
            size = file_path.stat().st_size if file_path.exists() else len(content)

            record = {
                "artifact_id": art_id,
                "name": name,
                "category": category.strip().lower() or "report",
                "created_at": _now_iso(),
                "size_bytes": size,
                "relative_path": f"data/{file_name}",
                "absolute_path": str(file_path.resolve()),
                "metadata": metadata or {},
            }
            artifacts[art_id] = record
            self._atomic_write_manifest(manifest)

            # Auto-prune to enforce caps
            self._prune_locked(manifest)
            return record

    def get_record(self, artifact_id_or_name: str) -> Optional[Dict[str, Any]]:
        """Find an artifact metadata record by ID or exact/latest matching name."""
        with self._lock:
            manifest = self._load_manifest()
            artifacts = manifest.get("artifacts", {})

            # 1. Exact ID match
            if artifact_id_or_name in artifacts:
                return artifacts[artifact_id_or_name]

            # 2. Latest match by exact or safe name
            matches = [
                rec for rec in artifacts.values()
                if rec.get("name") == artifact_id_or_name or _safe_filename(rec.get("name", "")) == _safe_filename(artifact_id_or_name)
            ]
            if matches:
                # Sort newest first
                matches.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                return matches[0]
            return None

    def get_artifact(self, artifact_id_or_name: str) -> Optional[str]:
        """Retrieve the text content of an artifact by ID or name."""
        with self._lock:
            record = self.get_record(artifact_id_or_name)
            if not record:
                return None
            path = Path(record.get("absolute_path", ""))
            if not path.exists():
                # Fallback to relative_path under root_dir
                rel = record.get("relative_path", "")
                if rel:
                    path = self.root_dir / rel
            if path.exists() and path.is_file():
                try:
                    return path.read_text(encoding="utf-8")
                except Exception:
                    try:
                        return path.read_bytes().decode("utf-8", errors="replace")
                    except Exception:
                        return None
            return None

    def list_artifacts(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List stored artifacts sorted newest-first, optionally filtered by category."""
        with self._lock:
            manifest = self._load_manifest()
            artifacts = list(manifest.get("artifacts", {}).values())
            if category:
                cat_lower = category.strip().lower()
                artifacts = [r for r in artifacts if r.get("category", "").lower() == cat_lower]
            artifacts.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return artifacts[:limit]

    def offload_tool_output(
        self,
        tool_name: str,
        raw_output: str,
        task_context: str = "",
        max_inline: Optional[int] = None,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """Intelligently offload tool output to an artifact if it exceeds the inline threshold.

        Returns:
            (inline_text, artifact_record):
            If within limit, returns (raw_output, None).
            If exceeded, saves artifact to disk and returns a concise preview + artifact record.
        """
        threshold = max_inline if max_inline is not None else self.max_inline_chars
        if not raw_output or len(raw_output) <= threshold:
            return raw_output, None

        with self._lock:
            art_name = f"{tool_name}_output.log"
            preview_len = min(400, threshold // 2)
            preview = raw_output[:preview_len].rstrip()
            metadata = {
                "tool": tool_name,
                "task_context": task_context[:100] if task_context else "",
                "original_size": len(raw_output),
            }
            record = self.create_artifact(
                name=art_name,
                content=raw_output,
                category="offload",
                metadata=metadata,
            )
            summary_text = (
                f"[Tool Output Offloaded to Artifact]\n"
                f"Tool: {tool_name} | Artifact ID: `{record['artifact_id']}` ({record['size_bytes']} bytes)\n"
                f"Preview (first {preview_len} chars):\n"
                f"```\n{preview}\n...\n```\n"
                f"(Use get_artifact '{record['artifact_id']}' or inspect '{record['relative_path']}' for full output)"
            )
            return summary_text, record

    def delete_artifact(self, artifact_id_or_name: str) -> bool:
        """Delete an artifact file and remove its manifest entry."""
        with self._lock:
            record = self.get_record(artifact_id_or_name)
            if not record:
                return False
            art_id = record["artifact_id"]
            manifest = self._load_manifest()
            if art_id in manifest.get("artifacts", {}):
                del manifest["artifacts"][art_id]
                self._atomic_write_manifest(manifest)

            # Remove file
            for p_str in (record.get("absolute_path"), str(self.root_dir / record.get("relative_path", ""))):
                if p_str:
                    try:
                        p = Path(p_str)
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass
            return True

    def prune(
        self,
        max_age_days: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
    ) -> int:
        """Explicitly prune older artifacts exceeding age or byte limits. Returns count pruned."""
        with self._lock:
            manifest = self._load_manifest()
            return self._prune_locked(
                manifest,
                max_age_days=max_age_days or self.max_age_days,
                max_total_bytes=max_total_bytes or self.max_total_bytes,
            )

    def _prune_locked(
        self,
        manifest: Dict[str, Any],
        max_age_days: Optional[int] = None,
        max_total_bytes: Optional[int] = None,
    ) -> int:
        age_limit = max_age_days if max_age_days is not None else self.max_age_days
        byte_limit = max_total_bytes if max_total_bytes is not None else self.max_total_bytes
        artifacts: Dict[str, Dict[str, Any]] = manifest.get("artifacts", {})
        if not artifacts:
            return 0

        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=age_limit)

        to_remove: List[str] = []
        # 1. Age pruning
        for art_id, rec in list(artifacts.items()):
            created_str = rec.get("created_at", "")
            try:
                if created_str:
                    created_dt = datetime.datetime.fromisoformat(created_str)
                    if created_dt < cutoff:
                        to_remove.append(art_id)
            except Exception:
                pass

        # 2. Byte cap pruning (remove oldest first when total bytes > limit)
        remaining = [
            (art_id, rec) for art_id, rec in artifacts.items()
            if art_id not in to_remove
        ]
        total_size = sum(r.get("size_bytes", 0) for _, r in remaining)
        if total_size > byte_limit:
            # Sort oldest first
            remaining.sort(key=lambda item: item[1].get("created_at", ""))
            for art_id, rec in remaining:
                if total_size <= byte_limit:
                    break
                to_remove.append(art_id)
                total_size -= rec.get("size_bytes", 0)

        pruned_count = 0
        for art_id in to_remove:
            rec = artifacts.pop(art_id, None)
            if rec:
                pruned_count += 1
                p_str = rec.get("absolute_path")
                if p_str:
                    try:
                        p = Path(p_str)
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass
                p_rel = rec.get("relative_path")
                if p_rel:
                    try:
                        p = self.root_dir / p_rel
                        if p.exists():
                            p.unlink()
                    except Exception:
                        pass

        if pruned_count > 0:
            self._atomic_write_manifest(manifest)
        return pruned_count
