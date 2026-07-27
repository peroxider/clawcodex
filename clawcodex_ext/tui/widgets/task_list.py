"""Task-list and background-task widgets.

Ports three closely-related TS components:

* ``components/TaskListV2.tsx`` — in-transcript TODO strip that
  renders ``Task`` items from :class:`AppState` with status icons
  (``pending`` / ``in_progress`` / ``completed`` / ``cancelled``).
* ``components/tasks/BackgroundTask.tsx`` — a compact single-line
  summary for a long-running background process (shell, sub-agent,
  remote session).
* ``components/AgentProgressLine.tsx`` — tree-style progress line
  emitted by the ``AgentTool`` UI; used when an agent delegates to a
  sub-agent and wants to show nested tool activity.

All three are plain :class:`textual.widgets.Static` so they slot
directly into the transcript or the status bar without needing a
container wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping, cast

from rich.text import Text
from textual.widgets import Static

TaskStatus = Literal["pending", "in_progress", "completed", "cancelled", "failed"]


@dataclass(frozen=True, slots=True)
class LkbStatus:
    """Minimal Plan Graph projection needed by the shared task widget."""

    derived_status: str = "ready"
    validation_result: str | None = None
    blocked_by: tuple[str, ...] = ()

    @property
    def is_blocked(self) -> bool:
        return self.derived_status == "blocked" or bool(self.blocked_by)


@dataclass
class Task:
    """A single TaskListV2 row."""

    id: str
    title: str
    status: TaskStatus = "pending"
    detail: str = ""
    children: list["Task"] = field(default_factory=list)
    # Optional LKB-derived status badge (when LKB is enabled).
    lkb: LkbStatus | None = None


# Mapping from status → (icon, icon style, title style).  The first four
# entries mirror the current Ink ``TaskListV2`` rendering: completed uses a
# green check, in-progress a warm-orange filled square, and both pending and
# cancelled use an empty square (cancelled is dim/struck).  ``failed`` is a
# downstream state, so retain its explicit red cross instead of collapsing it
# into one of the upstream states.
_STATUS_STYLES: dict[TaskStatus, tuple[str, str, str]] = {
    "pending": ("◻", "", ""),
    "in_progress": ("◼", "bold #D77757", "bold"),
    "completed": ("✔", "#4EBA65", "dim strike"),
    "cancelled": ("◻", "dim", "dim strike"),
    "failed": ("✖", "bold #FF6B80", "bold #FF6B80"),
}

# ── LKB derived-status badge table ──────────────────────────────────────
# Each entry: (emoji, zh_label, en_label, rich_style)
_LKB_BADGE_STYLES: dict[str, tuple[str, str, str, str]] = {
    "fail": ("✗", "验证未通过", "Validation failed", "bold red"),
    "blocked": ("▣", "被阻塞", "Blocked", "bold yellow"),
    "verified": ("✓", "已验证", "Verified", "bold green"),
    "needs_recheck": ("◎", "需复查", "Needs recheck", "dim yellow"),
}


def _lkb_badge(lkb: LkbStatus | None) -> Text | None:
    """Return a Rich Text badge for *lkb*, or ``None`` when no badge is needed."""
    if lkb is None:
        return None

    key: str | None = None
    if lkb.validation_result == "fail":
        key = "fail"
    elif lkb.is_blocked:
        key = "blocked"
    elif lkb.validation_result == "pass":
        key = "verified"
    elif lkb.derived_status == "needs_recheck":
        key = "needs_recheck"

    if key is None:
        return None

    emoji, zh, en, style = _LKB_BADGE_STYLES[key]
    out = Text()
    out.append("  [", style="dim")
    out.append(f"{emoji} {zh} / {en}", style=style)
    out.append("]", style="dim")
    return out


def render_task_tree(tasks: Iterable[Task], *, indent: int = 0) -> Text:
    """Render a task tree as a :class:`rich.text.Text` object."""

    out = Text()
    tasks = list(tasks)
    for idx, task in enumerate(tasks):
        icon, icon_style, title_style = _STATUS_STYLES.get(
            task.status,
            ("◻", "", ""),
        )
        is_last = idx == len(tasks) - 1
        connector = ""
        if indent:
            connector = "    " * (indent - 1) + ("└── " if is_last else "├── ")
        out.append(connector, style="dim")
        out.append(f"{icon} ", style=icon_style)
        out.append(task.title, style=title_style)
        # LKB derived-status badge
        badge = _lkb_badge(task.lkb)
        if badge is not None:
            out.append_text(badge)
        if task.detail:
            out.append(f"  {task.detail}", style="dim")
        out.append("\n")
        if task.children:
            out.append_text(render_task_tree(task.children, indent=indent + 1))
    return out


class TaskListWidget(Static):
    """Renders a :class:`Task` tree in the transcript."""

    DEFAULT_CSS = """
    TaskListWidget {
        padding: 0 1;
        height: auto;
        color: $text;
        background: transparent;
    }
    """

    def __init__(self, tasks: Iterable[Task] | None = None) -> None:
        self._tasks: list[Task] = list(tasks or [])
        super().__init__(render_task_tree(self._tasks), markup=False)

    def set_tasks(self, tasks: Iterable[Task]) -> None:
        self._tasks = list(tasks)
        self.update(render_task_tree(self._tasks))

    @property
    def tasks(self) -> list[Task]:
        return list(self._tasks)

    def progress(self) -> tuple[int, int]:
        """Return ``(done, total)`` counted over leaf tasks only.

        A task is a "leaf" when it has no children; parent tasks act
        purely as grouping rows so they're excluded from the ratio.
        """

        def _count(tasks: Iterable[Task]) -> tuple[int, int]:
            done = total = 0
            for task in tasks:
                if task.children:
                    d, t = _count(task.children)
                    done += d
                    total += t
                    continue
                total += 1
                if task.status == "completed":
                    done += 1
            return done, total

        return _count(self._tasks)


def task_from_mapping(raw: Mapping[str, Any]) -> Task:
    """Convert a Task-v2/LKB projection into the shared TUI row model."""

    task_id = str(raw.get("id") or "")
    status_raw = str(raw.get("status") or "pending")
    if status_raw == "deleted":
        status_raw = "cancelled"
    if status_raw not in _STATUS_STYLES:
        status_raw = "pending"

    lkb_raw = raw.get("lkb")
    lkb_status: LkbStatus | None = None
    detail_parts: list[str] = []
    owner = raw.get("owner")
    if isinstance(owner, str) and owner:
        detail_parts.append(f"owner: {owner}")
    if isinstance(lkb_raw, Mapping):
        derived_raw = str(lkb_raw.get("derivedStatus") or "ready")
        if derived_raw in ("blocked", "needs_recheck", "needs_review"):
            derived = derived_raw
        else:
            derived = "ready"
        validation = lkb_raw.get("validation")
        validation_result = None
        if derived_raw == "verified":
            validation_result = "pass"
        elif isinstance(validation, Mapping):
            raw_result = validation.get("result")
            if raw_result in ("pass", "fail", "unknown"):
                validation_result = raw_result
        active_blockers = lkb_raw.get("activeBlockers")
        blockers = (
            tuple(str(item) for item in active_blockers)
            if isinstance(active_blockers, list)
            else ()
        )
        lkb_status = LkbStatus(
            derived_status=cast(Any, derived),
            validation_result=cast(Any, validation_result),
            blocked_by=blockers,
        )
        if derived_raw not in ("ready", "verified"):
            detail_parts.append(f"LKB: {derived_raw}")

    return Task(
        id=task_id,
        title=f"{task_id}  {str(raw.get('subject') or task_id)}".strip(),
        status=cast(TaskStatus, status_raw),
        detail=" · ".join(detail_parts),
        lkb=lkb_status,
    )


class TaskProgressPanel(TaskListWidget):
    """Persistent Task-v2 progress panel mounted above the TUI status line."""

    can_focus = True

    DEFAULT_CSS = """
    TaskProgressPanel {
        display: none;
        padding: 0 1;
        height: auto;
        max-height: 10;
        overflow-y: auto;
        border-top: solid $panel;
    }
    TaskProgressPanel.-active {
        display: block;
    }
    TaskProgressPanel:focus {
        border-top: solid $accent;
    }
    """

    def __init__(self) -> None:
        super().__init__(tasks=[])

    def set_tasks(self, tasks: Iterable[Task]) -> None:
        super().set_tasks(tasks)
        done, total = self.progress()
        content = Text()
        content.append(f"Tasks  {done}/{total}\n", style="bold")
        content.append_text(render_task_tree(self._tasks))
        self.update(content)
        self.set_class(bool(self._tasks), "-active")


class BackgroundTaskRow(Static):
    """Compact single-line background-task summary."""

    DEFAULT_CSS = """
    BackgroundTaskRow {
        padding: 0 1;
        height: auto;
        color: $text;
        background: transparent;
    }
    """

    def __init__(
        self,
        *,
        task_id: str,
        title: str,
        status: TaskStatus = "in_progress",
        detail: str = "",
    ) -> None:
        self._task_id = task_id
        self._title = title
        self._status: TaskStatus = status
        self._detail = detail
        super().__init__(self._build_text(), markup=False)

    def mark_status(self, status: TaskStatus, *, detail: str | None = None) -> None:
        self._status = status
        if detail is not None:
            self._detail = detail
        self.update(self._build_text())

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def task_id(self) -> str:
        return self._task_id

    def _build_text(self) -> Text:
        icon, icon_style, title_style = _STATUS_STYLES.get(
            self._status,
            ("◻", "", ""),
        )
        out = Text(f"{icon} ", style=icon_style)
        out.append(self._title, style=title_style or "bold")
        if self._detail:
            out.append(f"  {self._detail}", style="dim")
        return out


class AgentProgressLine(Static):
    """Tree-style progress line used by :class:`AgentTool` UI.

    ``steps`` is a list of ``(label, status, detail)`` tuples rendered
    vertically; the widget is effectively a mini-TaskList that the
    agent owns for its lifetime. We expose :meth:`push_step` and
    :meth:`update_step` for the agent to drive without rebuilding
    the whole list.
    """

    DEFAULT_CSS = """
    AgentProgressLine {
        padding: 0 1;
        height: auto;
        color: $text;
        background: transparent;
    }
    """

    def __init__(
        self,
        *,
        header: str = "Delegated agent",
    ) -> None:
        self._header = header
        self._steps: list[tuple[str, TaskStatus, str]] = []
        super().__init__(self._build_text(), markup=False)

    def push_step(
        self,
        label: str,
        *,
        status: TaskStatus = "in_progress",
        detail: str = "",
    ) -> int:
        self._steps.append((label, status, detail))
        self.update(self._build_text())
        return len(self._steps) - 1

    def update_step(
        self,
        index: int,
        *,
        status: TaskStatus | None = None,
        detail: str | None = None,
    ) -> None:
        if not 0 <= index < len(self._steps):
            return
        label, old_status, old_detail = self._steps[index]
        self._steps[index] = (
            label,
            status if status is not None else old_status,
            detail if detail is not None else old_detail,
        )
        self.update(self._build_text())

    def _build_text(self) -> Text:
        out = Text()
        out.append(f"{self._header}\n", style="bold #D77757")
        for idx, (label, status, detail) in enumerate(self._steps):
            icon, icon_style, title_style = _STATUS_STYLES.get(
                status,
                ("◻", "", ""),
            )
            is_last = idx == len(self._steps) - 1
            connector = "└── " if is_last else "├── "
            out.append(connector, style="dim")
            out.append(f"{icon} ", style=icon_style)
            out.append(label, style=title_style)
            if detail:
                out.append(f"  {detail}", style="dim")
            out.append("\n")
        return out


__all__ = [
    "AgentProgressLine",
    "BackgroundTaskRow",
    "Task",
    "TaskListWidget",
    "TaskProgressPanel",
    "TaskStatus",
    "task_from_mapping",
    "render_task_tree",
]
