"""Session storage — JSONL transcript recording matching TypeScript session/storage.ts.

Provides:
- SessionStorage: write/read JSONL transcripts with metadata
- Atomic writes, content replacement for large tool results
- Flush control, session listing, cleanup
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..types.messages import Message, message_to_dict, message_from_dict

logger = logging.getLogger(__name__)

# Default directories
SESSIONS_DIR = Path.home() / ".clawcodex" / "sessions"
CONTENT_DIR_NAME = "content"

# Thresholds
LARGE_CONTENT_THRESHOLD = 10_000  # 10KB — store separately
DEFAULT_RETENTION_DAYS = 30
MAX_FLUSH_BATCH = 50


@dataclass
class SessionMetadata:
    """Metadata for a session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    start_time: float = field(default_factory=time.time)
    model: str = ""
    cwd: str = ""
    title: str = ""
    total_cost: float = 0.0
    message_count: int = 0
    last_updated: float = field(default_factory=time.time)
    last_user_input: str = ""
    agent_name: str = ""  # S-R4-A: agent type used for the session
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "start_time": self.start_time,
            "model": self.model,
            "cwd": self.cwd,
            "title": self.title,
            "total_cost": self.total_cost,
            "message_count": self.message_count,
            "last_updated": self.last_updated,
            "last_user_input": self.last_user_input,
            "agent_name": self.agent_name,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetadata:
        return cls(
            session_id=data.get("session_id", str(uuid.uuid4())),
            start_time=data.get("start_time", time.time()),
            model=data.get("model", ""),
            cwd=data.get("cwd", ""),
            title=data.get("title", ""),
            total_cost=data.get("total_cost", 0.0),
            message_count=data.get("message_count", 0),
            last_updated=data.get("last_updated", time.time()),
            last_user_input=data.get("last_user_input", ""),
            agent_name=data.get("agent_name", ""),
            tags=data.get("tags", []),
        )


