"""Re-export facade — leader_permission_bridge canonical impl in src/.

This is the documented ClawCodex exception to the
``clawcodex_ext/ → 禁止导入 src/`` rule.

The module-level ``_callbacks`` dict (and its RLock) is **stateful
singletons** — duplicating the implementation in clawcodex_ext/
would create a second, independent registry. Tests / production
callers that register a callback via one path would not see it
fire from the other path.

Rather than duplicate the registry and risk silent breakage, the
clawcodex_ext/ module is a thin re-export of the canonical
implementation in ``src/services/swarm/leader_permission_bridge.py``.
The src/ implementation in turn imports ``mailbox`` via that
module's facade (which re-exports from clawcodex_ext/), so the
import chain terminates cleanly.
"""

from src.services.swarm.leader_permission_bridge import *  # noqa: F401,F403
