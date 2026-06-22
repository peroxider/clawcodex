"""Swarm/Teammates subsystem.

Provides teammate spawning, permission synchronization, mailbox
transport, and team coordination. Mirrors the TypeScript ``swarm/``
directory.

This package is the canonical implementation. ``src/services/swarm/``
is a thin facade re-exporting everything from here.
"""

from __future__ import annotations

from .agent_name_registry import AgentNameAlreadyClaimedError, AgentNameRegistry
from .helpers import format_team_summary, get_active_teammates
from .leader_permission_bridge import (
    PermissionRequest,
    create_permission_request,
    deliver_permission_decision,
    get_pending_request_ids,
    register_permission_callback,
    send_permission_request_via_mailbox,
    unregister_permission_callback,
)
from .mailbox import (
    TeammateMessage,
    create_plan_approval_response_message,
    create_shutdown_approved_message,
    create_shutdown_rejected_message,
    create_shutdown_request_message,
    get_inbox_path,
    get_mailboxes_root,
    make_iso_timestamp,
    read_mailbox,
    write_to_mailbox,
)
from .mailbox_poller import (
    start_mailbox_poller,
    stop_mailbox_poller,
    sweep_mailboxes,
)
from .permissions import PermissionDecision, SwarmPermissionSync
from .team_file import (
    BackendType,
    TeamFile,
    TeamMember,
    add_member,
    find_member_by_name,
    get_team_file_path,
    read_team_file,
    remove_member,
    write_team_file,
)
from .team_membership import is_team_lead
from .teammate import (
    Teammate,
    TeammateConfig,
    TeammateManager,
    TeammateStatus,
)

__all__ = [
    # teammate
    "Teammate",
    "TeammateConfig",
    "TeammateManager",
    "TeammateStatus",
    # helpers
    "format_team_summary",
    "get_active_teammates",
    # permissions
    "PermissionDecision",
    "SwarmPermissionSync",
    # mailbox
    "TeammateMessage",
    "create_plan_approval_response_message",
    "create_shutdown_approved_message",
    "create_shutdown_rejected_message",
    "create_shutdown_request_message",
    "get_inbox_path",
    "get_mailboxes_root",
    "make_iso_timestamp",
    "read_mailbox",
    "write_to_mailbox",
    # mailbox poller
    "start_mailbox_poller",
    "stop_mailbox_poller",
    "sweep_mailboxes",
    # leader permission bridge
    "PermissionRequest",
    "create_permission_request",
    "deliver_permission_decision",
    "get_pending_request_ids",
    "register_permission_callback",
    "send_permission_request_via_mailbox",
    "unregister_permission_callback",
    # team file
    "BackendType",
    "TeamFile",
    "TeamMember",
    "add_member",
    "find_member_by_name",
    "get_team_file_path",
    "read_team_file",
    "remove_member",
    "write_team_file",
    # team membership
    "is_team_lead",
    # agent name registry
    "AgentNameAlreadyClaimedError",
    "AgentNameRegistry",
]
