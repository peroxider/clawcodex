"""Facade — agent/constants.py moved to clawcodex_ext/agent/.

The agent constants (``AGENT_TOOL_NAME``, ``ALL_AGENT_DISALLOWED_TOOLS``,
``ASYNC_AGENT_ALLOWED_TOOLS``, ``CUSTOM_AGENT_DISALLOWED_TOOLS``,
``DEFAULT_AGENT_PROMPT``, ``FORK_SUBAGENT_TYPE``, etc.) now live in
:mod:`clawcodex_ext.agent.constants`. This module re-exports them
verbatim so existing ``from src.agent.constants import ...`` callers
keep working.
"""

from clawcodex_ext.agent.constants import *  # noqa: F401,F403
