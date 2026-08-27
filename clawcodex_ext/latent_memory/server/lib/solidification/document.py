"""Deterministic Markdown and optional Git projection for canonical crystals."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.lib.solidification.ledger import CrystalLedger
from clawcodex_ext.latent_memory.server.lib.solidification.maturity import derive_maturity
from clawcodex_ext.latent_memory.server.lib.solidification.models import Revision

logger = logging.getLogger("memory-server.solidification")

_APP_FIELDS = (
    ("applies_when", "适用"),
    ("does_not_apply_when", "不适用"),
    ("known_exceptions", "已知例外"),
)


def _slug(value: str, *, fallback: str) -> str:
    text = str(value or "").strip()
    readable = "-".join(
        part for part in re.split(r"[^\w\-]+", text, flags=re.UNICODE) if part
    ).strip("-_.")
    readable = readable[:64] or fallback
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{readable}-{digest}"


def _yaml(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def render_card(
    head: Revision,
    *,
    chain: list[Revision],
    history: list[Revision],
    supersedes: list[str],
) -> str:
    """Render one canonical head, independent of clock, randomness, or model calls."""
    snapshot = derive_maturity(chain)
    asset = head.asset if isinstance(head.asset, dict) else {}
    applicability = asset.get("applicability")
    applicability = applicability if isinstance(applicability, dict) else {}
    applies_when = _string_list(applicability.get("applies_when") or asset.get("conditions"))
    app_values = {
        "applies_when": applies_when,
        "does_not_apply_when": _string_list(applicability.get("does_not_apply_when")),
        "known_exceptions": _string_list(applicability.get("known_exceptions")),
    }

    lines = [
        "---",
        f"crystal_id: {_yaml(head.crystal_id)}",
        f"rev_id: {head.rev_id}",
        f"version: {head.version}",
        f"status: {_yaml(head.status)}",
        f"asset_type: {_yaml(head.asset_type)}",
        f"knowledge_type: {_yaml(head.knowledge_type)}",
        f"subject: {_yaml(head.subject)}",
        f"confidence: {_yaml(head.confidence)}",
        f"valid_from: {_yaml(head.valid_from)}",
        f"valid_to: {_yaml(head.valid_to)}",
        f"reinforcement_count: {snapshot.reinforcement_count}",
        f"distinct_run_count: {snapshot.distinct_run_count}",
        f"contradiction_count: {snapshot.contradiction_count}",
        f"source_count: {len(head.source_ids)}",
        f"supersedes: {_yaml(','.join(sorted(supersedes)))}",
        "---",
        "",
        "# 结论",
        "",
        str(asset.get("claim") or head.body).strip(),
        "",
        "# 适用 / 不适用",
        "",
    ]
    for key, title in _APP_FIELDS:
        lines.extend([f"## {title}", ""])
        values = app_values[key]
        lines.extend([f"- {value}" for value in values] or ["- 未记录"])
        lines.append("")

    steps = _string_list(asset.get("steps"))
    relations = _string_list(asset.get("relations"))
    lines.extend(["# 步骤 / 关系", ""])
    if steps:
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps, 1))
    if relations:
        lines.extend(f"- 关系：{relation}" for relation in relations)
    if not steps and not relations:
        lines.append("- 未记录")

    lines.extend(
        [
            "",
            "# 证据",
            "",
            f"- 强化事件：{snapshot.reinforcement_count}",
            f"- 不同 run：{snapshot.distinct_run_count}",
            f"- run_ids：{', '.join(snapshot.run_ids) or '未记录'}",
            "- source_ids：",
        ]
    )
    lines.extend([f"  - `{source_id}`" for source_id in head.source_ids] or ["  - 未记录"])

    lines.extend(["", "# 变更", ""])
    for revision in reversed(history):
        confidence = "null" if revision.confidence is None else f"{revision.confidence:.3f}"
        marker = " ← current" if revision.rev_id == head.rev_id else ""
        lines.append(
            f"- v{revision.version} / rev {revision.rev_id} / {revision.recorded_at[:10]}: "
            f"{revision.op} → {revision.status}, confidence={confidence}{marker}"
        )
    return "\n".join(lines).rstrip() + "\n"


class DocumentProjection:
    """Project canonical heads to files and batch the changes into Git commits."""

    def __init__(
        self,
        ledger: CrystalLedger,
        *,
        repo_path: str,
        git_enabled: bool = True,
        mode: str = "async",
        batch_size: int = 100,
    ):
        if mode not in {"async", "sync"}:
            raise ValueError("document projection mode must be async or sync")
        self._ledger = ledger
        self.repo_path = Path(repo_path).resolve()
        self.git_enabled = bool(git_enabled)
        self.mode = mode
        self.batch_size = max(1, int(batch_size))
        self._flush_lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error: str | None = None
        self._commits = 0
        self._writes = 0
        self._deletes = 0
        self.repo_path.mkdir(parents=True, exist_ok=True)
        marker = self.repo_path / ".solidification-doc-repo"
        if not marker.exists():
            marker.write_text("managed by clawcodex_ext.latent_memory.server\n", encoding="utf-8")
        if self.git_enabled:
            if shutil.which("git") is None:
                self.git_enabled = False
                self._last_error = "git executable not found; markdown projection remains enabled"
            else:
                self._ensure_git_repo()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git failed")
        return result

    def _ensure_git_repo(self) -> None:
        if not (self.repo_path / ".git").exists():
            self._git("init", "--quiet")
        self._git("config", "user.name", "memory-solidification")
        self._git("config", "user.email", "solidification@local.invalid")

    def start(self) -> None:
        if self.mode != "async" or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(
            target=self._worker,
            name="solidification-document-projector",
            daemon=True,
        )
        self._thread.start()
        self._wake.set()

    def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def notify(self, _rev_id: int | None = None) -> None:
        if self.mode == "sync":
            self.flush()
        else:
            self._wake.set()

    def _worker(self) -> None:
        try:
            while not self._stopping.is_set():
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                if self._stopping.is_set():
                    break
                try:
                    self.flush()
                except Exception as exc:
                    self._last_error = str(exc)
                    logger.error("document projection failed: %s", exc, exc_info=True)
        finally:
            self._ledger.close()

    def _card_path(self, revision: Revision) -> Path:
        user = revision.scope.get("user_id") or "global"
        directory = self.repo_path / _slug(user, fallback="global")
        filename = _slug(revision.crystal_id, fallback="crystal") + ".md"
        return directory / filename

    def _paths_for_crystal(self, crystal_id: str) -> list[Path]:
        filename = _slug(crystal_id, fallback="crystal") + ".md"
        return list(self.repo_path.glob(f"*/{filename}"))

    def _render(self, head: Revision) -> str:
        chain = self._ledger.revision_chain(head.crystal_id)
        history = self._ledger.history(head.crystal_id)
        supersedes = [
            link.from_crystal_id
            for link in self._ledger.lineage_for_crystal(head.crystal_id)
            if link.to_crystal_id == head.crystal_id
            and link.relation in {"absorbed_into", "superseded_by"}
        ]
        return render_card(
            head,
            chain=chain,
            history=history,
            supersedes=sorted(set(supersedes)),
        )

    def _write_atomic(self, path: Path, content: str) -> bool:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return True

    def _reconcile(self, crystal_ids: list[str]) -> bool:
        changed = False
        for crystal_id in dict.fromkeys(crystal_ids):
            head = self._ledger.head(crystal_id)
            expected = self._card_path(head) if head and head.status == "canonical" else None
            for old_path in self._paths_for_crystal(crystal_id):
                if expected is None or old_path != expected:
                    old_path.unlink(missing_ok=True)
                    self._deletes += 1
                    changed = True
            if expected is not None and self._write_atomic(expected, self._render(head)):
                self._writes += 1
                changed = True
        return changed

    def _commit(self, message: str) -> str | None:
        if not self.git_enabled:
            return None
        self._git("add", "-A", "--", ".")
        if self._git("diff", "--cached", "--quiet", check=False).returncode == 0:
            return self.current_commit()
        self._git("commit", "--quiet", "-m", message)
        self._commits += 1
        return self.current_commit()

    def current_commit(self) -> str | None:
        if not self.git_enabled:
            return None
        result = self._git("rev-parse", "HEAD", check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def flush(self) -> int:
        with self._flush_lock:
            through = int(self._ledger.projection_state().get("document", {}).get("through_rev", 0))
            while True:
                page = self._ledger.revisions_after(through, limit=self.batch_size)
                if not page:
                    break
                changed = self._reconcile([revision.crystal_id for revision in page])
                target = page[-1].rev_id
                if changed:
                    self._commit(f"solidify: project through rev {target}")
                through = target
                self._ledger.set_projection_through("document", through)
            self._last_error = None
            return through

    def reconcile_crystals(self, crystal_ids: list[str]) -> int:
        unique = list(dict.fromkeys(str(value) for value in crystal_ids if value))
        with self._flush_lock:
            if self._reconcile(unique):
                self._commit("solidify: reconcile head rollback")
            self._last_error = None
        return len(unique)

    def card(self, crystal_id: str) -> dict[str, Any] | None:
        head = self._ledger.head(crystal_id)
        if head is None or head.status != "canonical":
            return None
        self.reconcile_crystals([crystal_id])
        path = self._card_path(head)
        return {
            "crystal_id": crystal_id,
            "rev_id": head.rev_id,
            "version": head.version,
            "path": str(path),
            "markdown": path.read_text(encoding="utf-8"),
            "git_commit": self.current_commit(),
        }

    def rebuild(self) -> dict[str, Any]:
        with self._flush_lock:
            removed = False
            for path in self.repo_path.glob("*/*.md"):
                path.unlink(missing_ok=True)
                removed = True
            self._ledger.set_projection_through("document", 0)
        through = self.flush()
        # A ledger without canonical heads produces no writes during flush. Explicitly commit
        # the deletion of expired cards so that Git still mirrors the rebuilt view.
        if removed:
            with self._flush_lock:
                self._commit("solidify: rebuild document projection")
        return {"through_rev": through, "cards": self.card_count()}

    def reset(self) -> None:
        with self._flush_lock:
            self._clear_cards()

    def _clear_cards(self) -> None:
        changed = False
        for path in self.repo_path.glob("*/*.md"):
            path.unlink(missing_ok=True)
            changed = True
        if changed:
            self._commit("solidify: reset document projection")

    def reset_with_ledger(self, reset_ledger: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Exclude the document worker thread while all derived state and source state are reset."""
        with self._flush_lock:
            self._clear_cards()
            return reset_ledger()

    def card_count(self) -> int:
        return sum(1 for _ in self.repo_path.glob("*/*.md"))

    def state(self) -> dict[str, Any]:
        through = int(self._ledger.projection_state().get("document", {}).get("through_rev", 0))
        return {
            "enabled": True,
            "mode": self.mode,
            "repo_path": str(self.repo_path),
            "git_enabled": self.git_enabled,
            "git_commit": self.current_commit(),
            "through_rev": through,
            "lag": max(0, self._ledger.max_rev_id() - through),
            "cards": self.card_count(),
            "writes": self._writes,
            "deletes": self._deletes,
            "commits": self._commits,
            "last_error": self._last_error,
        }
