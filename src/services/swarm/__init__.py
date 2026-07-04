"""Facade — services/swarm/ re-exports from clawcodex_ext.services.swarm.

Canonical implementation lives at ``clawcodex_ext/services/swarm/``.
This module is kept so existing imports of
``from src.services.swarm import ...`` continue to work.
"""

from clawcodex_ext.services.swarm import *  # noqa: F401,F403
