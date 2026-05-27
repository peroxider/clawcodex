"""Bridge Manager — integrates bridge lifecycle with the TUI.

Mirrors useReplBridge.tsx from the TypeScript reference. Manages:
- Bridge initialization and teardown
- State synchronization between bridge and UI
- Message forwarding to/from bridge
- Permission callback handling
- Task state publishing
- Session resume with context restoration

The BridgeManager is owned by ClawCodexTUI and outlives the REPL screen.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .init_repl_bridge import InitBridgeOptions, ReplBridgeHandle

logger = logging.getLogger(__name__)

# Max consecutive init failures before auto-disable
MAX_CONSECUTIVE_INIT_FAILURES = 3
# How long after a failure before replBridgeEnabled is auto-cleared
BRIDGE_FAILURE_DISMISS_MS = 10_000
# Task state publish interval
TASK_STATE_POLL_MS = 5000
TASK_STATE_DEBOUNCE_MS = 50


@dataclass
class PermissionRequest:
    """A tool permission request pending user decision."""

    request_id: str
    tool_name: str
    input: dict[str, Any] | None
    tool_use_id: str
    description: str
    permission_suggestions: list[dict[str, Any]] | None = None
    blocked_path: str | None = None
    created_at: float = field(default_factory=time.time)


class BridgePermissionCallbacks:
    """Permission callbacks passed to AppState for the interactive permission handler.

    Mirrors the BridgePermissionCallbacks interface from useReplBridge.tsx.
    """

    def __init__(
        self,
        send_request: Callable[..., None],
        send_response: Callable[..., None],
        cancel_request: Callable[..., None],
        on_response: Callable[[str, Callable[[dict[str, Any]], None]], Callable[[], None]],
    ) -> None:
        self._send_request = send_request
        self._send_response = send_response
        self._cancel_request = cancel_request
        self._on_response = on_response
        self._pending_handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def send_request(
        self,
        request_id: str,
        tool_name: str,
        input: dict[str, Any] | None,
        tool_use_id: str,
        description: str,
        permission_suggestions: list[dict[str, Any]] | None = None,
        blocked_path: str | None = None,
    ) -> None:
        self._send_request(
            request_id,
            tool_name,
            input,
            tool_use_id,
            description,
            permission_suggestions,
            blocked_path,
        )

    def send_response(self, request_id: str, response: dict[str, Any]) -> None:
        self._send_response(request_id, response)

    def cancel_request(self, request_id: str) -> None:
        self._cancel_request(request_id)

    def on_response(
        self, request_id: str, handler: Callable[[dict[str, Any]], None]
    ) -> Callable[[], None]:
        self._pending_handlers[request_id] = handler
        return self._on_response(request_id, handler)


@dataclass
class BridgeManagerState:
    """Current state of the bridge manager."""

    enabled: bool = False
    connected: bool = False
    session_active: bool = False
    reconnecting: bool = False
    outbound_only: bool = False
    error: str | None = None
    session_id: str | None = None
    environment_id: str | None = None
    connect_url: str | None = None
    session_url: str | None = None
    permission_callbacks: BridgePermissionCallbacks | None = None


class BridgeManager:
    """Manages bridge lifecycle and integrates with the TUI.

    This class parallels useReplBridge.tsx from the TypeScript reference.
    It owns the bridge handle and coordinates:
    - Bridge initialization/teardown
    - State synchronization with AppState
    - Message forwarding to the bridge
    - Permission callback handling
    - Task state publishing for remote sessions
    """

    def __init__(
        self,
        app_state: Any,  # AppState from tui.state
        post_message: Callable[[Any], None],
        get_working_dir: Callable[[], str],
        get_machine_name: Callable[[], str],
        get_branch: Callable[[], str],
        get_git_repo_url: Callable[[], str | None],
        get_access_token: Callable[[], str | None],
        get_main_loop_model: Callable[[], str],
        set_main_loop_model_override: Callable[[str | None], None],
        is_bridge_enabled: Callable[[], bool] = lambda: True,
        is_outbound_only: Callable[[], bool] = lambda: False,
    ) -> None:
        self._app_state = app_state
        self._post_message = post_message
        self._get_working_dir = get_working_dir
        self._get_machine_name = get_machine_name
        self._get_branch = get_branch
        self._get_git_repo_url = get_git_repo_url
        self._get_access_token = get_access_token
        self._get_main_loop_model = get_main_loop_model
        self._set_main_loop_model_override = set_main_loop_model_override
        self._is_bridge_enabled = is_bridge_enabled
        self._is_outbound_only = is_outbound_only

        self._handle: Any | None = None  # ReplBridgeHandle
        self._teardown_promise: asyncio.Task[None] | None = None
        self._cancelled = False
        self._failure_timeout: asyncio.Task[None] | None = None
        self._consecutive_failures = 0

        # Message tracking for bridge forwarding
        self._last_written_index = 0
        self._flushed_uuids: set[str] = set()
        self._transcript_reset_pending = False
        self._pending_result_after_flush = False

        # Permission handlers
        self._pending_permission_handlers: dict[str, Callable[[dict[str, Any]], None]] = {}

        # Task state publishing
        self._task_state_poll_task: asyncio.Task[None] | None = None
        self._task_state_debounce_timer: asyncio.Task[None] | None = None
        self._last_published_snapshot_key: str | None = None

        # Bridge state
        self._state = BridgeManagerState()

    @property
    def state(self) -> BridgeManagerState:
        return self._state

    @property
    def handle(self) -> Any | None:
        return self._handle

    @property
    def is_connected(self) -> bool:
        return self._state.connected

    def is_enabled(self) -> bool:
        return self._is_bridge_enabled()

    def _fire_state_change(self, state: str, detail: str | None = None) -> None:
        """Handle bridge state changes and sync to AppState."""
        if self._cancelled:
            return

        outbound_only = self._is_outbound_only()

        if outbound_only:
            # Mirror mode: just sync connected state
            if state == 'failed':
                self._app_state.repl_bridge_connected = False
            elif state in ('ready', 'connected'):
                self._app_state.repl_bridge_connected = True
            return

        handle = self._handle

        if state == 'ready':
            self._app_state.repl_bridge_connected = True
            self._app_state.repl_bridge_session_active = False
            self._app_state.repl_bridge_reconnecting = False
            self._app_state.repl_bridge_error = None
            if handle:
                self._state.session_id = handle.bridge_session_id
                self._state.environment_id = handle.environment_id
                self._app_state.repl_bridge_session_id = handle.bridge_session_id
                self._app_state.repl_bridge_environment_id = handle.environment_id

        elif state == 'connected':
            self._app_state.repl_bridge_connected = True
            self._app_state.repl_bridge_session_active = True
            self._app_state.repl_bridge_reconnecting = False
            self._app_state.repl_bridge_error = None
            self._state.session_active = True

            # Post system message about connection
            self._post_message({
                'type': 'system',
                'subtype': 'info',
                'content': 'Remote Control 已连接',
            })

        elif state == 'reconnecting':
            self._app_state.repl_bridge_reconnecting = True
            self._app_state.repl_bridge_session_active = False

        elif state == 'failed':
            # Schedule auto-disable after timeout
            self._schedule_failure_dismiss()
            self._app_state.repl_bridge_error = detail
            self._app_state.repl_bridge_reconnecting = False
            self._app_state.repl_bridge_session_active = False
            self._app_state.repl_bridge_connected = False
            self._state.error = detail

            # Post failure message
            self._post_message({
                'type': 'system',
                'subtype': 'warning',
                'content': f'Remote Control failed to connect: {detail}',
            })

    def _schedule_failure_dismiss(self) -> None:
        """Schedule auto-disable of bridge after failure timeout."""
        if self._failure_timeout is not None:
            self._failure_timeout.cancel()

        async def dismiss_after_timeout() -> None:
            await asyncio.sleep(BRIDGE_FAILURE_DISMISS_MS / 1000)
            if not self._cancelled and self._app_state.repl_bridge_error:
                self._app_state.repl_bridge_enabled = False
                self._app_state.repl_bridge_error = None

        loop = asyncio.get_event_loop()
        self._failure_timeout = loop.create_task(dismiss_after_timeout())

    def _notify_bridge_failed(self, detail: str | None = None) -> None:
        """Post a bridge failure notification."""
        message = 'Remote Control failed'
        if detail:
            message += f' · {detail}'
        self._post_message({
            'type': 'system',
            'subtype': 'error',
            'content': message,
        })

    def _handle_permission_response(self, response: dict[str, Any]) -> None:
        """Handle incoming permission response from bridge."""
        request_id = response.get('response', {}).get('request_id') if isinstance(response, dict) else None
        if not request_id:
            logger.debug('[bridge:manager] No request_id in permission response')
            return

        handler = self._pending_permission_handlers.pop(request_id, None)
        if handler:
            handler(response)
        else:
            logger.debug(f'[bridge:manager] No handler for permission response request_id={request_id}')

    def _handle_interrupt(self) -> None:
        """Handle interrupt request from remote session."""
        # TODO: Wire to abort controller
        logger.debug('[bridge:manager] Remote interrupt received')

    def _handle_set_model(self, model: str | None) -> None:
        """Handle model change from remote session."""
        resolved = model if model != 'default' else None
        self._set_main_loop_model_override(resolved)
        self._app_state.main_loop_model_for_session = resolved

    def _handle_set_permission_mode(self, mode: str) -> dict[str, Any]:
        """Handle permission mode change request from remote session."""
        from src.permissions.modes import transition_permission_mode

        current = self._app_state.tool_permission_context.mode if hasattr(self._app_state, 'tool_permission_context') else 'default'

        # Policy checks would go here (mirrors TS isBypassPermissionsModeDisabled, isAutoModeGateEnabled)
        if mode == 'bypassPermissions':
            # Check if bypass is available
            if not getattr(self._app_state.tool_permission_context, 'is_bypass_permissions_mode_available', False):
                return {'ok': False, 'error': 'bypassPermissions not available'}

        # Apply the transition
        next_state = transition_permission_mode(current, mode, getattr(self._app_state, 'tool_permission_context', None))
        if hasattr(self._app_state, 'tool_permission_context'):
            self._app_state.tool_permission_context.mode = mode

        return {'ok': True}

    async def init_bridge(
        self,
        messages: list[Any],
        initial_name: str | None = None,
        perpetual: bool = False,
    ) -> bool:
        """Initialize the bridge connection.

        Mirrors useReplBridge's init effect.
        Returns True if bridge was successfully initialized.
        """
        if self._cancelled:
            return False

        if not self._is_bridge_enabled():
            return False

        if self._consecutive_failures >= MAX_CONSECUTIVE_INIT_FAILURES:
            logger.debug(
                f'[bridge:manager] {self._consecutive_failures} consecutive init failures, not retrying'
            )
            self._notify_bridge_failed('disabled after repeated failures · restart to retry')
            return False

        # Wait for any in-progress teardown
        if self._teardown_promise:
            logger.debug('[bridge:manager] Waiting for previous teardown to complete')
            await self._teardown_promise
            self._teardown_promise = None

        if self._cancelled:
            return False

        try:
            # Dynamic import to avoid circular deps
            from src.bridge.init_repl_bridge import init_repl_bridge, InitBridgeOptions

            opts = InitBridgeOptions(
                initial_name=initial_name,
                initial_messages=messages,
                perpetual=perpetual,
                outbound_only=self._is_outbound_only(),
            )

            self._state.outbound_only = self._is_outbound_only()

            # Build callbacks
            async def on_inbound_message(msg: dict[str, Any]) -> None:
                """Handle inbound message from remote session."""
                await self._handle_inbound_message(msg)

            def on_state_change(state: str, detail: str | None = None) -> None:
                self._fire_state_change(state, detail)

            def on_permission_response(response: dict[str, Any]) -> None:
                self._handle_permission_response(response)

            def on_interrupt() -> None:
                self._handle_interrupt()

            def on_set_model(model: str | None) -> None:
                self._handle_set_model(model)

            def on_set_permission_mode(mode: str) -> dict[str, Any]:
                return self._handle_set_permission_mode(mode)

            opts.on_inbound_message = on_inbound_message
            opts.on_state_change = on_state_change
            opts.on_permission_response = on_permission_response
            opts.on_interrupt = on_interrupt
            opts.on_set_model = on_set_model
            opts.on_set_permission_mode = on_set_permission_mode

            handle = await init_repl_bridge(
                opts,
                machine_name=self._get_machine_name(),
                branch=self._get_branch(),
                git_repo_url=self._get_git_repo_url(),
                working_dir=self._get_working_dir(),
            )

            if self._cancelled:
                if handle:
                    await handle.teardown()
                return False

            if handle is None:
                self._consecutive_failures += 1
                logger.debug(
                    f'[bridge:manager] Init returned null; consecutive failures: {self._consecutive_failures}'
                )
                self._schedule_failure_dismiss()
                return False

            # Success
            self._handle = handle
            self._consecutive_failures = 0
            self._state.enabled = True
            self._last_written_index = len(messages)

            # Build permission callbacks
            permission_callbacks = BridgePermissionCallbacks(
                send_request=lambda request_id, tool_name, input, tool_use_id, description, permission_suggestions=None, blocked_path=None: (
                    handle.send_control_request({
                        'type': 'control_request',
                        'request_id': request_id,
                        'request': {
                            'subtype': 'can_use_tool',
                            'tool_name': tool_name,
                            'input': input,
                            'tool_use_id': tool_use_id,
                            'description': description,
                            **({} if permission_suggestions is None else {'permission_suggestions': permission_suggestions}),
                            **({} if blocked_path is None else {'blocked_path': blocked_path}),
                        },
                    })
                ),
                send_response=lambda request_id, response: (
                    handle.send_control_response({
                        'type': 'control_response',
                        'response': {
                            'subtype': 'success',
                            'request_id': request_id,
                            'response': response,
                        },
                    })
                ),
                cancel_request=lambda request_id: (
                    handle.send_cancel_request(request_id)
                ),
                on_response=lambda request_id, handler: (
                    self._pending_permission_handlers.pop(request_id, None),
                    self._pending_permission_handlers.update({request_id: handler}),
                    lambda: self._pending_permission_handlers.pop(request_id, None)
                )[2] if True else None  # Simplified; just register
            )
            self._state.permission_callbacks = permission_callbacks
            self._app_state.repl_bridge_permission_callbacks = permission_callbacks

            # Post connection status message
            session_url = f"https://claude.ai/bridge/{handle.bridge_session_id}" if handle.bridge_session_id else None
            self._post_message({
                'type': 'bridge_status',
                'url': session_url,
            })

            logger.debug(f'[bridge:manager] Initialized, session={handle.bridge_session_id}')
            return True

        except Exception as err:
            if self._cancelled:
                return False

            self._consecutive_failures += 1
            error_msg = str(err)
            logger.error(f'[bridge:manager] Init failed: {error_msg}')
            self._notify_bridge_failed(error_msg)
            self._app_state.repl_bridge_error = error_msg
            self._schedule_failure_dismiss()

            if not self._state.outbound_only:
                self._post_message({
                    'type': 'system',
                    'subtype': 'warning',
                    'content': f'Remote Control failed to connect: {error_msg}',
                })

            return False

    async def _handle_inbound_message(self, msg: dict[str, Any]) -> None:
        """Handle an inbound message from the remote session.

        Inject the message into the REPL as a user prompt.
        """
        try:
            # Extract content from message
            msg_type = msg.get('type', '')
            content = None

            if msg_type == 'user_message':
                content = msg.get('content', {}).get('text', '') or msg.get('content', '')
            elif msg_type == 'sdk_message':
                # SDK message format
                content = msg.get('content', {}).get('text', '') if isinstance(msg.get('content'), dict) else msg.get('content', '')

            if not content:
                return

            uuid_val = msg.get('uuid')
            preview = content[:80] if isinstance(content, str) else f'[{len(content)} content blocks]'
            logger.debug(f'[bridge:manager] Injecting inbound message: {preview}' + (f' uuid={uuid_val}' if uuid_val else ''))

            # Enqueue the message for the REPL to process
            self._post_message({
                'type': 'bridge_inject',
                'content': content,
                'uuid': uuid_val,
                'bridge_origin': True,
            })

        except Exception as e:
            logger.error(f'[bridge:manager] handle_inbound_message failed: {e}')

    def write_messages(self, messages: list[Any]) -> None:
        """Write new messages to the bridge.

        Called when new user/assistant messages are added to the transcript.
        """
        if not self._handle:
            return

        # Collect messages since last write
        new_messages = []
        for i in range(self._last_written_index, len(messages)):
            msg = messages[i]
            if msg and msg.get('type') in ('user', 'assistant', 'system'):
                if msg.get('type') == 'system' and msg.get('subtype') != 'local_command':
                    continue
                new_messages.append(msg)

        if new_messages:
            try:
                self._handle.write_messages(new_messages)
                self._last_written_index = len(messages)
            except Exception as e:
                logger.error(f'[bridge:manager] write_messages failed: {e}')

    def send_result(self) -> None:
        """Send result acknowledgment to the bridge."""
        if self._handle:
            try:
                self._handle.send_result()
            except Exception as e:
                logger.error(f'[bridge:manager] send_result failed: {e}')

    def mark_transcript_reset(self) -> None:
        """Mark that transcript was reset (for compact, etc.)."""
        self._transcript_reset_pending = True
        self._pending_result_after_flush = False
        self._last_written_index = 0

    async def teardown(self) -> None:
        """Tear down the bridge connection.

        Called when the app exits or bridge is disabled.
        """
        if self._cancelled:
            return

        self._cancelled = True

        # Cancel task poll
        if self._task_state_poll_task:
            self._task_state_poll_task.cancel()
            self._task_state_poll_task = None

        if self._failure_timeout:
            self._failure_timeout.cancel()
            self._failure_timeout = None

        handle = self._handle
        self._handle = None

        if handle:
            try:
                await handle.teardown()
            except Exception as e:
                logger.debug(f'[bridge:manager] Teardown error: {e}')

        # Clear state
        self._state = BridgeManagerState()
        self._app_state.repl_bridge_connected = False
        self._app_state.repl_bridge_session_active = False
        self._app_state.repl_bridge_reconnecting = False
        self._app_state.repl_bridge_session_id = None
        self._app_state.repl_bridge_environment_id = None
        self._app_state.repl_bridge_error = None
        self._app_state.repl_bridge_permission_callbacks = None

    def start_task_state_publishing(self) -> None:
        """Start publishing task state to the bridge.

        Mirrors useReplBridge's task-state polling effect.
        """
        if self._state.outbound_only:
            return

        async def poll_task_state() -> None:
            while not self._cancelled:
                await asyncio.sleep(TASK_STATE_POLL_MS / 1000)
                if self._cancelled or not self._state.session_active:
                    continue
                await self._publish_task_state()

        loop = asyncio.get_event_loop()
        self._task_state_poll_task = loop.create_task(poll_task_state())

    async def _publish_task_state(self) -> None:
        """Publish current task state to the bridge."""
        if not self._handle or not self._state.session_active:
            return

        try:
            from src.utils.tasks import get_task_list_id, list_tasks, get_tasks_dir
            import os

            task_list_id = get_task_list_id()
            tasks_dir = get_tasks_dir(task_list_id)

            if not os.path.exists(tasks_dir):
                return

            tasks = await list_tasks(task_list_id)

            # Build snapshot key
            snapshot_key = f"{task_list_id}:{len(tasks)}"

            if snapshot_key == self._last_published_snapshot_key:
                return

            # Build task state message
            task_state = {
                'type': 'task_state',
                'task_list_id': task_list_id,
                'tasks': [
                    {
                        'id': t.get('id', ''),
                        'status': t.get('status', ''),
                        'description': t.get('description', ''),
                    }
                    for t in tasks
                ],
            }

            self._handle.write_sdk_messages([task_state])
            self._last_published_snapshot_key = snapshot_key

        except Exception as e:
            logger.error(f'[bridge:manager] Failed to publish task_state: {e}')

    def apply_resume_state(self, session: Any) -> None:
        """Apply session state after resume.

        Restores turn count, usage stats, and other UI state from the session.
        Mirrors processResumedConversation in the TS reference.
        """
        # Restore turn count from conversation
        if hasattr(session, 'conversation') and session.conversation:
            turn_count = sum(
                1 for msg in getattr(session.conversation, 'messages', [])
                if getattr(msg, 'role', None) == 'user'
            )
            self._app_state.turn_count = turn_count

        # Restore model info
        if hasattr(session, 'model') and session.model:
            self._app_state.main_loop_model_for_session = session.model

        # Restore usage stats
        if hasattr(session, 'cost'):
            cost = session.cost or {}
            self._app_state.usage = {
                'input_tokens': cost.get('input_tokens', 0),
                'output_tokens': cost.get('output_tokens', 0),
            }

    def reset_for_resume(self, messages: list[Any]) -> None:
        """Reset bridge state for resume.

        Called before init_bridge on resume to clear stale state.
        """
        self._last_written_index = len(messages)
        self._flushed_uuids.clear()
        self._transcript_reset_pending = False
        self._pending_result_after_flush = False
        self._last_published_snapshot_key = None