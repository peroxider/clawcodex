"""Context collection for Intent Forecast."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawcodex_ext.intent_forecast.config import IntentForecastConfig
from clawcodex_ext.intent_forecast.learning import read_recent_feedback
from clawcodex_ext.session_intelligence.queue import enqueue_summary_job


MEMORY_FILENAMES = ("CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "CLUDE.md")


@dataclass(frozen=True)
class ForecastContext:
    cwd: str
    current_messages: list[dict[str, str]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    memory_files: list[dict[str, str]] = field(default_factory=list)
    workspace: dict[str, Any] = field(default_factory=dict)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    response_language: str = "English"
    fingerprint: str = ""

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "cwd": self.cwd,
            "current_messages": self.current_messages,
            "sessions": self.sessions,
            "memory_files": self.memory_files,
            "workspace": self.workspace,
            "feedback": self.feedback,
            "response_language": self.response_language,
        }


class IntentForecastContextBuilder:
    def __init__(
        self,
        *,
        conversation: Any | None,
        workspace_root: Path,
        config: IntentForecastConfig | None = None,
        sessions_dir: Path | None = None,
        feedback_base_dir: Path | None = None,
    ) -> None:
        self.conversation = conversation
        self.workspace_root = Path(workspace_root)
        self.config = config or IntentForecastConfig()
        self.sessions_dir = sessions_dir
        self.feedback_base_dir = feedback_base_dir

    def build(self) -> ForecastContext:
        current = self._current_messages()
        sessions = self._sessions()
        memory = self._memory_files()
        workspace = self._workspace_signals()
        feedback = read_recent_feedback(limit=30, base_dir=self.feedback_base_dir)
        response_language = infer_response_language(current, sessions)
        raw = json.dumps(
            {
                "cwd": str(self.workspace_root),
                "current": current,
                "sessions": sessions,
                "memory": memory,
                "workspace": workspace,
                "response_language": response_language,
            },
            sort_keys=True,
            default=str,
        )
        return ForecastContext(
            cwd=str(self.workspace_root),
            current_messages=current,
            sessions=sessions,
            memory_files=memory,
            workspace=workspace,
            feedback=feedback,
            response_language=response_language,
            fingerprint=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        )

    def _current_messages(self) -> list[dict[str, str]]:
        messages = list(getattr(self.conversation, "messages", []) or [])
        out: list[dict[str, str]] = []
        for msg in messages[-self.config.max_transcript_tail_messages :]:
            role = str(getattr(msg, "role", "") or "")
            if role not in {"user", "assistant", "system"}:
                continue
            text = _flatten_content(getattr(msg, "content", "")).strip()
            if text:
                out.append({"role": role, "content": text[:1200]})
        return out

    def _sessions(self) -> list[dict[str, Any]]:
        try:
            from src.services.session_storage import SessionStorage

            metas = SessionStorage.list_sessions(self.sessions_dir, limit=self.config.max_sessions)
        except Exception:
            return []
        rows: list[dict[str, Any]] = []
        for meta in metas:
            row = {
                "session_id": getattr(meta, "session_id", ""),
                "title": getattr(meta, "title", ""),
                "model": getattr(meta, "model", ""),
                "last_user_input": getattr(meta, "last_user_input", ""),
                "last_updated": getattr(meta, "last_updated", 0),
                "tags": list(getattr(meta, "tags", []) or []),
            }
            summary = self._load_session_summary(str(row["session_id"]))
            if summary:
                row["summary"] = summary
            else:
                tail = self._load_transcript_tail(str(row["session_id"]))
                if tail:
                    row["transcript_tail"] = tail
                if self.config.summary_lazy_generate:
                    try:
                        enqueue_summary_job(str(row["session_id"]), cwd=self.workspace_root)
                    except Exception:
                        pass
            rows.append(row)
        return rows

    def _load_session_summary(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        try:
            from src.services.session_storage import SESSIONS_DIR

            base = self.sessions_dir or SESSIONS_DIR
            path = Path(base) / session_id / "summary.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and int(data.get("schema_version", 0)) >= 1:
                return {k: data.get(k) for k in ("title", "goals", "open_threads", "next_action_candidates")}
        except Exception:
            return None
        return None

    def _load_transcript_tail(self, session_id: str) -> list[dict[str, str]]:
        if not session_id:
            return []
        try:
            from src.services.session_storage import SESSIONS_DIR

            base = self.sessions_dir or SESSIONS_DIR
            path = Path(base) / session_id / "transcript.jsonl"
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        rows: list[dict[str, str]] = []
        for line in lines[-self.config.max_transcript_tail_messages :]:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            role = str(data.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            text = _flatten_content(data.get("content", "")).strip()
            if text:
                rows.append({"role": role, "content": text[:1000]})
        return rows

    def _memory_files(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for name in MEMORY_FILENAMES:
            path = self.workspace_root / name
            if not path.is_file():
                continue
            try:
                rows.append({"path": name, "content": path.read_text(encoding="utf-8", errors="replace")[:4000]})
            except OSError:
                continue
        dot = self.workspace_root / ".clawcodex"
        if dot.is_dir():
            for path in sorted(dot.glob("*.md"))[:5]:
                try:
                    rows.append(
                        {
                            "path": str(path.relative_to(self.workspace_root)),
                            "content": path.read_text(encoding="utf-8", errors="replace")[:2000],
                        }
                    )
                except OSError:
                    continue
        return rows

    def _workspace_signals(self) -> dict[str, Any]:
        return {
            "git_status": _run_git(self.workspace_root, ["status", "--short"])[:4000],
            "git_diff_stat": _run_git(self.workspace_root, ["diff", "--stat"])[:4000],
            "project_files": _project_files(self.workspace_root),
            "permission_mode": _permission_mode(self.workspace_root),
        }


def _run_git(cwd: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _project_files(cwd: Path) -> list[str]:
    names = ("README.md", "pyproject.toml", "package.json", "CLAUDE.md", "AGENTS.md")
    return [name for name in names if (cwd / name).exists()]


def _permission_mode(cwd: Path) -> str:
    try:
        from src.settings.settings import load_settings

        settings = load_settings(cwd=cwd)
        structured = getattr(getattr(settings, "permissions", None), "default_mode", None)
        legacy = getattr(settings, "permission_mode", "") or ""
        return str(structured or legacy or "default")
    except Exception:
        return "unknown"


def _flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_flatten_content(item) for item in content)
    if isinstance(content, dict):
        if content.get("type") in (None, "text"):
            return str(content.get("text") or content.get("content") or "")
        if content.get("type") == "tool_use":
            return f"[tool:{content.get('name') or ''}]"
        if content.get("type") == "tool_result":
            return str(content.get("content") or "")
    text = getattr(content, "text", None)
    if text is not None:
        return str(text)
    return str(content)


def infer_response_language(
    current_messages: list[dict[str, str]],
    sessions: list[dict[str, Any]] | None = None,
) -> str:
    """Infer whether forecast suggestions should be Chinese or English."""

    samples: list[str] = []
    for msg in reversed(current_messages):
        if msg.get("role") == "user":
            samples.append(str(msg.get("content") or ""))
        if len(samples) >= 6:
            break
    if not samples:
        for session in sessions or []:
            last = str(session.get("last_user_input") or "")
            if last:
                samples.append(last)
            tail = session.get("transcript_tail")
            if isinstance(tail, list):
                for item in reversed(tail):
                    if isinstance(item, dict) and item.get("role") == "user":
                        samples.append(str(item.get("content") or ""))
                        break
            if len(samples) >= 6:
                break

    text = "\n".join(samples)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
    if cjk >= 3 and cjk >= latin * 0.25:
        return "Chinese"
    return "English"
