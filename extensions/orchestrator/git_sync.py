"""Post-run git sync for repository-backed workspaces."""

from __future__ import annotations

import asyncio
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clawcodex_ext.utils.git import (
    get_current_branch,
    get_default_branch,
    get_file_status,
    get_repo_root,
    _run_git,
)
from .config.schema import AgentConfig, HooksConfig
from . import report_writer
from .issue import Issue
from .tracker import PullRequestRef, TrackerAdapter
from .workspace import Workspace


@dataclass(frozen=True)
class GitSyncResult:
    """Result of post-run git synchronization."""

    branch_name: str
    base_branch: str
    commit_sha: str | None = None
    pull_request: PullRequestRef | None = None
    committed: bool = False
    pushed: bool = False
    has_conflict: bool = False
    conflict_files: tuple[str, ...] = field(default_factory=tuple)
    pending_review: bool = False  # True for LocalTracker after successful commit
    # F-40 / F-38 补遗: 当分支没有可评审 commit 时（如 daemon 触发了 read-only
    # loop 终止），标记终结原因。orchestrator 据此走 mark_failed_with_reason
    # 而非 mark_synced，避免给空 PR 标 SYNCED。
    session_end_reason: str | None = None


class GitSyncError(RuntimeError):
    """Raised when post-run git sync fails."""


class VerificationFailed(GitSyncError):
    """Raised when configured verification commands fail."""

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        self.output = output


class HookFailedError(GitSyncError):
    """Raised when a configured sync hook fails."""

    def __init__(self, hook_name: str, message: str, output: str = "") -> None:
        super().__init__(message)
        self.hook_name = hook_name
        self.output = output


class GitSyncPostCommitError(GitSyncError):
    """Raised when post-commit sync steps fail after a commit exists."""

    def __init__(self, cause: VerificationFailed | HookFailedError, result: GitSyncResult) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.result = result
        self.output = getattr(cause, "output", "")
        self.hook_name = getattr(cause, "hook_name", None)


