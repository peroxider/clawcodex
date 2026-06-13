"""Prompt input widget — bottom ``❯`` line with slash palette + history.

Port of ``typescript/src/components/PromptInput/PromptInput.tsx`` at the
fidelity required to feel like the ink reference:

* Multi-line editing via ``Shift+Enter`` / ``Ctrl+J`` (Textual's default)
  with plain ``Enter`` submitting the prompt.
* Slash-command palette opens when the current token starts with ``/``
  and fuzzy-filters as the user types.
* ``@``-file completions open when the current token starts with ``@``,
  using the same matching logic as the REPL (``src/utils/at_file_completer``).
* Up / Down navigate the in-session history when the palette is closed;
  when it is open, arrow keys drive the option list.
* ``Escape`` closes the palette without losing the draft.
* ``Ctrl+L`` clears the draft.

Phase 1 deliberately keeps the implementation single-line-in-practice
(using Textual's ``Input``) but exposes :meth:`set_multiline` for
Phase 2 to swap in a ``TextArea`` without changing the public surface.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from ..commands import CommandSuggestion
from ..messages import CancelRequested, PermissionModeCycleRequested, PromptPasted
from ..paste import PasteInfo, classify_paste
from ..vim import VimState
from .prompt_input_footer import PromptInputFooter
from .prompt_input_mode_indicator import PromptInputModeIndicator

# Reuse the same matching machinery as the prompt_toolkit REPL.
# ``_AT_TOKEN_RE`` matches ``@<query>`` at the cursor position;
# ``_is_path_like_token`` / ``_path_completions`` handle absolute
# and explicit-relative paths by walking the filesystem directly;
# ``_filter_candidates`` ranks project-file hits by substring,
# subsequence and fuzzy signals with a 26-bit bitmap pre-filter.
# ``_list_git_files`` / ``_walk_filesystem`` provide the candidate list.
from src.utils.at_file_completer import (  # type: ignore[import-untyped]
    _AT_TOKEN_RE,
    _build_path_bitmap,
    _filter_candidates,
    _is_path_like_token,
    _list_git_files,
    _MAX_SUGGESTIONS as _AT_FILE_MAX_SUGGESTIONS,
    _path_completions,
    _walk_filesystem,
)

# How long we cache the project-file index (same as ``AtFileCompleter``).
_FILE_CACHE_TTL = 5.0


@dataclass
class PromptSubmitted(Message):
    """User pressed Enter on a non-empty prompt."""

    text: str


class _PasteAwareInput(Input):
    """``Input`` subclass that routes bracketed paste through the host.

    The stock Textual ``Input._on_paste`` truncates the payload to the
    first line and bypasses any custom paste handler on the parent
    widget. That destroys the very property chapter 14 calls out as
    "critical for security" — the bracketed-paste envelope must travel
    intact so the host can decide whether it is a literal text insert,
    an image-file drag, or an empty-paste image-clipboard sentinel.

    This subclass intercepts ``events.Paste`` before the stock handler
    runs and forwards it to the surrounding :class:`PromptInput` via
    ``parent.handle_paste``. The Input itself does not insert anything;
    the host owns the buffer mutation so vim-mode shims, slash-popup
    suppression, and history-pointer hygiene all happen in one place.
    """

    def _on_paste(self, event: events.Paste) -> None:  # type: ignore[override]
        # Walk up the widget tree looking for a parent that knows how
        # to absorb a bracketed paste. ``hasattr`` avoids a forward
        # reference to :class:`PromptInput` (which is declared below
        # to keep the file readable top-down).
        node = self.parent
        for _ in range(8):  # bounded walk; the tree is always shallow.
            if node is None:
                break
            handler = getattr(node, "handle_paste", None)
            if callable(handler):
                handler(event.text)
                # ``prevent_default`` is what stops Textual's MRO
                # walker from also invoking the stock
                # ``Input._on_paste`` (which would truncate the
                # payload to the first line and double-insert).
                # ``stop`` then halts bubbling to ancestor widgets so
                # the host does not see the raw Paste twice.
                event.prevent_default()
                event.stop()
                return
            node = getattr(node, "parent", None)
        # Fallback to the stock behaviour if we've been re-parented
        # outside a :class:`PromptInput` host.
        super()._on_paste(event)


_NAME_COLUMN_WIDTH = 22  # left column reserved for "/name (alias)"
_MAX_VISIBLE_SUGGESTIONS = 10


class _SlashSuggestions(OptionList):
    DEFAULT_CSS = """
    _SlashSuggestions {
        max-height: 10;
        border: none;
        padding: 0;
        background: $background;
    }
    _SlashSuggestions > .option-list--option {
        padding: 0 1;
    }
    _SlashSuggestions > .option-list--option-highlighted {
        background: $boost;
        text-style: bold;
    }
    _SlashSuggestions.-hidden {
        display: none;
    }
    """


class _MessageSuggestions(OptionList):
    """Popup for message-history completions."""

    DEFAULT_CSS = """
    _MessageSuggestions {
        max-height: 6;
        border: none;
        padding: 0;
        background: $background;
        height: auto;
    }
    _MessageSuggestions > .option-list--option {
        padding: 0 1;
    }
    _MessageSuggestions > .option-list--option-highlighted {
        background: $boost;
        text-style: bold;
    }
    _MessageSuggestions.-hidden {
        display: none;
    }
    """


class _AtFileSuggestions(OptionList):
    """Popup for ``@`` file-path completions."""

    DEFAULT_CSS = """
    _AtFileSuggestions {
        max-height: 12;
        border: none;
        padding: 0;
        background: $background;
        height: auto;
    }
    _AtFileSuggestions > .option-list--option {
        padding: 0 1;
    }
    _AtFileSuggestions > .option-list--option-highlighted {
        background: $boost;
        text-style: bold;
    }
    _AtFileSuggestions.-hidden {
        display: none;
    }
    """


def _current_at_token(text_before_cursor: str) -> str | None:
    """Return the query after ``@`` at the current cursor position, or None.

    A valid ``@`` token must be at the start of the buffer or preceded
    by whitespace — ``foo@bar`` (e.g. an email address) does not count.
    This mirrors the same rule in ``AtFileCompleter.get_completions``.
    """
    match = _AT_TOKEN_RE.search(text_before_cursor)
    if match is None:
        return None
    at_pos = match.start()
    if at_pos > 0 and not text_before_cursor[at_pos - 1].isspace():
        return None
    return match.group(1)


class PromptInput(Vertical):
    """Input line plus slash-command suggestion popup."""

    DEFAULT_CSS = """
    PromptInput {
        height: auto;
        padding: 0 0;
    }
    PromptInput > Input {
        border: round $primary-darken-2;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("ctrl+l", "clear_draft", "Clear draft"),
    ]

    def __init__(
        self,
        *,
        words_provider: Callable[[], list[str]],
        suggestions_provider: Callable[[], list[CommandSuggestion]] | None = None,
        message_history_provider: Callable[[], list[str]] | None = None,
        cwd: str | os.PathLike[str] | None = None,
        vim_mode: bool = False,
    ) -> None:
        super().__init__()
        self._words_provider = words_provider
        self._suggestions_provider = suggestions_provider
        self._message_history_provider = message_history_provider
        self._message_completions: list[str] = []
        self._message_completion_pos: int | None = None
        self._history: list[str] = []
        self._history_pos: int | None = None
        self._input = _PasteAwareInput(placeholder="Type a prompt, or / for commands")
        self._suggestions = _SlashSuggestions(classes="-hidden")
        self._message_suggestions = _MessageSuggestions(classes="-hidden")
        self._at_file_suggestions = _AtFileSuggestions(classes="-hidden")
        self._vim = VimState(enabled=vim_mode)
        self._yank_buffer: str = ""
        # Round 2 / WI-R2.5: most-recent bracketed paste classification.
        # Test seam — the host reads :class:`PromptPasted` instead.
        self._last_paste: PasteInfo | None = None
        # Round 2 / WI-R2.4: passive status surfaces around the input.
        # The mode indicator subscribes to ``VimState`` directly; the
        # footer reads ``VimState.enabled`` lazily. Both mounted as
        # siblings of the existing ``Input`` + ``OptionList`` pair.
        self._mode_indicator = PromptInputModeIndicator(vim_state=self._vim)
        self._footer = PromptInputFooter(vim_state=self._vim)
        # ---- ``@`` file-completion state ----
        self._cwd = Path(cwd or os.getcwd()).resolve()
        self._file_cache: list[str] = []
        self._file_cache_bitmaps: list[int] = []
        self._file_cache_built_at: float = 0.0

    def compose(self) -> ComposeResult:
        yield self._mode_indicator
        yield self._input
        yield self._suggestions
        yield self._message_suggestions
        yield self._at_file_suggestions
        yield self._footer

    def on_mount(self) -> None:
        self._input.focus()

    # ---- external API ----
    def focus_input(self) -> None:
        self._input.focus()

    def clear(self) -> None:
        self._input.value = ""
        self._hide_suggestions()
        self._hide_message_suggestions()

    def set_value(self, value: str) -> None:
        """Replace the draft text in the prompt (used by /history)."""

        self._input.value = value or ""
        self._hide_suggestions()
        self._hide_message_suggestions()

    # ---- bracketed paste ----
    def handle_paste(self, text: str) -> PasteInfo:
        """Insert a bracketed-paste payload as a single atomic operation.

        Bypasses the slash-popup recomputer, the history pointer, and
        the vim chord tracker — pasted characters must always reach the
        buffer literally even when they happen to spell a chord prefix.
        Chapter 14 calls this the ``isPasted`` invariant; the Python
        port honours it by funnelling every bracketed paste through
        this single entry point.

        Returns the :class:`PasteInfo` so callers (typically tests) can
        assert on classification without having to listen for the
        :class:`PromptPasted` message.
        """

        info = classify_paste(text)
        self._last_paste = info
        if not info.is_empty:
            inp = self._input
            value = inp.value or ""
            pos = max(0, min(inp.cursor_position, len(value)))
            new_value = value[:pos] + info.text + value[pos:]
            inp.value = new_value
            inp.cursor_position = pos + info.length
        # Pasted content must never reopen the slash palette; the user
        # paste-bombed the prompt and likely wants to keep typing or
        # submit. Same rationale as the TS ``usePasteHandler`` reset.
        self._hide_suggestions()
        # Paste must never disturb the history cursor — leaving
        # ``_history_pos`` untouched here is the explicit contract.
        self.post_message(PromptPasted(info=info))
        return info

    @property
    def last_paste(self) -> PasteInfo | None:
        """Most recent classified paste (test seam)."""

        return self._last_paste

    def action_clear_draft(self) -> None:
        self.clear()

    def set_enabled(self, enabled: bool) -> None:
        """Enable / disable the input (used when a modal steals focus)."""

        self._input.disabled = not enabled
        if enabled:
            self._input.focus()

    # ---- vim mode ----
    def set_vim_mode(self, enabled: bool) -> None:
        """Toggle vim-mode on the prompt."""

        self._vim.set_enabled(enabled)
        # ``VimState`` listeners only fire on actual mode transitions
        # (Round 2 / WI-R2.1), so the enable/disable flip itself needs
        # an explicit refresh on the surrounding status surfaces.
        try:
            self._mode_indicator.refresh_mode()
            self._footer.refresh_hints()
        except Exception:
            # Pre-mount: ``compose`` will render with the right state.
            pass

    @property
    def vim_mode(self) -> bool:
        return self._vim.enabled

    @property
    def vim_state(self) -> VimState:  # exposed for tests / status line
        return self._vim

    # ---- input events ----
    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_suggestions(event.value, event.input.cursor_position)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        # If the palette is open and a row is highlighted, accept the
        # selection instead of submitting the partial prompt.
        if not self._suggestions.has_class("-hidden"):
            idx = self._suggestions.highlighted
            if idx is not None:
                option = self._suggestions.get_option_at_index(idx)
                if option is not None and option.id and option.id != text:
                    self._input.value = option.id
                    self._input.cursor_position = len(option.id)
                    self._hide_suggestions()
                    return
        # If @ file suggestions are open and a row is highlighted, accept
        # the selection instead of submitting.
        if not self._at_file_suggestions.has_class("-hidden"):
            idx = self._at_file_suggestions.highlighted
            if idx is not None:
                option = self._at_file_suggestions.get_option_at_index(idx)
                if option is not None and option.id and option.id != text:
                    self._input.value = option.id
                    self._input.cursor_position = len(option.id)
                    self._hide_at_file_suggestions()
                    return
        self._history.append(text)
        self._history_pos = None
        self._hide_suggestions()
        self._hide_at_file_suggestions()
        self._input.value = ""
        ## _log(f'[prompt_input] posting PromptSubmitted: {text}')
        self.post_message(PromptSubmitted(text=text))

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Handle Enter/Space on a suggestion row — insert the command."""
        if event.option.id:
            self._input.value = event.option.id
            self._input.cursor_position = len(event.option.id)
            # ``OptionList.OptionSelected`` exposes its source list via
            # ``option_list`` (``Message.sender`` is not an attribute on
            # the base ``Message`` in this Textual version, so the old
            # ``event.sender is …`` comparison raised AttributeError).
            if event.option_list is self._at_file_suggestions:
                self._hide_at_file_suggestions()
            elif event.option_list is self._message_suggestions:
                self._hide_message_suggestions()
            else:
                self._hide_suggestions()

    async def on_key(self, event: events.Key) -> None:
        key = event.key

        # Shift+Tab: cycle permission mode. Intercept here so it works
        # even when the Input child has focus (Textual's default focus
        # navigation would otherwise consume the key before the screen
        # binding fires).
        if key == "shift+tab":
            self.post_message(PermissionModeCycleRequested())
            event.stop()
            return

        # Vim mode: consume chord-owned keys before the Input sees them.
        if self._vim.enabled:
            result = self._vim.handle(key)
            if result.consumed:
                if result.action is not None:
                    self._apply_vim_action(result.action)
                event.stop()
                return

        if key == "escape" and not self._suggestions.has_class("-hidden"):
            self._hide_suggestions()
            event.stop()
            return
        if key == "escape" and not self._message_suggestions.has_class("-hidden"):
            self._hide_message_suggestions()
            event.stop()
            return
        if key == "escape" and not self._at_file_suggestions.has_class("-hidden"):
            self._hide_at_file_suggestions()
            event.stop()
            return
        if key == "escape":
            # Bubble up to the app; it decides whether to actually
            # cancel based on whether the agent bridge is busy.
            # Mirrors the TS reference's chat:cancel keybinding.
            self.post_message(CancelRequested())
            event.stop()
            return
        if key in ("up", "down"):
            # @ file suggestions take top priority
            if not self._at_file_suggestions.has_class("-hidden"):
                if key == "up":
                    self._at_file_suggestions.action_cursor_up()
                else:
                    self._at_file_suggestions.action_cursor_down()
                event.stop()
                return
            # Message-history popup takes second priority
            if not self._message_suggestions.has_class("-hidden"):
                if key == "up":
                    self._message_suggestions.action_cursor_up()
                else:
                    self._message_suggestions.action_cursor_down()
                event.stop()
                return
            if not self._suggestions.has_class("-hidden"):
                self._suggestions.focus()
                if key == "up":
                    self._suggestions.action_cursor_up()
                else:
                    self._suggestions.action_cursor_down()
                event.stop()
                return
            self._navigate_history(1 if key == "up" else -1)
            event.stop()
            return
        if key == "tab":
            # Tab: if @ file suggestions popup is open, accept the
            # highlighted item.
            if not self._at_file_suggestions.has_class("-hidden"):
                idx = self._at_file_suggestions.highlighted
                if idx is not None:
                    opt = self._at_file_suggestions.get_option_at_index(idx)
                    if opt is not None and opt.id:
                        self._input.value = opt.id
                        self._input.cursor_position = len(opt.id)
                        self._hide_at_file_suggestions()
                event.stop()
                return
            # Tab: if message-suggestions popup is open, accept the
            # highlighted item.
            if not self._message_suggestions.has_class("-hidden"):
                idx = self._message_suggestions.highlighted
                if idx is not None:
                    opt = self._message_suggestions.get_option_at_index(idx)
                    if opt is not None and opt.id:
                        self._input.value = opt.id
                        self._input.cursor_position = len(opt.id)
                        self._hide_message_suggestions()
                event.stop()
                return
            # No popup open — try to trigger @ file completions first
            text = self._input.value or ""
            cursor = self._input.cursor_position
            at_query = _current_at_token(text[:cursor])
            if at_query is not None:
                self._refresh_at_file_suggestions(at_query)
                if not self._at_file_suggestions.has_class("-hidden"):
                    event.stop()
                    return
            # Then try message-history completions
            self._refresh_message_suggestions(text, cursor)
            if not self._message_suggestions.has_class("-hidden"):
                event.stop()
                return
            # Fall through to slash suggestions if message history has
            # nothing (keeps slash-completion via / working normally).

    # ---- vim action application ----
    def _apply_vim_action(self, action: str) -> None:
        inp = self._input
        value = inp.value or ""
        pos = inp.cursor_position
        if action == "insert-before":
            return
        if action == "insert-after":
            inp.cursor_position = min(len(value), pos + 1)
        elif action == "insert-line-start":
            inp.cursor_position = 0
        elif action == "insert-line-end":
            inp.cursor_position = len(value)
        elif action == "move-left":
            inp.cursor_position = max(0, pos - 1)
        elif action == "move-right":
            inp.cursor_position = min(len(value), pos + 1)
        elif action == "move-start":
            inp.cursor_position = 0
        elif action == "move-end":
            inp.cursor_position = len(value)
        elif action == "move-word-next":
            inp.cursor_position = _next_word(value, pos)
        elif action == "move-word-prev":
            inp.cursor_position = _prev_word(value, pos)
        elif action == "delete-char":
            if pos < len(value):
                inp.value = value[:pos] + value[pos + 1 :]
        elif action == "delete-line":
            self._yank_buffer = value
            inp.value = ""
        elif action == "yank-line":
            self._yank_buffer = value
        elif action == "paste-after":
            if self._yank_buffer:
                inp.value = value[: pos + 1] + self._yank_buffer + value[pos + 1 :]
                inp.cursor_position = pos + 1 + len(self._yank_buffer)
        elif action == "paste-before":
            if self._yank_buffer:
                inp.value = value[:pos] + self._yank_buffer + value[pos:]
                inp.cursor_position = pos + len(self._yank_buffer)
        elif action == "submit":
            text = value.strip()
            if text:
                self._history.append(text)
                self._history_pos = None
                inp.value = ""
                self.post_message(PromptSubmitted(text=text))

    # ---- suggestion plumbing ----
    def _refresh_suggestions(self, text: str, cursor: int) -> None:
        token, _ = _current_slash_token(text[:cursor])
        if token is not None:
            # Slash mode: show command suggestions
            self._hide_message_suggestions()
            self._hide_at_file_suggestions()
            partial = token[1:].lower()

            options = self._build_suggestion_options(partial)
            if not options:
                self._hide_suggestions()
                return
            self._suggestions.clear_options()
            self._suggestions.add_options(options)
            self._suggestions.highlighted = 0
            self._suggestions.remove_class("-hidden")
            return

        # Check for ``@`` file-completion token
        at_query = _current_at_token(text[:cursor])
        if at_query is not None:
            self._hide_suggestions()
            self._hide_message_suggestions()
            self._refresh_at_file_suggestions(at_query)
            return

        # Non-slash, non-@ mode: hide slash suggestions, check message history
        self._hide_suggestions()
        self._hide_at_file_suggestions()
        self._refresh_message_suggestions(text, cursor)

    def _build_suggestion_options(self, partial: str) -> list[Option]:
        """Return the rich Option rows to show under the prompt.

        Prefers the rich ``suggestions_provider`` (two-column ``/name +
        description`` layout to match the TS reference); falls back to
        the ``words_provider`` string list when no rich source exists
        (legacy tests, embedded uses).
        """

        if self._suggestions_provider is not None:
            try:
                suggestions = self._suggestions_provider() or []
            except Exception:
                suggestions = []
            return _options_from_suggestions(suggestions, partial)

        words = self._words_provider() or []
        return _options_from_words(words, partial)

    def _hide_suggestions(self) -> None:
        if not self._suggestions.has_class("-hidden"):
            self._suggestions.add_class("-hidden")
            self._suggestions.clear_options()

    def _refresh_message_suggestions(self, text: str, cursor: int) -> None:
        """Refresh message-history completions when not in slash mode.

        Collects the current token (non-whitespace word) under the cursor.
        If it matches the start of any previous user message, shows them
        in a popup below the input line.
        """
        if not self._message_history_provider:
            self._hide_message_suggestions()
            return

        # Guard against stale cursor positions (e.g. after programmatic
        # ``_input.value = ""`` while the widget still reports the old
        # cursor offset). Without this, ``prefix[i]`` below IndexErrors.
        if cursor > len(text):
            self._hide_message_suggestions()
            return

        # Extract the current token (non-whitespace word) under cursor.
        prefix = text[:cursor]
        # Find the start of the current token
        i = cursor - 1
        while i >= 0 and not prefix[i].isspace():
            i -= 1
        current_token = prefix[i + 1: cursor]

        if not current_token:
            self._hide_message_suggestions()
            return

        token_lower = current_token.lower()

        try:
            history = self._message_history_provider() or []
        except Exception:
            self._hide_message_suggestions()
            return

        # Find matching messages, ranked by relevance
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for idx, msg in enumerate(reversed(history)):
            if not isinstance(msg, str):
                continue
            msg_key = msg.lower()
            if msg_key in seen:
                continue
            seen.add(msg_key)

            if msg_key == token_lower:
                scored.append((0, idx, msg))
            elif msg_key.startswith(token_lower):
                scored.append((1, idx, msg))
            elif _fuzzy_match(msg_key, token_lower):
                scored.append((2, idx, msg))

        scored.sort(key=lambda t: (t[0], t[1]))
        scored = scored[:_MAX_VISIBLE_SUGGESTIONS]

        if not scored:
            self._hide_message_suggestions()
            return

        self._message_suggestions.clear_options()
        for rank, idx, full_msg in scored:
            display = full_msg[:100] + ("..." if len(full_msg) > 100 else "")
            self._message_suggestions.add_option(display, id=full_msg)
        self._message_suggestions.highlighted = 0
        self._message_suggestions.remove_class("-hidden")

    def _hide_message_suggestions(self) -> None:
        if not self._message_suggestions.has_class("-hidden"):
            self._message_suggestions.add_class("-hidden")

    # ---- ``@`` file suggestion plumbing ----

    def _get_cached_file_list(self) -> tuple[list[str], list[int]]:
        """Return a snapshot of the project-file index, rebuilding if stale.

        Mirrors the 5-second TTL of ``AtFileCompleter._candidates_snapshot``.
        Returns ``(paths, bitmaps)`` — the bitmaps are 26-bit ints encoding
        lowercase a-z presence for fast pre-filtering in ``_filter_candidates``.
        """
        now = time.monotonic()
        if (
            self._file_cache
            and (now - self._file_cache_built_at) < _FILE_CACHE_TTL
        ):
            return self._file_cache, self._file_cache_bitmaps

        paths = _list_git_files(self._cwd)
        if paths is None:
            paths = _walk_filesystem(self._cwd)
        paths.sort(key=str.lower)
        self._file_cache = paths
        self._file_cache_bitmaps = [_build_path_bitmap(p) for p in paths]
        self._file_cache_built_at = time.monotonic()
        return self._file_cache, self._file_cache_bitmaps

    def _refresh_at_file_suggestions(self, query: str) -> None:
        """Refresh the ``@`` file-suggestion popup based on the typed query.

        Two code paths:
        * Path-like tokens (``@/...``, ``@~/...``, ``@./...``, ``@../...``)
          walk the filesystem directly via ``_path_completions``.
        * Plain queries (``@src/uti``) are matched against the cached
          project-file index via ``_filter_candidates``.
        """
        if _is_path_like_token(query):
            entries = _path_completions(query, _AT_FILE_MAX_SUGGESTIONS)
            if not entries:
                self._hide_at_file_suggestions()
                return
            self._at_file_suggestions.clear_options()
            for entry in entries:
                self._at_file_suggestions.add_option(
                    entry.display, id="@" + entry.text,
                )
            self._at_file_suggestions.highlighted = 0
            self._at_file_suggestions.remove_class("-hidden")
            return

        candidates, bitmaps = self._get_cached_file_list()
        if not candidates:
            self._hide_at_file_suggestions()
            return

        matches = _filter_candidates(
            candidates, query, _AT_FILE_MAX_SUGGESTIONS, bitmaps=bitmaps,
        )
        if not matches:
            self._hide_at_file_suggestions()
            return

        self._at_file_suggestions.clear_options()
        for path in matches:
            self._at_file_suggestions.add_option(path, id="@" + path)
        self._at_file_suggestions.highlighted = 0
        self._at_file_suggestions.remove_class("-hidden")

    def _hide_at_file_suggestions(self) -> None:
        if not self._at_file_suggestions.has_class("-hidden"):
            self._at_file_suggestions.add_class("-hidden")
            self._at_file_suggestions.clear_options()
            self._message_suggestions.clear_options()

    def _navigate_history(self, direction: int) -> None:
        """``direction`` = +1 means older (Up); -1 means newer (Down)."""
        if not self._history:
            return
        if direction > 0:
            if self._history_pos is None:
                self._history_pos = len(self._history) - 1
            else:
                self._history_pos = max(0, self._history_pos - 1)
        else:
            if self._history_pos is None:
                return
            self._history_pos += 1
            if self._history_pos >= len(self._history):
                self._history_pos = None
                self._input.value = ""
                return
        self._input.value = self._history[self._history_pos]
        self._input.cursor_position = len(self._input.value)


def _options_from_suggestions(
    suggestions: list[CommandSuggestion],
    partial: str,
) -> list[Option]:
    """Filter + rank rich command suggestions, then render two-column rows.

    Sort order matches the TS ranking spirit: exact name → exact alias
    → prefix name → prefix alias → fuzzy subsequence. Duplicates (same
    name) are collapsed; aliases are surfaced only when the user typed
    them so an unmatched ``/com<TAB>`` does not get polluted with the
    full alias list.
    """

    scored: list[tuple[int, int, CommandSuggestion, str | None]] = []
    seen: set[str] = set()
    for idx, sugg in enumerate(suggestions):
        if not isinstance(sugg, CommandSuggestion):
            continue
        name_lc = sugg.name.lower()
        if name_lc in seen:
            continue
        matched_alias: str | None = None
        rank: int | None = None
        if not partial:
            # Preserve the provider's order — built-ins first, then
            # skills — by collapsing every entry into one rank bucket
            # and tiebreaking on the insertion index below.
            rank = 0
        elif name_lc == partial:
            rank = 0
        else:
            alias_exact = next(
                (a for a in sugg.aliases if a.lower() == partial), None
            )
            if alias_exact:
                rank = 1
                matched_alias = alias_exact
            elif name_lc.startswith(partial):
                rank = 2
            else:
                alias_prefix = next(
                    (a for a in sugg.aliases if a.lower().startswith(partial)),
                    None,
                )
                if alias_prefix:
                    rank = 3
                    matched_alias = alias_prefix
                elif _fuzzy_match(name_lc, partial):
                    rank = 5
                else:
                    alias_fuzzy = next(
                        (a for a in sugg.aliases if _fuzzy_match(a.lower(), partial)),
                        None,
                    )
                    if alias_fuzzy:
                        rank = 6
                        matched_alias = alias_fuzzy
        if rank is None:
            continue
        seen.add(name_lc)
        # Tiebreak: for an empty partial preserve insertion order so
        # built-ins lead skills; otherwise shorter names (closer to
        # the typed prefix) sort first, then alphabetically.
        secondary = idx if not partial else len(sugg.name)
        scored.append((rank, secondary, sugg, matched_alias))

    scored.sort(key=lambda t: (t[0], t[1], t[2].name.lower()))
    scored = scored[:_MAX_VISIBLE_SUGGESTIONS]
    return [
        Option(_render_suggestion_row(sugg, matched_alias), id=sugg.slash)
        for _, _, sugg, matched_alias in scored
    ]


def _options_from_words(words: list[Any], partial: str) -> list[Option]:
    """Fallback renderer for the legacy ``words_provider`` path.

    Produces the same plain ``/name`` rows the older popup used, with
    the same fuzzy filter — so older callers / tests keep working
    while richer surfaces opt into the two-column layout.
    """

    matches: list[str] = []
    seen: set[str] = set()
    for word in words:
        if not isinstance(word, str) or not word.startswith("/"):
            continue
        key = word[1:].lower()
        if key in seen:
            continue
        if not partial or _fuzzy_match(key, partial):
            seen.add(key)
            matches.append(word)
            if len(matches) >= _MAX_VISIBLE_SUGGESTIONS:
                break
    return [Option(word, id=word) for word in matches]


def _render_suggestion_row(
    sugg: CommandSuggestion,
    matched_alias: str | None,
) -> Text:
    """Render one slash-command row as a Rich ``Text`` with two columns.

    Column 1: ``/name`` (plus ``(alias)`` if the user typed an alias),
    padded to :data:`_NAME_COLUMN_WIDTH`. Column 2: optional
    ``[tag]`` then the command description. The whole row is dim by
    default; OptionList's highlighted-row CSS overlays bold + boost
    background on the selected entry (see ``_SlashSuggestions``).
    """

    alias_text = f" ({matched_alias})" if matched_alias else ""
    name_segment = f"{sugg.slash}{alias_text}"
    if len(name_segment) > _NAME_COLUMN_WIDTH - 1:
        name_segment = name_segment[: _NAME_COLUMN_WIDTH - 2] + "…"
    pad = max(1, _NAME_COLUMN_WIDTH - len(name_segment))

    row = Text(no_wrap=True, overflow="ellipsis", style="dim")
    row.append(name_segment, style="bold")
    row.append(" " * pad)
    if sugg.tag:
        row.append(f"[{sugg.tag}] ", style="italic cyan")
    if sugg.description:
        # Collapse internal whitespace so multi-line descriptions render
        # cleanly on a single row (the OptionList truncates with "…").
        row.append(" ".join(sugg.description.split()))
    return row


def _fuzzy_match(name: str, partial: str) -> bool:
    """Lightweight fuzzy matcher: prefix wins, subsequence falls back.

    Matches the behavior of ``useTypeahead`` in
    ``typescript/src/components/PromptInput/useTypeahead.ts`` at a
    reduced fidelity (no scoring, no MRU). Prefix matches are always
    preferred so the most common ``/ex<Tab>`` workflow feels snappy.
    """

    if name.startswith(partial):
        return True
    i = 0
    for ch in name:
        if ch == partial[i]:
            i += 1
            if i == len(partial):
                return True
    return False


def _next_word(text: str, pos: int) -> int:
    """Return the cursor index of the next word start.

    ``pos`` is clamped to ``[0, len(text)]``. A word is any run of
    non-whitespace characters; we skip the current word first, then
    any whitespace.
    """

    n = len(text)
    pos = max(0, min(pos, n))
    # skip to end of current word
    while pos < n and not text[pos].isspace():
        pos += 1
    # skip intervening whitespace
    while pos < n and text[pos].isspace():
        pos += 1
    return pos


def _prev_word(text: str, pos: int) -> int:
    """Return the cursor index of the previous word start."""

    pos = max(0, min(pos, len(text)))
    # step back over whitespace
    while pos > 0 and text[pos - 1].isspace():
        pos -= 1
    # step back to start of word
    while pos > 0 and not text[pos - 1].isspace():
        pos -= 1
    return pos


def _current_slash_token(text_before_cursor: str) -> tuple[str | None, int]:
    """Return ``(token, start_idx)`` for the slash command under the cursor.

    Semantics locked in by :mod:`tests.tui.test_slash_token_parser`: a
    slash token is a ``/word`` that either starts at the beginning of
    the buffer or is preceded by whitespace. A slash followed by a
    space has already been "committed" and does not re-open the popup.
    """

    text = text_before_cursor
    if not text:
        return None, 0
    if text.startswith("/"):
        if " " in text:
            return None, 0
        return text, 0
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == "/":
            if i > 0 and not text[i - 1].isspace():
                return None, 0
            token = text[i:]
            if " " in token:
                return None, 0
            return token, i
        if ch.isspace():
            return None, 0
    return None, 0