class SessionStorage:
    """JSONL-based session transcript storage."""

    def __init__(
        self,
        session_id: str | None = None,
        sessions_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id or str(uuid.uuid4())
        self.sessions_dir = sessions_dir or SESSIONS_DIR
        self._session_dir = self.sessions_dir / self.session_id
        self._transcript_path = self._session_dir / "transcript.jsonl"
        self._metadata_path = self._session_dir / "metadata.json"
        self._content_dir = self._session_dir / CONTENT_DIR_NAME
        self._write_buffer: list[dict[str, Any]] = []
        self._metadata: SessionMetadata | None = None
        # Set of message uuids already flushed to disk — guards against
        # duplicate transcript lines when ``save_to_session_storage``
        # is called multiple times for the same session (e.g. resume
        # paths, agent loop restarts). Lazy-initialised on first flush
        # from the on-disk transcript so a resumed session inherits
        # the de-dup baseline instead of re-appending everything.
        self._flushed_uuids: set[str] | None = None

    @property
    def session_dir(self) -> Path:
        return self._session_dir

    # --- Metadata ---

    def init_metadata(
        self,
        *,
        model: str = "",
        cwd: str = "",
        title: str = "",
        tags: list[str] | None = None,
    ) -> SessionMetadata:
        """Initialize session metadata.

        Idempotent: when ``metadata.json`` already exists on disk
        (e.g. a resumed session or a second ``save_to_session_storage``
        call for the same session_id), the existing ``start_time`` is
        preserved instead of being overwritten with ``time.time()``.
        The same applies to the on-disk ``message_count`` and
        ``last_updated`` — only the caller-supplied fields are written.
        This prevents the clock-skew class of bugs where re-saving a
        session moves its start_time later than the messages it
        contains (see visualizer screenshot repro for
        ``02cba64e-…``).
        """
        existing = self._load_metadata()
        if existing is not None:
            # Preserve wall-clock anchors from disk; refresh the
            # caller-supplied identity fields only.
            if model:
                existing.model = model
            if cwd:
                existing.cwd = cwd
            if title:
                existing.title = title
            if tags:
                existing.tags = tags
            self._metadata = existing
            self._save_metadata()
            return existing
        self._metadata = SessionMetadata(
            session_id=self.session_id,
            model=model,
            cwd=cwd,
            title=title,
            tags=tags or [],
        )
        self._save_metadata()
        return self._metadata

    def get_metadata(self) -> SessionMetadata | None:
        """Get cached or loaded metadata."""
        if self._metadata is not None:
            return self._metadata
        return self._load_metadata()

    def update_metadata(self, **kwargs: Any) -> None:
        """Update metadata fields."""
        meta = self.get_metadata()
        if meta is None:
            return
        for key, value in kwargs.items():
            if hasattr(meta, key):
                setattr(meta, key, value)
        meta.last_updated = time.time()
        self._save_metadata()

    def _save_metadata(self) -> None:
        if self._metadata is None:
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self._metadata_path, json.dumps(self._metadata.to_dict(), indent=2))

    def _load_metadata(self) -> SessionMetadata | None:
        if not self._metadata_path.exists():
            return None
        try:
            data = json.loads(self._metadata_path.read_text(encoding="utf-8"))
            self._metadata = SessionMetadata.from_dict(data)
            return self._metadata
        except Exception as e:
            logger.debug("Failed to load metadata: %s", e)
            return None

    # --- Transcript writing ---

    def write_message(self, message: Message) -> None:
        """Write a message to the transcript buffer."""
        msg_dict = message_to_dict(message)
        msg_dict = self._replace_large_content(msg_dict)
        self._write_buffer.append(msg_dict)
        if len(self._write_buffer) >= MAX_FLUSH_BATCH:
            self.flush()

    def write_raw(self, data: dict[str, Any]) -> None:
        """Write raw dict to transcript buffer."""
        self._write_buffer.append(data)
        if len(self._write_buffer) >= MAX_FLUSH_BATCH:
            self.flush()

    def flush(self) -> None:
        """Flush buffered messages to disk.

        Dedupes by message ``uuid``: if a buffered entry's uuid was
        already flushed (either this session's buffer or the on-disk
        transcript), it is skipped. This prevents the transcript
        doubling seen when ``save_to_session_storage`` is invoked
        twice for the same session — the second call would otherwise
        re-append the entire conversation, producing the duplicate
        lines visible in screenshot repro
        (transcript.jsonl lines 1-6 == 7-12, identical uuids).
        """
        if not self._write_buffer:
            return
        # Lazy-init the seen-uuid set from the on-disk transcript so
        # resumed sessions don't restart from an empty baseline.
        if self._flushed_uuids is None:
            self._flushed_uuids = self._scan_flushed_uuids()
        # Filter buffer, preserving order, and track newly-flushed ids.
        to_write: list[dict[str, Any]] = []
        for entry in self._write_buffer:
            uuid = entry.get("uuid") if isinstance(entry, dict) else None
            if uuid and uuid in self._flushed_uuids:
                continue
            to_write.append(entry)
            if uuid:
                self._flushed_uuids.add(uuid)
        if not to_write:
            self._write_buffer.clear()
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        with open(self._transcript_path, "a", encoding="utf-8") as f:
            for entry in to_write:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        count = len(to_write)
        self._write_buffer.clear()

        # Update metadata message count
        if self._metadata:
            self._metadata.message_count += count
            self._metadata.last_updated = time.time()
            self._save_metadata()

    def _scan_flushed_uuids(self) -> set[str]:
        """Walk the on-disk transcript and collect already-flushed uuids.

        Tolerant of malformed lines (mirrors ``read_transcript``) so
        a corrupt trailing write doesn't poison the dedup baseline.
        """
        seen: set[str] = set()
        if not self._transcript_path.exists():
            return seen
        try:
            with open(self._transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict):
                        uuid = entry.get("uuid")
                        if isinstance(uuid, str) and uuid:
                            seen.add(uuid)
        except OSError:
            return seen
        return seen

    # --- Content replacement ---

    def _replace_large_content(self, msg_dict: dict[str, Any]) -> dict[str, Any]:
        """Replace large tool result content with file references."""
        content = msg_dict.get("content")
        if not isinstance(content, list):
            return msg_dict

        replaced = False
        new_content = []
        for block in content:
            if not isinstance(block, dict):
                new_content.append(block)
                continue

            if block.get("type") == "tool_result":
                inner = block.get("content", "")
                if isinstance(inner, str) and len(inner) > LARGE_CONTENT_THRESHOLD:
                    ref_id = str(uuid.uuid4())
                    self._store_content(ref_id, inner)
                    block = dict(block)
                    block["content"] = f"[content stored: {ref_id}]"
                    block["_content_ref"] = ref_id
                    replaced = True

            new_content.append(block)

        if replaced:
            msg_dict = dict(msg_dict)
            msg_dict["content"] = new_content
        return msg_dict

    def _store_content(self, ref_id: str, content: str) -> None:
        """Store large content to a separate file."""
        self._content_dir.mkdir(parents=True, exist_ok=True)
        path = self._content_dir / f"{ref_id}.txt"
        path.write_text(content, encoding="utf-8")

    def load_content(self, ref_id: str) -> str | None:
        """Load stored content by reference ID."""
        path = self._content_dir / f"{ref_id}.txt"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    # --- Transcript reading ---

    def read_transcript(self) -> list[dict[str, Any]]:
        """Read all entries from the JSONL transcript."""
        if not self._transcript_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(self._transcript_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as e:
                    logger.warning("Malformed JSONL line %d: %s", line_num, e)
        return entries

    def read_messages(self) -> list[Message]:
        """Read transcript as typed Message objects."""
        entries = self.read_transcript()
        messages: list[Message] = []
        for entry in entries:
            try:
                messages.append(message_from_dict(entry))
            except Exception as e:
                logger.warning("Failed to parse message: %s", e)
        return messages

    # --- Session listing & cleanup ---

    @classmethod
    def list_sessions(
        cls,
        sessions_dir: Path | None = None,
        *,
        limit: int = 50,
        tag_filter: str | None = None,
    ) -> list[SessionMetadata]:
        """List recent sessions sorted by last_updated descending.

        When tag_filter is set, only sessions whose tags list contains
        any entry starting with tag_filter are returned.
        """
        base = sessions_dir or SESSIONS_DIR
        if not base.exists():
            return []

        sessions: list[SessionMetadata] = []
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            meta_path = entry / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                meta = SessionMetadata.from_dict(data)
                if tag_filter is not None:
                    if not any(t.startswith(tag_filter) for t in meta.tags):
                        continue
                sessions.append(meta)
            except Exception:
                continue

        sessions.sort(key=lambda s: s.last_updated, reverse=True)
        return sessions[:limit]

    @classmethod
    def cleanup_sessions(
        cls,
        sessions_dir: Path | None = None,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> int:
        """Delete sessions older than retention_days. Returns count deleted."""
        base = sessions_dir or SESSIONS_DIR
        if not base.exists():
            return 0

        cutoff = time.time() - (retention_days * 86400)
        deleted = 0

        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            meta_path = entry / "metadata.json"
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    last_updated = data.get("last_updated", 0)
                    if last_updated < cutoff:
                        shutil.rmtree(entry, ignore_errors=True)
                        deleted += 1
                        continue
                except Exception:
                    pass
            else:
                # No metadata — check directory mtime
                try:
                    if entry.stat().st_mtime < cutoff:
                        shutil.rmtree(entry, ignore_errors=True)
                        deleted += 1
                except Exception:
                    pass

        return deleted

    def delete(self) -> None:
        """Delete this session's directory."""
        if self._session_dir.exists():
            shutil.rmtree(self._session_dir, ignore_errors=True)


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically via temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