class GitSyncService:
    """Perform commit, push, and PR creation after a run."""

    def __init__(
        self,
        tracker: TrackerAdapter,
        branch_prefix: str | None = None,
        gitignore_patterns: list[str] | None = None,
        agent_config: AgentConfig | None = None,
        hooks_config: HooksConfig | None = None,
    ) -> None:
        self.tracker = tracker
        self._branch_prefix = branch_prefix
        self._agent_config = agent_config or AgentConfig()
        self._hooks_config = hooks_config or HooksConfig()
        self._gitignore_patterns = gitignore_patterns or [
            ".event_streams",
            ".orchestrator_control",
            ".orchestrator_workspace",
            ".operator_hints.md",
            ".reports",
            ".clawcodex_clarification_queue.json",
            ".clawcodex_issue_registry.json",
            ".clawcodex_workspace.lock",
            "*.pyc",
            "__pycache__",
            "*.egg-info",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "*.log",
        ]

    async def sync(
        self,
        session: Any,
        *,
        mode: str = "default",
    ) -> GitSyncResult | None:
        """Commit/push/PR sync.

        F-39 Sub-C: when `mode == "followup"`, the session is expected
        to already carry a `pull_request` attribute (set by the
        orchestrator from the registry record) and the run is treated
        as a same-branch follow-up commit. The commit message uses
        the "fix:" prefix (vs. "feat:" for new runs) and the existing
        `update_pull_request` path appends a `## ClawCodex Follow-up
        #N` section to the PR body (F-38 Sub-C, already in place).

        Other modes (default / future) are unchanged.
        """
        # F-39 Sub-C: validate followup-mode prerequisites BEFORE any
        # workspace / repo_root I/O. A follow-up that forgot to wire
        # the existing PR would otherwise silently open a brand-new
        # PR, which is exactly what follow-up is trying to avoid.
        if mode == "followup":
            existing_pr = getattr(session, "pull_request", None)
            if existing_pr is None:
                raise GitSyncError(
                    "GitSyncService.sync(mode='followup') requires "
                    "session.pull_request to be set; orchestrator "
                    "should populate it from the IssueRegistry record"
                )

        workspace: Workspace = session.workspace
        issue: Issue = session.issue

        repo_root = await asyncio.to_thread(get_repo_root, str(workspace.path))
        if not repo_root:
            return None

        # Check if tracker is LocalTrackerAdapter — skip push/PR for local-only repos
        from .local_tracker.adapter import LocalTrackerAdapter

        is_local_tracker = isinstance(self.tracker, LocalTrackerAdapter)
        workspace_strategy = getattr(session, "workspace_strategy", "isolated")
        is_sequential = workspace_strategy == "sequential"
        self._sync_git_exclude(repo_root)
        no_push = is_local_tracker or is_sequential

        followup_pr = getattr(session, "pull_request", None)
        base_branch = getattr(session, "base_branch", None)
        if not base_branch:
            base_branch = await asyncio.to_thread(get_default_branch, repo_root)
        if is_sequential:
            branch_name = getattr(session, "integration_branch", None)
            if not branch_name:
                branch_name = (
                    await asyncio.to_thread(get_current_branch, repo_root) or base_branch
                )
        else:
            branch_name = await asyncio.to_thread(
                self._ensure_work_branch, repo_root, issue, base_branch
            )
        changed = bool(await asyncio.to_thread(get_file_status, repo_root))

        commit_sha: str | None = None
        committed = False
        has_run_commit = False
        pushed = False
        has_conflict = False
        conflict_files: tuple[str, ...] = ()
        if changed:
            await asyncio.to_thread(self._ensure_commit_identity, repo_root)
            if is_sequential:
                await self._run_pre_commit_hook(repo_root, session)
            await asyncio.to_thread(self._run_git_checked, ["add", "-A"], repo_root)
            await asyncio.to_thread(self._unstage_orchestrator_artifacts, repo_root)
            await asyncio.to_thread(self._apply_file_whitelist, repo_root)

            # Check if there are staged changes after add/unstage/whitelist
            # If not, agent may have already committed (e2e workflow)
            has_staged = await asyncio.to_thread(self._has_staged_changes, repo_root)
            agent_committed = False
            if not has_staged:
                # No staged changes - check if agent already committed by comparing HEAD
                current_sha = await asyncio.to_thread(
                    self._run_git_output, ["rev-parse", "HEAD"], repo_root
                )
                start_commit_sha = getattr(session, "start_commit_sha", None)
                has_run_commit = bool(start_commit_sha and current_sha != start_commit_sha)

                if has_run_commit:
                    # Agent already committed, skip auto-commit
                    agent_committed = True
                    commit_sha = current_sha
                else:
                    # No staged changes and HEAD unchanged - likely whitelist filtered everything
                    # Fall through to normal commit flow (which will create empty commit or skip)
                    commit_sha = None
            else:
                commit_message = self._build_commit_message(
                    issue,
                    followup=followup_pr is not None,
                    feedback_body=getattr(session, "feedback_commit_body", None),
                )
                await asyncio.to_thread(
                    self._run_git_checked, ["commit", "-m", commit_message], repo_root
                )
                commit_sha = await asyncio.to_thread(
                    self._run_git_output, ["rev-parse", "HEAD"], repo_root
                )
                committed = True
            try:
                if not is_sequential and not agent_committed:
                    await self._run_pre_commit_hook(repo_root, session)
                    commit_sha = await asyncio.to_thread(
                        self._run_git_output, ["rev-parse", "HEAD"], repo_root
                    )
                await self._run_pre_push_verification(repo_root, session)
            except (VerificationFailed, HookFailedError) as exc:
                # Roll back the just-created commit since verification failed
                # But only if we created the commit (not agent)
                if not agent_committed:
                    try:
                        await asyncio.to_thread(
                            self._run_git_checked, ["reset", "--mixed", "HEAD~1"], repo_root
                        )
                    except GitSyncError:
                        pass  # No commit to rollback or reset failed — proceed anyway
                    committed = False
                raise self._post_commit_error(
                    exc,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    commit_sha=commit_sha,
                    committed=committed,
                    pushed=pushed,
                    has_conflict=has_conflict,
                    conflict_files=conflict_files,
                    pull_request=followup_pr,
                    is_local_tracker=is_local_tracker,
                ) from exc
            if no_push:
                # LocalTracker: no remote, skip push but record branch info
                pass
            else:
                pushed, has_conflict, conflict_files = await asyncio.to_thread(
                    self._push_with_recovery,
                    repo_root,
                    branch_name,
                )
        else:
            commit_sha = await asyncio.to_thread(
                self._run_git_output, ["rev-parse", "HEAD"], repo_root
            )
            start_commit_sha = getattr(session, "start_commit_sha", None)
            has_run_commit = bool(start_commit_sha and commit_sha != start_commit_sha)
            try:
                await self._run_pre_push_verification(repo_root, session)
            except (VerificationFailed, HookFailedError) as exc:
                raise self._post_commit_error(
                    exc,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    commit_sha=commit_sha,
                    committed=has_run_commit,
                    pushed=False,
                    has_conflict=False,
                    conflict_files=(),
                    pull_request=followup_pr,
                    is_local_tracker=is_local_tracker,
                ) from exc
            if not has_run_commit:
                commit_sha = None
            # No staged changes but branch may have diverged from origin — still push
            if branch_name and not no_push:
                pushed, has_conflict, conflict_files = await asyncio.to_thread(
                    self._push_with_recovery,
                    repo_root,
                    branch_name,
                )

        pr_ref: PullRequestRef | None = followup_pr
        pr_title = self._build_pr_title(issue)
        # F-40 / F-38 补遗：阻止空 PR 创建。当分支无 reviewable commit（daemon
        # 触发 read_only_loop / loop_detected / stagnation 终止场景），
        # 即便分支被 push 也不能创建 PR — 否则会留下 0 commit 的空 PR。
        has_reviewable_commit = committed or has_run_commit
        if (
            pr_ref is None
            and branch_name != base_branch
            and not no_push
            and has_reviewable_commit
        ):
            pr_ref = await self.tracker.ensure_pull_request(
                issue=issue,
                head_branch=branch_name,
                base_branch=base_branch,
                title=pr_title,
                body=self._build_pr_body(
                    issue,
                    commit_sha,
                    branch_name,
                    base_branch,
                    session=session,
                    pull_request=None,
                ),
            )
            # GitCode PR creation may not return number/url immediately;
            # fall back to listing open PRs and matching by head branch.
            if pr_ref is not None and (not pr_ref.number or not pr_ref.url):
                pr_ref = await self._find_pr_fallback(
                    pr_ref,
                    head_branch=branch_name,
                    base_branch=base_branch,
                )

        report_result = self._write_report(
            session=session,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pull_request=pr_ref,
        )

        if pr_ref is not None and not no_push:
            updated_pr = await self.tracker.update_pull_request(
                pull_request=pr_ref,
                title=pr_title,
                body=self._build_pr_body(
                    issue,
                    commit_sha,
                    branch_name,
                    base_branch,
                    session=session,
                    pull_request=pr_ref,
                ),
            )
            if updated_pr is not None:
                pr_ref = self._merge_pr_ref(updated_pr, pr_ref)
                if not pr_ref.number or not pr_ref.url:
                    pr_ref = await self._find_pr_fallback(
                        pr_ref,
                        head_branch=branch_name,
                        base_branch=base_branch,
                    )
                self._write_report(
                    session=session,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    commit_sha=commit_sha,
                    pull_request=pr_ref,
                )

        has_reviewable_commit = committed or has_run_commit
        try:
            await self._run_post_sync_hook(repo_root, session)
        except (VerificationFailed, HookFailedError) as exc:
            if has_reviewable_commit:
                raise self._post_commit_error(
                    exc,
                    branch_name=branch_name,
                    base_branch=base_branch,
                    commit_sha=commit_sha,
                    committed=has_reviewable_commit,
                    pushed=pushed,
                    has_conflict=has_conflict,
                    conflict_files=conflict_files,
                    pull_request=pr_ref,
                    is_local_tracker=is_local_tracker,
                ) from exc
            raise

        # F-40 补遗：仅当有 reviewable commit **或**已存在 PR（follow-up 场景）
        # 时才发 summary comment。空分支 + 推送到远端但无 commit 的场景不再发
        # 总结评论（避免给一个"什么也没改"的 PR 写总结）。
        if has_reviewable_commit or pr_ref is not None:
            await self._update_summary_comment(
                session=session,
                branch_name=branch_name,
                base_branch=base_branch,
                commit_sha=commit_sha,
                pull_request=pr_ref,
                committed=has_reviewable_commit,
                pushed=pushed if not no_push else False,
                report_path=(
                    report_result.persistent_markdown_path if report_result is not None else None
                ),
            )

        # F-40 / F-38 补遗：标记 session_end_reason，便于 orchestrator
        # 决定走 mark_synced 还是 mark_failed_with_reason。
        session_end_reason: str | None = None
        if not has_reviewable_commit and pr_ref is None:
            session_end_reason = "empty_branch_no_commits"

        return GitSyncResult(
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pull_request=pr_ref,
            committed=has_reviewable_commit,
            pushed=pushed,
            has_conflict=has_conflict,
            conflict_files=conflict_files,
            pending_review=bool(
                (is_local_tracker or self._agent_config.review_required) and has_reviewable_commit
            ),
            session_end_reason=session_end_reason,
        )

    def _post_commit_error(
        self,
        cause: VerificationFailed | HookFailedError,
        *,
        branch_name: str,
        base_branch: str,
        commit_sha: str | None,
        committed: bool,
        pushed: bool,
        has_conflict: bool,
        conflict_files: tuple[str, ...],
        pull_request: PullRequestRef | None,
        is_local_tracker: bool,
    ) -> GitSyncPostCommitError:
        result = GitSyncResult(
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pull_request=pull_request,
            committed=committed,
            pushed=pushed,
            has_conflict=has_conflict,
            conflict_files=conflict_files,
            pending_review=bool(
                (is_local_tracker or self._agent_config.review_required) and committed
            ),
        )
        return GitSyncPostCommitError(cause, result)

    async def _run_pre_commit_hook(self, repo_root: str, session: Any) -> None:
        command = self._hooks_config.pre_commit
        if not command:
            return
        output = await self._run_shell(command, repo_root, self._hooks_config.timeout_ms)
        if (
            await asyncio.to_thread(get_file_status, repo_root)
            and getattr(session, "workspace_strategy", "isolated") != "sequential"
        ):
            await asyncio.to_thread(self._run_git_checked, ["add", "-A"], repo_root)
            await asyncio.to_thread(
                self._run_git_checked, ["commit", "--amend", "--no-edit"], repo_root
            )
        setattr(session, "pre_commit_output", output)

    async def _run_pre_push_verification(self, repo_root: str, session: Any) -> None:
        outputs: list[str] = []
        for label, command in (
            ("test", self._agent_config.test_command),
            ("build", self._agent_config.build_command),
            ("lint", self._agent_config.lint_command),
        ):
            if not command:
                continue
            try:
                output = await self._run_shell(
                    command,
                    repo_root,
                    self._agent_config.verification.timeout_ms,
                )
            except VerificationFailed as exc:
                raise VerificationFailed(f"{label} verification failed", exc.output) from exc
            outputs.append(f"## {label}\n{output}".strip())
        hook_command = self._hooks_config.pre_push
        if hook_command:
            before = await asyncio.to_thread(self._status_snapshot, repo_root)
            try:
                output = await self._run_shell(
                    hook_command,
                    repo_root,
                    self._hooks_config.timeout_ms,
                )
            except VerificationFailed as exc:
                raise HookFailedError("pre_push", "pre_push hook failed", exc.output) from exc
            if await asyncio.to_thread(self._status_snapshot, repo_root) != before:
                raise HookFailedError(
                    "pre_push",
                    "pre_push hook modified the workspace",
                    output,
                )
            outputs.append(f"## pre_push\n{output}".strip())
        setattr(session, "verification_status", "passed")
        setattr(session, "verification_output", "\n\n".join(outputs))

    async def _run_post_sync_hook(self, repo_root: str, session: Any) -> None:
        command = self._hooks_config.post_sync
        if not command:
            return
        before = await asyncio.to_thread(self._status_snapshot, repo_root)
        try:
            output = await self._run_shell(command, repo_root, self._hooks_config.timeout_ms)
        except VerificationFailed as exc:
            raise HookFailedError("post_sync", "post_sync hook failed", exc.output) from exc
        if await asyncio.to_thread(self._status_snapshot, repo_root) != before:
            raise HookFailedError(
                "post_sync",
                "post_sync hook modified the workspace",
                output,
            )
        setattr(session, "post_sync_output", output)

    async def _run_shell(self, command: str, repo_root: str, timeout_ms: int) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=repo_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError as exc:
            raise VerificationFailed(
                f"command timed out after {timeout_ms}ms: {command}",
                "",
            ) from exc
        output = "\n".join(
            part.decode("utf-8", errors="replace").strip() for part in (stdout, stderr) if part
        ).strip()
        if proc.returncode != 0:
            raise VerificationFailed(
                f"command failed with exit code {proc.returncode}: {command}",
                output,
            )
        return output

    def _status_snapshot(self, repo_root: str) -> str:
        return "\n".join(sorted(s.path for s in get_file_status(repo_root)))

    def _sync_gitignore(self, repo_root: str) -> None:
        self._sync_git_exclude(repo_root)

    def _sync_git_exclude(self, repo_root: str) -> None:
        exclude_path = Path(repo_root) / ".git" / "info" / "exclude"
        self._append_ignore_patterns(exclude_path)

    def _append_ignore_patterns(self, path: Path) -> None:
        existing: set[str] = set()
        if path.exists():
            existing = {
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            }
        new_patterns = [pattern for pattern in self._gitignore_patterns if pattern not in existing]
        if not new_patterns:
            return
        with path.open("a", encoding="utf-8") as handle:
            if path.exists() and path.stat().st_size > 0:
                handle.write("\n")
            handle.write("# ClawCodeX managed — do not edit manually\n")
            for pattern in new_patterns:
                handle.write(f"{pattern}\n")

    def _push_with_recovery(
        self,
        repo_root: str,
        branch_name: str,
    ) -> tuple[bool, bool, tuple[str, ...]]:
        """Push branch, recovering from non-fast-forward with rebase."""
        stdout, stderr, rc = _run_git(
            ["push", "-u", "origin", branch_name],
            repo_root,
        )
        if rc == 0:
            return True, False, ()

        if not self._is_non_fast_forward(stderr):
            raise GitSyncError(f"git push failed: {stderr or stdout}")

        # Attempt fetch + rebase
        self._run_git_checked(["fetch", "origin"], repo_root)
        # F-120: defensively clear any leftover REBASE_HEAD before
        # starting a fresh rebase — if a previous run aborted mid-
        # rebase, this prevents compounding conflict markers.
        _git_rebase_abort(repo_root)
        stdout, stderr, rc = _run_git(
            ["rebase", f"origin/{branch_name}"],
            repo_root,
        )
        if rc != 0:
            # Check if remote branch doesn't exist (shallow clone scenario)
            if "fatal: invalid upstream" in stderr or "couldn't find remote ref" in stderr:
                # Remote branch doesn't exist - force push to create it
                self._run_git_checked(["push", "-u", "origin", branch_name, "--force"], repo_root)
                return True, False, ()
            conflict_files = self._detect_conflicts(repo_root)
            if conflict_files:
                # F-120: leave the half-finished rebase in place so
                # the follow-up agent run can resume with
                # ``git rebase --continue`` after resolving the
                # conflict markers.
                return False, True, conflict_files
            # F-120: non-conflict rebase failure (auth / network) —
            # abort the half-finished rebase so the workspace
            # doesn't stay stuck in REBASE_HEAD.
            _git_rebase_abort(repo_root)
            raise GitSyncError(f"git rebase failed: {stderr or stdout}")

        # Retry push after successful rebase
        self._run_git_checked(["push", "-u", "origin", branch_name], repo_root)
        return True, False, ()

    def _is_non_fast_forward(self, stderr: str) -> bool:
        if not stderr:
            return False
        return (
            "non-fast-forward" in stderr.lower()
            or "fetch first" in stderr.lower()
            or "Updates were rejected" in stderr
            or "shallow update" in stderr.lower()
            or "deny updating a hidden branch" in stderr.lower()
        )

    def _detect_conflicts(self, repo_root: str) -> tuple[str, ...]:
        """Return list of files with conflict markers."""
        stdout, _, _ = _run_git(
            ["diff", "--name-only", "--diff-filter=U"],
            repo_root,
        )
        if not stdout.strip():
            return ()
        return tuple(f.strip() for f in stdout.strip().splitlines() if f.strip())

    def _ensure_work_branch(
        self,
        repo_root: str,
        issue: Issue,
        base_branch: str,
    ) -> str:
        current_branch = get_current_branch(repo_root)
        branch_name = issue.branch_name or self._default_branch_name(issue)

        if current_branch == branch_name:
            return branch_name
        if current_branch and current_branch != "HEAD" and current_branch != base_branch:
            return current_branch

        stdout, stderr, rc = _run_git(["checkout", branch_name], repo_root)
        if rc == 0:
            return branch_name

        # Branch doesn't exist locally — determine best creation strategy
        # Case 1: remote branch exists → checkout with --track to wire it to origin
        # Case 2: completely new branch → create with -b
        remote_ref = f"origin/{branch_name}"
        check_remote = self._run_git_output(
            ["rev-parse", "--verify", f"refs/remotes/{remote_ref}"], repo_root
        )
        if check_remote:
            # Remote branch exists — wire it up with --track
            stdout, stderr, rc = _run_git(
                ["checkout", "--track", remote_ref],
                repo_root,
            )
        else:
            # No remote branch → create new local branch
            stdout, stderr, rc = _run_git(
                ["checkout", "-b", branch_name],
                repo_root,
            )
        if rc != 0:
            raise GitSyncError(f"Failed to checkout work branch {branch_name}: {stderr or stdout}")
        return branch_name

    def _ensure_commit_identity(self, repo_root: str) -> None:
        email = self._run_git_output(["config", "user.email"], repo_root)
        name = self._run_git_output(["config", "user.name"], repo_root)
        if not email:
            self._run_git_checked(
                ["config", "user.email", "clawcodex-bot@local.invalid"],
                repo_root,
            )
        if not name:
            self._run_git_checked(
                ["config", "user.name", "ClawCodex Bot"],
                repo_root,
            )

    _ORCHESTRATOR_ARTIFACTS: tuple[str, ...] = (
        ".orchestrator_control",
        ".orchestrator_workspace",
        ".reports",
        ".operator_hints.md",
        ".clawcodex_issue_registry.json",
        ".clawcodex_clarification_queue.json",
        ".clawcodex_workspace.lock",
        ".event_streams",
        "daemon.pid",
    )

    def _unstage_orchestrator_artifacts(self, repo_root: str) -> None:
        """Remove orchestrator-internal files from the staging area.

        Safety net: even if ``.git/info/exclude`` patterns are bypassed
        (e.g. the agent overwrites the exclude file), these files will
        never enter a commit.
        """
        stdout, _, rc = _run_git(["diff", "--cached", "--name-only"], repo_root)
        if rc != 0 or not stdout.strip():
            return
        staged = {f.strip() for f in stdout.strip().splitlines() if f.strip()}
        to_unstage: list[str] = []
        for path in staged:
            for artifact in self._ORCHESTRATOR_ARTIFACTS:
                if path == artifact or path.startswith(f"{artifact}/"):
                    to_unstage.append(path)
                    break
        if to_unstage:
            self._run_git_checked(["reset", "--", *to_unstage], repo_root)

    def _apply_file_whitelist(self, repo_root: str) -> None:
        """Unstage files outside the allowed whitelist before commit.

        When ``agent.allowed_changed_files`` is configured, only the
        specified glob patterns may enter the commit.  Any other staged
        file is reset to unstaged (``git reset -- <path>``).  If all
        files are filtered out the commit is still attempted — it will
        simply produce no commit (no staged changes), which the caller
        already handles gracefully.
        """
        whitelist = self._agent_config.allowed_changed_files
        if not whitelist:
            return
        import fnmatch

        stdout, _, rc = _run_git(["diff", "--cached", "--name-only"], repo_root)
        if rc != 0 or not stdout.strip():
            return
        staged = [f.strip() for f in stdout.strip().splitlines() if f.strip()]
        to_unstage = [f for f in staged if not any(fnmatch.fnmatch(f, pat) for pat in whitelist)]
        if to_unstage:
            self._run_git_checked(["reset", "--", *to_unstage], repo_root)

    def _build_commit_message(
        self, issue: Issue, *, followup: bool = False, feedback_body: str | None = None
    ) -> str:
        identifier = (issue.identifier or "issue").strip().lstrip("#")
        prefix = "fix" if followup else "feat"
        if followup and feedback_body:
            # Use the review comment as the commit title
            title = feedback_body.strip()[:72]
        else:
            title = (issue.title or "automated update").strip()
        message = f"{prefix}: {identifier} {title}"
        return message[:72]

    def _build_pr_title(self, issue: Issue) -> str:
        identifier = (issue.identifier or "issue").strip()
        title = (issue.title or "Automated update").strip()
        return f"{identifier}: {title}"

    def _build_pr_body(
        self,
        issue: Issue,
        commit_sha: str | None,
        branch_name: str,
        base_branch: str,
        *,
        session: Any,
        pull_request: PullRequestRef | None,
    ) -> str:
        report_path = getattr(session, "report_path", None)
        verification_status = getattr(session, "verification_status", None) or "skipped"
        workspace_path = (
            getattr(session.workspace, "path", None) if hasattr(session, "workspace") else None
        )
        lines = [
            "## ClawCodex Automated Change",
            "",
            f"- Issue: {issue.identifier or issue.id or 'unknown'}",
            f"- Branch: `{branch_name}`",
            f"- Base: `{base_branch}`",
            f"- Commit: `{commit_sha or 'n/a'}`",
            f"- Verification: `{verification_status}`",
            f"- Report: `{report_path or 'n/a'}`",
        ]
        # Add workspace path if available (useful for manual verification)
        if workspace_path:
            lines.append(f"- Workspace: `{workspace_path}`")
        if issue.url:
            lines.append(f"- Source issue: {issue.url}")
        if pull_request and pull_request.url:
            lines.append(f"- Pull request: {pull_request.url}")

        # Read agent's commit message for e2e verification results
        if commit_sha:
            try:
                workspace_path = getattr(session.workspace, "path", None)
                if workspace_path:
                    commit_msg = self._run_git_output(
                        ["log", "-1", "--format=%B", commit_sha],
                        str(workspace_path),
                    )
                    if commit_msg and commit_msg.strip():
                        lines.extend(["", "---", ""])
                        e2e_section = self._extract_section(commit_msg, "E2E Verification")
                        changes_section = self._extract_section(commit_msg, "Changes")

                        if changes_section:
                            lines.extend(["## Changes", "", changes_section])
                        if e2e_section:
                            lines.extend(["", "## E2E Verification", "", e2e_section])

                        if not e2e_section and not changes_section:
                            lines.extend(["## Agent Notes", "", commit_msg.strip()])
            except Exception:
                pass

        # Include regression test output summary
        verification_output = getattr(session, "verification_output", None)
        if verification_output:
            summary_lines = [
                l
                for l in verification_output.strip().splitlines()
                if "passed" in l or "failed" in l
            ]
            if summary_lines:
                lines.extend(["", "## Regression Tests", "", "```", summary_lines[-1], "```"])

        if report_path:
            lines.extend(["", f"<!-- metadata: report_path={report_path} -->"])
        return "\n".join(lines)

    @staticmethod
    def _extract_section(text: str, section_name: str) -> str | None:
        """Extract a named section from a structured commit message.

        Looks for `## Section Name` followed by content until the next `##` or EOF.
        """
        import re

        pattern = rf"## {re.escape(section_name)}\s*\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    def _write_report(
        self,
        *,
        session: Any,
        branch_name: str,
        base_branch: str,
        commit_sha: str | None,
        pull_request: PullRequestRef | None,
    ) -> report_writer.ReportResult | None:
        run_id = getattr(session, "run_id", None)
        workspace = getattr(session, "workspace", None)
        issue = getattr(session, "issue", None)
        if not run_id or workspace is None or issue is None:
            return None
        result = report_writer.write(
            run_id=run_id,
            workspace_path=Path(workspace.path),
            tracker=getattr(self.tracker, "platform", self.tracker.__class__.__name__),
            owner=getattr(self.tracker, "owner", None),
            repo=getattr(self.tracker, "repo", None),
            issue=issue,
            status=getattr(session, "status", "unknown"),
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pr_number=str(pull_request.number)
            if pull_request and pull_request.number is not None
            else None,
            pr_url=pull_request.url if pull_request else None,
            turn_count=getattr(session, "turn_count", 0),
            tool_count=getattr(session, "tool_count", 0),
            verification_status=getattr(session, "verification_status", None),
            verification_output=getattr(session, "verification_output", None),
            output_text=getattr(session, "output_text", ""),
            # F-45: forward the per-tool audit log path so report_writer
            # can dual-write the NDJSON into the persistent layer.
            tool_events_path=getattr(session, "tool_events_path", None),
        )
        setattr(session, "report_path", result.persistent_markdown_path)
        return result

    async def _update_summary_comment(
        self,
        *,
        session: Any,
        branch_name: str,
        base_branch: str,
        commit_sha: str | None,
        pull_request: PullRequestRef | None,
        committed: bool,
        pushed: bool,
        report_path: str | None,
    ) -> None:
        issue = session.issue
        if not issue.id:
            return

        body = self._build_summary_comment_body(
            session=session,
            branch_name=branch_name,
            base_branch=base_branch,
            commit_sha=commit_sha,
            pull_request=pull_request,
            committed=committed,
            pushed=pushed,
            report_path=report_path,
        )
        comment_id = getattr(session, "summary_comment_id", None)
        if comment_id:
            updated = await self.tracker.update_comment(issue.id, comment_id, body)
            if updated is not None:
                return
        created = await self.tracker.create_comment(issue.id, body)
        if created is not None and getattr(created, "id", None):
            setattr(session, "summary_comment_id", created.id)

    def _build_summary_comment_body(
        self,
        *,
        session: Any,
        branch_name: str,
        base_branch: str,
        commit_sha: str | None,
        pull_request: PullRequestRef | None,
        committed: bool,
        pushed: bool,
        report_path: str | None,
    ) -> str:
        verification_status = getattr(session, "verification_status", None) or "skipped"
        body_lines = [
            "## ClawCodex Run Summary",
            "",
            f"- Run: `{getattr(session, 'run_id', 'unknown')}`",
            f"- Status: `{getattr(session, 'status', 'unknown')}`",
            f"- Branch: `{branch_name}`",
            f"- Base: `{base_branch}`",
            f"- Committed: {'yes' if committed else 'no'}",
            f"- Pushed: {'yes' if pushed else 'no'}",
            f"- Verification: `{verification_status}`",
            f"- Report: `{report_path or 'n/a'}`",
        ]
        if commit_sha:
            body_lines.append(f"- Commit: `{commit_sha}`")
        if pull_request and pull_request.url:
            body_lines.append(f"- Pull request: {pull_request.url}")
        if report_path:
            body_lines.extend(["", f"<!-- metadata: report_path={report_path} -->"])
        return "\n".join(body_lines)

    def _default_branch_name(self, issue: Issue) -> str:
        identifier = issue.identifier or issue.id or "issue"
        title = issue.title or "update"
        slug = _slugify(f"{identifier}-{title}")[:48]
        prefix = self._branch_prefix or "clawcodex"
        return f"{prefix}/{slug}"

    def _merge_pr_ref(
        self,
        updated: PullRequestRef,
        existing: PullRequestRef,
    ) -> PullRequestRef:
        return PullRequestRef(
            number=updated.number or existing.number,
            url=updated.url or existing.url,
            title=updated.title or existing.title,
        )

    def _run_git_output(self, args: list[str], repo_root: str) -> str:
        stdout, stderr, rc = _run_git(args, repo_root)
        if rc != 0:
            return ""
        return stdout.strip()

    def _run_git_checked(self, args: list[str], repo_root: str) -> str:
        stdout, stderr, rc = _run_git(args, repo_root)
        if rc != 0:
            raise GitSyncError(f"git {' '.join(args)} failed: {stderr or stdout}")
        return stdout.strip()

    def _has_staged_changes(self, repo_root: str) -> bool:
        """Check if there are staged changes ready to commit.

        Returns True if `git diff --cached --quiet` exits with non-zero
        (meaning there are staged changes), False otherwise.
        """
        _, _, rc = _run_git(["diff", "--cached", "--quiet"], repo_root)
        # rc=0 means no staged changes, rc=1 means there are staged changes
        return rc != 0

    async def _find_pr_fallback(
        self,
        pr_ref: PullRequestRef,
        *,
        head_branch: str,
        base_branch: str,
    ) -> PullRequestRef:
        """Find a just-created PR when the initial response lacks number/url.

        Some trackers (notably GitCode) return a pull-request object where
        ``number`` and ``url`` are empty right after creation.  This method
        polls the tracker's open-PR list and matches by ``head_branch``.
        """
        import asyncio

        for _ in range(15):
            try:
                found = await self.tracker.find_pull_request(
                    head_branch=head_branch,
                    base_branch=base_branch,
                )
            except Exception:
                found = None
            if found is not None and (found.number or found.url):
                return self._merge_pr_ref(found, pr_ref)

            try:
                open_prs = await self.tracker.list_pull_requests(
                    state="open",
                    head=head_branch,
                )
            except (TypeError, AttributeError):
                # Tracker doesn't support head filtering — try unfiltered.
                try:
                    open_prs = await self.tracker.list_pull_requests(state="open")
                except Exception:
                    return pr_ref
            except Exception:
                return pr_ref
            if open_prs:
                for candidate in open_prs:
                    candidate_head = (
                        getattr(candidate, "head_ref", None)
                        or getattr(candidate, "head_branch", None)
                        or getattr(candidate, "source_branch", None)
                        or ""
                    )
                    if candidate_head == head_branch:
                        return candidate
            await asyncio.sleep(2)
        return pr_ref


