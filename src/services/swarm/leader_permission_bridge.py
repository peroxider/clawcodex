"""Facade — services/swarm/leader_permission_bridge.py has been moved to clawcodex_ext.

The full implementation now lives in
:mod:`clawcodex_ext.services.swarm.leader_permission_bridge`. This module
re-exports the public surface so existing
``from src.services.swarm.leader_permission_bridge import ...`` callers
keep working without modification.
"""

from clawcodex_ext.services.swarm.leader_permission_bridge import (  # noqa: F401
    PermissionRequest,
    _reset_callbacks,
    create_permission_request,
    register_permission_callback,
    unregister_permission_callback,
    get_pending_request_ids,
    deliver_permission_decision,
    send_permission_request_via_mailbox,
)

__all__ = [
    'PermissionRequest',
    '_reset_callbacks',
    'create_permission_request',
    'register_permission_callback',
    'unregister_permission_callback',
    'get_pending_request_ids',
    'deliver_permission_decision',
    'send_permission_request_via_mailbox',
]
