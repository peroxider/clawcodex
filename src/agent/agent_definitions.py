"""Facade — agent/agent_definitions.py moved to clawcodex_ext/agent/.

The full agent definition machinery (``AgentDefinition``,
``AgentSource``, ``BuiltInAgentDefinition``, ``EXPLORE_AGENT``,
``FORK_AGENT``, ``GENERAL_PURPOSE_AGENT``, ``PLAN_AGENT``,
``find_agent_by_type``, ``get_built_in_agents``, ``is_built_in_agent``)
now lives in :mod:`clawcodex_ext.agent.agent_definitions`. This module
re-exports it verbatim so existing ``from src.agent.agent_definitions
import ...`` callers keep working.
"""

from clawcodex_ext.agent.agent_definitions import *  # noqa: F401,F403