def _slugify(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "issue-update"


# ---------------------------------------------------------------------------
# F-120: PR conflict auto-resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PRRebaseResult:
    """Result of `rebase_for_pr`.

    Attributes:
      * ``rebased`` — ``True`` if the local branch is now based on
        the latest base. ``False`` if the rebase did not happen (no
        work to do, push failed, or pre-flight check rejected).
      * ``has_conflict`` — ``True`` if the rebase left content
        conflicts in the workspace. The orchestrator's daemon
        scan path uses this to schedule a follow-up agent run
        (``run_kind="agent_rebase"``).
      * ``conflict_files`` — list of files containing conflict
        markers (from ``git diff --name-only --diff-filter=U``).
        Empty tuple when ``has_conflict`` is False.
      * ``new_head_sha`` — the local commit SHA after a successful
        rebase+push. ``None`` when no push happened.
      * ``pushed`` — ``True`` if the rebased branch was pushed to
        the remote. ``False`` when no rebase was needed (already
        up-to-date) or the push failed.
      * ``push_method`` — one of ``"force_with_lease"`` /
        ``"force"`` / ``"none"``. Lets the audit log distinguish
        operator-explicit ``--force`` runs from the default
        safe-with-lease path.
      * ``workspace_clean`` — ``True`` when no
        ``.git/REBASE_HEAD`` is left behind. ``False`` indicates
        the operator should run ``git rebase --abort`` manually
        (defensive cleanup paths in ``rebase_for_pr`` are
        best-effort).
    """

    rebased: bool
    has_conflict: bool = False
    conflict_files: tuple[str, ...] = field(default_factory=tuple)
    new_head_sha: str | None = None
    pushed: bool = False
    push_method: str = "none"  # "force_with_lease" | "force" | "none"
    workspace_clean: bool = True


def _git_rebase_abort(repo_root: str) -> None:
    """F-120: best-effort ``git rebase --abort``.

    Used by ``rebase_for_pr`` to clear a stuck rebase state when
    pre-flight checks fail (e.g. fetch returned 0 commits, or the
    rebase exited with a non-conflict error like auth failure). The
    command is allowed to fail silently — when no rebase is in
    progress ``git rebase --abort`` returns a non-zero exit code
    with a "No rebase in progress?" message; we don't want that to
    raise and mask the real error.
    """
    stdout, stderr, _rc = _run_git(["rebase", "--abort"], repo_root)
    # ``_run_git`` does not raise on non-zero rc; we explicitly
    # ignore the result.
    del stdout, stderr


def _ahead_behind(repo_root: str, branch: str, base: str) -> tuple[int, int]:
    """Return ``(ahead, behind)`` commit counts of ``branch`` vs ``base``.

    Wraps ``git rev-list --left-right --count branch...base`` and
    parses the two integers from stdout. On parse failure returns
    ``(0, 0)`` so the caller can short-circuit ("nothing to do")
    rather than crash.
    """
    stdout, _stderr, rc = _run_git(
        ["rev-list", "--left-right", "--count", f"{branch}...{base}"],
        repo_root,
    )
    if rc != 0:
        return (0, 0)
    parts = stdout.strip().split()
    if len(parts) != 2:
        return (0, 0)
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (0, 0)


def rebase_for_pr(
    *,
    workspace_path: str,
    branch_name: str,
    base_branch: str,
    force: bool = False,
) -> PRRebaseResult:
    """F-120: resolve a stale-base PR by rebasing the feature branch.

    Flow:
      1. **Pre-flight** — ``git checkout <branch>`` (if not already
         there). Abort any leftover ``.git/REBASE_HEAD`` so the
         fresh rebase doesn't compound a half-finished one.
      2. **Fetch** — ``git fetch --prune origin <base>:<base>`` so
         ``origin/<base>`` reflects the current remote tip.
      3. **Ahead/behind check** — if ``behind_by == 0`` the branch
         is already up-to-date; return immediately (no-op success).
      4. **Rebase** — ``git rebase origin/<base>``. If the command
         exits 0 we're on a fast-forward-friendly history; on
         non-zero exit, ``_detect_conflicts`` reports which files
         have conflict markers. If the failure is non-conflict
         (auth / network), abort the rebase and return
         ``rebased=False, has_conflict=False``.
      5. **Push** — ``git push --force-with-lease=origin/<branch>:
         <remote_sha>`` by default. When ``force=True``, fall
         back to plain ``--force`` (operator-explicit override).
         Push failure rolls back via
         ``git reset --hard origin/<branch>`` so the next
         retry starts from a known good state.
      6. **Return** — a ``PRRebaseResult`` summarizing the
         outcome. The CLI / daemon converts this to audit-log
         lines and ``IssueRecord.mark_conflict`` /
         ``clear_conflict`` calls.

    This function is sync (no ``await``) because it is a thin
    wrapper around ``subprocess.run``-based ``_run_git`` calls.
    Callers in async code paths can ``await asyncio.to_thread(
    rebase_for_pr, ...)`` if they need to yield the event loop
    during long fetches.
    """
    repo_root = workspace_path
    # 0. checkout + defensive rebase --abort (best-effort)
    current_branch = get_current_branch(repo_root)
    if current_branch != branch_name:
        co_stdout, co_stderr, co_rc = _run_git(["checkout", branch_name], repo_root)
        if co_rc != 0:
            raise GitSyncError(
                f"git checkout {branch_name} failed: {co_stderr or co_stdout}"
            )
    _git_rebase_abort(repo_root)

    # 1. fetch base
    fetch_stdout, fetch_stderr, fetch_rc = _run_git(
        ["fetch", "--prune", "origin", f"{base_branch}:{base_branch}"],
        repo_root,
    )
    if fetch_rc != 0:
        # Stale workspace: leave REBASE_HEAD absent and report
        # no-op (the operator can re-run with a corrected base
        # branch or refresh the workspace manually).
        return PRRebaseResult(
            rebased=False,
            push_method="none",
            workspace_clean=True,
        )

    # 2. ahead/behind short-circuit
    ahead, behind = _ahead_behind(repo_root, branch_name, f"origin/{base_branch}")
    if behind == 0:
        # Already up-to-date — no rebase needed.
        head_stdout, _, head_rc = _run_git(["rev-parse", "HEAD"], repo_root)
        head = head_stdout.strip() if head_rc == 0 else None
        return PRRebaseResult(
            rebased=True,
            has_conflict=False,
            conflict_files=(),
            new_head_sha=head,
            pushed=False,
            push_method="none",
            workspace_clean=True,
        )

    # 3. rebase
    rebase_stdout, rebase_stderr, rebase_rc = _run_git(
        ["rebase", f"origin/{base_branch}"],
        repo_root,
    )
    if rebase_rc != 0:
        # Inline the conflict check (the upstream helper is a
        # method on GitSyncService and we are a free function).
        diff_stdout, _, _ = _run_git(
            ["diff", "--name-only", "--diff-filter=U"],
            repo_root,
        )
        conflict_files = tuple(
            f.strip() for f in diff_stdout.strip().splitlines() if f.strip()
        )
        if conflict_files:
            # Leave the rebase in progress — the follow-up agent
            # run will read the conflict markers and resolve
            # them, then ``git rebase --continue`` +
            # ``git push --force-with-lease``.
            return PRRebaseResult(
                rebased=False,
                has_conflict=True,
                conflict_files=conflict_files,
                push_method="none",
                workspace_clean=False,
            )
        # Rare: rebase failed but no conflicts. Could be auth,
        # missing remote, or filesystem permission. Abort the
        # half-finished rebase and report no-op.
        _git_rebase_abort(repo_root)
        return PRRebaseResult(
            rebased=False,
            has_conflict=False,
            push_method="none",
            workspace_clean=True,
        )

    # 4. push (force-with-lease by default; --force on operator request)
    # Capture the remote SHA BEFORE pushing so --force-with-lease
    # refuses if the remote moved between fetch and push.
    remote_sha_stdout, _, remote_sha_rc = _run_git(
        ["rev-parse", f"origin/{branch_name}"], repo_root
    )
    remote_sha = remote_sha_stdout.strip() if remote_sha_rc == 0 else ""
    if force:
        push_stdout, push_stderr, push_rc = _run_git(
            ["push", "--force", "origin", branch_name],
            repo_root,
        )
        push_method = "force"
    elif remote_sha:
        # NOTE: --force-with-lease uses the SHORT ref name (no
        # `origin/` prefix). `git push --force-with-lease=origin/foo:X`
        # is parsed as an extra refspec and silently downgrades to a
        # non-fast-forward rejection. The correct form is
        # `--force-with-lease=foo:<expected-sha>`.
        push_stdout, push_stderr, push_rc = _run_git(
            [
                "push",
                f"--force-with-lease={branch_name}:{remote_sha}",
                "origin",
                branch_name,
            ],
            repo_root,
        )
        push_method = "force_with_lease"
    else:
        # Remote branch doesn't exist yet — fall back to plain
        # ``push -u`` (this is a fresh branch, no history to clobber).
        push_stdout, push_stderr, push_rc = _run_git(
            ["push", "-u", "origin", branch_name],
            repo_root,
        )
        push_method = "none"

    if push_rc != 0:
        # Roll back to the pre-rebase remote tip. The local
        # working tree will be left at the rebased commits; the
        # ``git reset --hard origin/<branch>`` rewinds to the
        # remote so the next attempt starts from a known state.
        rb_stdout, rb_stderr, rb_rc = _run_git(
            ["reset", "--hard", f"origin/{branch_name}"],
            repo_root,
        )
        if rb_rc != 0:
            # Reset failed — surface as a no-op with
            # workspace_clean=False so the operator knows the
            # local tree is in an unknown state.
            return PRRebaseResult(
                rebased=False,
                has_conflict=False,
                push_method="none",
                workspace_clean=False,
            )
        return PRRebaseResult(
            rebased=False,
            has_conflict=False,
            push_method="none",
            workspace_clean=True,
        )

    new_head_stdout, _, new_head_rc = _run_git(["rev-parse", "HEAD"], repo_root)
    new_head = new_head_stdout.strip() if new_head_rc == 0 else None
    return PRRebaseResult(
        rebased=True,
        has_conflict=False,
        conflict_files=(),
        new_head_sha=new_head,
        pushed=True,
        push_method=push_method,
        workspace_clean=True,
    )

