"""Downstream-enhanced REPL (ClawCodexExtREPL).

Subclass of :class:`src.repl.core.ClawcodexREPL` that adds provider
injection, runtime-context awareness, soft-fallback for missing API
keys, session resume, thinking-toggle support, and the ``/provider``
slash command wiring — all without touching ``src/``.

Usage
-----

    from clawcodex_ext.repl.app import ClawCodexExtREPL

    repl = ClawCodexExtREPL(
        provider_name="glm",
        stream=False,
        permission_mode="default",
        is_bypass_permissions_mode_available=False,
        resume_session_id="abc123",
        provider=...,       # optional pre-built provider
        session=...,        # optional pre-built session
        tool_registry=...,
        tool_context=...,
        workspace_root=Path.cwd(),
        runtime_context=...,
    )
    repl.run()
"""

from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.agent import Session
from src.providers.runtime import build_provider_from_config
from src.repl.core import ClawcodexREPL, _MessageHistoryCompleter, _SlashOnlyCompleter

if TYPE_CHECKING:
    pass

from rich.console import Console as RichConsole


class ClawCodexExtREPL(ClawcodexREPL):
    """Downstream-enhanced REPL with provider injection and runtime context.

    Accepts all the same public-method interface as
    :class:`ClawcodexREPL` (``run``, ``handle_command``, ``chat``, …)
    but overrides ``__init__`` and ``_init_command_system`` to support
    downstream extensions.
    """

    def __init__(
        self,
        provider_name: str = "glm",
        stream: bool = False,
        *,
        permission_mode: str = "default",
        is_bypass_permissions_mode_available: bool = False,
        # Downstream-only parameters ------------------------------------
        resume_session_id: str | None = None,
        provider: Any | None = None,
        session: Session | None = None,
        tool_registry: Any | None = None,
        tool_context: Any | None = None,
        workspace_root: Path | None = None,
        runtime_context: Any | None = None,
        append_system_prompt: str = "",
    ) -> None:
        # ---- Shared setup (identical to upstream) ----
        self._permission_mode = permission_mode
        self._is_bypass_permissions_mode_available = bool(
            is_bypass_permissions_mode_available
        )
        self._append_system_prompt = append_system_prompt

        from rich.console import Console
        from clawcodex_ext.repl.color_scheme import (
            build_rich_theme,
            build_ptk_style,
            DARK as _REPL_DARK,
        )
        from rich.theme import Theme as _RichTheme

        self._repl_ptk_style = build_ptk_style(_REPL_DARK)
        self._repl_palette = _REPL_DARK
        self.console = Console(theme=_RichTheme(build_rich_theme(_REPL_DARK)), highlight=False)

        self.runtime_context = runtime_context
        self.provider_name = provider_name
        self.stream = stream
        self.workspace_root = workspace_root or Path.cwd()

        # ---- Provider construction (downstream) ----
        if provider is not None:
            self.provider = provider
            self._api_key_missing = False
        else:
            try:
                self.provider = build_provider_from_config(provider_name)
                self._api_key_missing = False
            except RuntimeError:
                self._api_key_missing = True

        if self._api_key_missing:
            # No configured credentials — initialise minimal read-only state
            self.provider = None
            self.session = None
            self.tool_registry = None
            self.tool_context = None
            self._engine_messages = []
            # ``deque(maxlen=100)`` silently drops the oldest entry once full
            # so a long-running session can't accumulate an unbounded queue
            # under the per-turn lock. See ``clear_pending_turn_buffers`` in
            # core.py for the turn-end reset that runs even on small queues.
            self._queued_prompts: deque[str] = deque(maxlen=100)
            self._cron_queued_prompts: deque[str] = deque(maxlen=100)
            self._queued_prompts_lock = threading.Lock()
            self._original_built_ins = [
                "/", "/help", "/exit", "/quit", "/q", "/clear",
                "/save", "/load", "/stream", "/render-last", "/tools",
                "/tool", "/skills", "/init", "/tui", "/login",
            ]
            self._built_in_commands = list(self._original_built_ins)

            # Minimal prompt session for the missing-key case so that
            # run() doesn't crash on ``self.prompt_session.prompt()``.
            from prompt_toolkit import PromptSession as _P
            self.prompt_session = _P()  # type: ignore[call-arg]
            return

        # ---- Session: create or resume ----
        self._engine_messages: list[Any] = []
        self._resume_session_id = resume_session_id
        self._session_metadata: dict[str, Any] | None = None  # S-R4-M: cached metadata
        if session is not None:
            self.session = session
        elif resume_session_id:
            loaded_session = Session.resume(resume_session_id)
            if loaded_session is not None:
                self.session = loaded_session
                self.console.print(
                    f"[success]Resumed session: {resume_session_id}[/success]"
                )
                self.console.print(
                    f"[dim]Provider: {loaded_session.provider}, "
                    f"Model: {loaded_session.model}[/dim]"
                )
                self._sync_conversation_from_transcript(resume_session_id)
                # Sync historical messages into _engine_messages so the
                # QueryEngine receives the full conversation context
                # (not just new messages from this REPL session).
                self._engine_messages = list(self.session.conversation.messages or [])
                # S-R4-M: load and display session metadata
                self._load_session_metadata(resume_session_id)
            else:
                self.console.print(
                    f"[warning]Session not found: {resume_session_id}. "
                    "Starting new session.[/warning]"
                )
                self.session = Session.create(provider_name, self.provider.model)
        else:
            self.session = Session.create(provider_name, self.provider.model)

        # ---- Tool registry + context ----
        def _get_mcp_servers_for_prompt() -> list[str]:
            ctx = getattr(self, "tool_context", None)
            if ctx is None:
                return []
            clients = getattr(ctx, "mcp_clients", None) or {}
            return list(clients.keys())

        from src.tool_system.defaults import build_default_registry

        self.tool_registry = tool_registry or build_default_registry(
            provider=self.provider,
            get_available_mcp_servers=_get_mcp_servers_for_prompt,
        )

        from src.permissions.types import ToolPermissionContext
        from src.tool_system.context import ToolContext

        if tool_context is None:
            self.tool_context = ToolContext(
                workspace_root=self.workspace_root,
                permission_context=ToolPermissionContext(
                    mode=self._permission_mode,  # type: ignore[arg-type]
                    is_bypass_permissions_mode_available=(
                        self._is_bypass_permissions_mode_available
                    ),
                ),
            )
        else:
            self.tool_context = tool_context
            self.tool_context.workspace_root = self.workspace_root
            self.tool_context.permission_context = ToolPermissionContext(
                mode=self._permission_mode,  # type: ignore[arg-type]
                is_bypass_permissions_mode_available=(
                    self._is_bypass_permissions_mode_available
                ),
            )
        self.tool_context.ask_user = self._ask_user_questions
        self._current_status = None
        if self._permission_mode == "bypassPermissions":
            self.tool_context.allow_docs = True
            self.tool_context.permission_handler = (
                lambda _tn, _msg, _sug: (True, False)
            )
        else:
            self.tool_context.permission_handler = self._handle_permission_request

        # ---- Runtime permission controller (downstream subclass) ----
        # The upstream ``ClawcodexREPL.__init__`` instantiates its own
        # controller, but this subclass overrides ``__init__`` without
        # calling ``super().__init__``, so we build one here. The
        # duplicate ``s-tab`` binding further down in this file routes
        # through it; ``/permissions`` (if any) and the LiveStatus
        # Shift+Tab path also go through the same chokepoint.
        #
        # ``default_permission_handler`` is snapshotted on the
        # ``ToolContext`` so the controller can restore it on cycle
        # OUT of ``bypassPermissions`` without reaching back into
        # ``self._handle_permission_request``.
        if self.tool_context is not None:
            self.tool_context.default_permission_handler = (
                self._handle_permission_request
            )
        from clawcodex_ext.permissions.runtime import (
            RuntimePermissionController,
        )

        self._runtime_permission_controller = RuntimePermissionController(
            tool_context_factory=lambda: self.tool_context,
            default_handler=self._handle_permission_request,
            notify=self._notify_permission_mode_change,
        )

        # ---- State fields (shared with upstream) ----
        self._stats_turns: int = 0
        self._stats_input_tokens: int = 0
        self._stats_output_tokens: int = 0
        self._direct_abort_controller: AbortController | None = None
        # ``deque(maxlen=100)`` silently drops the oldest entry once full
        # so a long-running session can't accumulate an unbounded queue
        # under the per-turn lock. See ``clear_pending_turn_buffers`` in
        # core.py for the turn-end reset that runs even on small queues.
        self._queued_prompts: deque[str] = deque(maxlen=100)
        self._cron_queued_prompts: deque[str] = deque(maxlen=100)
        self._queued_prompts_lock = threading.Lock()
        self._permission_prompt_lock = threading.Lock()
        self._permission_decision_cache: dict[str, bool] = {}
        self._active_live_status: Any = None
        # Wire is_loading on the pre-existing cron scheduler (created by
        # RuntimeContext.build before this REPL was constructed).
        _cron_sched = getattr(self.tool_context, "cron_scheduler", None)
        if _cron_sched is not None:
            _cron_sched.is_loading = lambda: self._active_live_status is not None
        self._expandable_blocks: deque[tuple[str, str]] = deque(maxlen=20)

        # ---- Downstream-only state ----
        self._thinking_visible: bool = True
        # Streaming thought chunks — bounded by ``deque(maxlen=1000)`` so a
        # runaway / backgrounded session can't grow this buffer past ~1k
        # strings. ``clear_pending_turn_buffers`` (in core.py) additionally
        # empties it at every turn boundary for tight memory budgets (the
        # WSL2 3.8 GB OOM repro). ``clear_pending_turn_buffers``.
        self._thinking_chunks: deque[str] = deque(maxlen=1000)

        # ---- Cost tracker & history (created here for _init_command_system)
        from src.cost_tracker import CostTracker
        from src.history import HistoryLog

        self.cost_tracker = CostTracker()
        self.history_log = HistoryLog()

        # ---- Original built-in commands ----
        self._original_built_ins = [
            "/",
            "/help",
            "/exit",
            "/quit",
            "/q",
            "/repl",
            "/clear",
            "/save",
            "/load",
            "/stream",
            "/render-last",
            "/tools",
            "/tool",
            "/skills",
            "/init",
            "/model",
            "/provider",
            "/env",
            "/tui",
            "/login",
            "/permission",
        ]
        self._built_in_commands = list(self._original_built_ins)

        # ---- Initialise command system (must happen before PromptSession) ----
        # NOTE: this is deferred to first use of _init_command_system
        # via the _init_command_system override below; we call it here
        # to match upstream ordering.
        self._init_command_system()

        # ---- Prompt toolkit (from upstream __init__ lines 529-713) ----
        from pathlib import Path as _Path

        from prompt_toolkit.completion import merge_completers
        from prompt_toolkit.history import FileHistory
        from clawcodex_ext.repl.core import (
            _HintedAutoSuggest,
            _patch_accept_suggestion_bindings,
        )
        from prompt_toolkit.styles import Style

        from src.repl.agent_mention_completer import AgentMentionCompleter
        from src.repl.at_file_completer import AtFileCompleter

        history_file = _Path.home() / ".clawcodex" / "history"
        history_file.parent.mkdir(parents=True, exist_ok=True)

        # TTL cache for the slash-command suggestion list.
        self._slash_suggestions_cache: list[Any] | None = None
        self._slash_suggestions_cache_at: float = 0.0

        self._slash_completer = _SlashOnlyCompleter(
            self._get_slash_command_words,
            suggestions_provider=self._get_slash_command_suggestions,
        )
        self._at_completer = AtFileCompleter(
            cwd=str(self.tool_context.workspace_root)
        )
        self._agent_completer = AgentMentionCompleter(
            self._available_agents
        )
        self._message_history_completer = _MessageHistoryCompleter(
            self._get_user_message_history
        )
        self.completer = merge_completers(
            [self._slash_completer, self._at_completer, self._agent_completer, self._message_history_completer]
        )

        # Warm the slash-command suggestion cache in the background.
        threading.Thread(
            target=self._warm_slash_suggestions_cache,
            name="slash-suggestions-warm",
            daemon=True,
        ).start()

        # ---- Key bindings (from upstream __init__ lines 595-682) ----
        from prompt_toolkit.key_binding import KeyBindings

        self.bindings = KeyBindings()
        if hasattr(self.bindings, "add"):

            @self.bindings.add("/")
            def _show_slash_completions(event):
                buf = event.current_buffer
                was_empty = buf.text == ""
                buf.insert_text("/")
                if was_empty:
                    buf.start_completion(select_first=False)

            def _refresh_slash_menu_after_deletion(event, deleter):
                buf = event.current_buffer
                deleter(buf)
                if not (buf.completer and buf.complete_while_typing()):
                    return
                token, _ = _SlashOnlyCompleter._current_slash_token(
                    buf.document.text_before_cursor
                )
                if token is not None:
                    buf.start_completion(select_first=False)

            @self.bindings.add("backspace")
            def _backspace_refreshes_slash_menu(event):
                _refresh_slash_menu_after_deletion(
                    event, lambda b: b.delete_before_cursor(count=1)
                )

            @self.bindings.add("delete")
            def _delete_refreshes_slash_menu(event):
                _refresh_slash_menu_after_deletion(
                    event, lambda b: b.delete(count=1)
                )

            @self.bindings.add("c-m")
            def _enter_submits_or_backslash_newline(event):
                buf = event.current_buffer
                if buf.complete_state:
                    buf.complete_state = None
                    return
                text = buf.text
                pos = buf.cursor_position
                if pos > 0 and text[pos - 1] == "\\":
                    buf.delete_before_cursor(count=1)
                    buf.insert_text("\n")
                    return
                buf.validate_and_handle()

            @self.bindings.add("escape", "c-m")
            def _meta_or_shift_enter_inserts_newline(event):
                event.current_buffer.insert_text("\n")

            @self.bindings.add("c-o")
            def _expand_last(event):
                try:
                    from prompt_toolkit.application import run_in_terminal
                    run_in_terminal(self._do_expand_last)
                except Exception:
                    self._do_expand_last()

            @self.bindings.add("s-tab")  # type: ignore[attr-defined]
            def _cycle_permission_mode(event):  # type: ignore[no-untyped-def]
                """Shift+Tab: cycle through permission modes.

                Mirrors the TypeScript Ink reference's Shift+Tab binding
                for cycling through default → acceptEdits → plan →
                bypassPermissions → default. Routes through
                :class:`RuntimePermissionController` so the lock, the
                ``apply_permission_update`` canonical mutation, the
                AppState listener chain, and the default-handler
                restoration are all shared with the ``/permissions``
                picker and the LiveStatus Shift+Tab path.
                """
                self._apply_permission_mode_cycle()

        # ---- PromptSession ----
        from prompt_toolkit import PromptSession

        try:
            from src.settings.settings import get_settings as _get_settings

            _settings = _get_settings()
            _accept_key = getattr(
                _settings, "accept_suggestion_key", "c-e"
            ) or "c-e"
            _accept_tab_alias = bool(
                getattr(_settings, "accept_suggestion_tab_alias", True)
            )
        except Exception:
            _accept_key = "c-e"
            _accept_tab_alias = True

        self._file_history = FileHistory(str(history_file))
        self.prompt_session = PromptSession(
            history=self._file_history,
            auto_suggest=_HintedAutoSuggest(
                accept_key=_accept_key,
                has_tab_alias=_accept_tab_alias,
            ),
            completer=self.completer,
            style=Style.from_dict(self._repl_ptk_style),
            key_bindings=self.bindings,
            complete_while_typing=True,
            multiline=True,
            prompt_continuation=self._prompt_continuation,
            bottom_toolbar=self._bottom_toolbar,
        )
        _patch_accept_suggestion_bindings(
            self.bindings,
            accept_key=_accept_key,
            has_tab_alias=_accept_tab_alias,
        )

    # ---- Override _init_command_system to pass downstream fields ----

    def _init_command_system(self) -> None:
        """Initialise the command system with downstream context."""
        from src.command_system import (
            CommandRegistry,
            create_command_context,
            register_builtin_commands,
        )

        register_builtin_commands(None)

        self.command_registry = CommandRegistry()
        register_builtin_commands(self.command_registry)

        # Register downstream runtime commands (/provider, /model)
        from clawcodex_ext.cli.runtime_commands import register_runtime_commands
        register_runtime_commands(self.command_registry)  # instance registry (autocomplete)
        register_runtime_commands(None)  # global registry (execute_command_sync lookup)
        from clawcodex_ext.away_summary.registration import register_away_summary_commands
        register_away_summary_commands(self.command_registry)
        register_away_summary_commands(None)

        try:
            from extensions.skills_ext import init_skills_ext
            init_skills_ext()
        except Exception:
            pass

        self.command_context = create_command_context(
            workspace_root=self.workspace_root,
            conversation=self.session.conversation,
            cost_tracker=self.cost_tracker,
            history=self.history_log,
            provider=self.provider,
            tool_registry=self.tool_registry,
            tool_context=self.tool_context,
            runtime_context=self.runtime_context,
        )

        self._update_built_in_commands_with_command_system()

    # ---- Runtime permission controller helpers ----
    # Mirrors the upstream ``ClawcodexREPL`` methods. The downstream
    # subclass overrides ``__init__`` without calling ``super().__init__``,
    # so the controller is instantiated locally (see ``__init__`` above)
    # and these helpers route the ``s-tab`` binding (registered in
    # ``__init__``) through the chokepoint. Sharing the helper with the
    # upstream class keeps the two implementations in lockstep — any
    # future change to the controller contract only needs to be applied
    # in one place.
    def _apply_permission_mode_cycle(self) -> None:
        """Shift+Tab: cycle to the next permission mode.

        Routes through :class:`RuntimePermissionController` so the
        same lock / ``apply_permission_update`` / AppState-write /
        handler-restore logic is shared with the ``/permissions``
        picker and the LiveStatus Shift+Tab path.
        """
        next_mode = self._runtime_permission_controller.cycle()
        self._permission_mode = next_mode

    def _notify_permission_mode_change(self, mode: str) -> None:
        """Surface a mode change in the live status row or console.

        Called by the runtime controller after the multi-field swap.
        When a :class:`LiveStatus` is mounted (i.e. the agent is
        running), update its visible message — the user sees the new
        mode inline in the spinner row. Otherwise fall through to
        :meth:`console.print` so the change is visible between turns.
        """
        status = getattr(self, "_active_live_status", None)
        if status is not None:
            try:
                status.update(f"mode: {mode}")
            except Exception:
                pass
            return
        try:
            self.console.print(f"[success]Permission mode: {mode}[/success]")
        except Exception:
            pass

    # ---- S-R4-M: session metadata management ----

    def _load_session_metadata(self, session_id: str) -> None:
        """Load metadata from SessionStorage and cache it on the instance."""
        try:
            from src.services.session_storage import SessionStorage
            storage = SessionStorage(session_id=session_id)
            meta = storage.get_metadata()
            if meta is not None:
                self._session_metadata = {
                    "session_id": meta.session_id,
                    "title": meta.title or "",
                    "model": meta.model or "",
                    "cwd": meta.cwd or "",
                    "last_user_input": meta.last_user_input or "",
                    "message_count": meta.message_count,
                    "start_time": meta.start_time,
                    "last_updated": meta.last_updated,
                }
                # Display title if set
                if meta.title:
                    self.console.print(f"[dim]Session title: {meta.title}[/dim]")
        except Exception:
            self._session_metadata = None

    def _update_metadata_last_input(self, text: str) -> None:
        """Update the ``last_user_input`` field in SessionStorage metadata."""
        if not self.session:
            return
        try:
            from src.services.session_storage import SessionStorage
            storage = SessionStorage(session_id=self.session.session_id)
            storage.update_metadata(last_user_input=text[:200])  # cap at 200 chars
        except Exception:
            pass

    # ---- S-R4-A: agent metadata tracking ----

    def _update_metadata_agent(self, agent_name: str) -> None:
        """Store the agent name in SessionStorage metadata."""
        if not self.session:
            return
        try:
            from src.services.session_storage import SessionStorage
            storage = SessionStorage(session_id=self.session.session_id)
            storage.update_metadata(agent_name=agent_name)
        except Exception:
            pass

    # ---- S-R4-M: track last_user_input in metadata (override chat) ----

    def chat(self, user_input: str, max_turns: int | None = None):
        """Override chat() to track the last user input in metadata."""
        self._update_metadata_last_input(user_input)
        controller = getattr(self, "_away_summary_controller", None)
        if controller is not None:
            controller.on_run_start()
        # F-9: also start the ``/goal`` controller so it knows a new
        # assistant turn is about to begin. Auto-continuation is
        # driven from ``on_assistant_turn_complete`` in the
        # ``finally`` block, parallel to the away-summary path.
        goal_controller = getattr(self, "_goal_controller", None)
        if goal_controller is not None:
            try:
                goal_controller.on_run_start()
            except Exception:
                pass
        try:
            return super().chat(user_input, max_turns=max_turns)
        finally:
            if controller is not None:
                controller.on_run_finish()
                controller.on_assistant_turn_complete()
            if goal_controller is not None:
                try:
                    goal_controller.on_run_finish()
                    goal_controller.on_assistant_turn_complete()
                except Exception:
                    pass
