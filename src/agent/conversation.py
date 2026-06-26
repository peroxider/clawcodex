"""Facade — agent/conversation.py has been moved to clawcodex_ext/agent/conversation.

The ``Conversation`` class and related message-construction helpers now live in
:mod:`clawcodex_ext.agent.conversation`. This module re-exports the public
surface so existing ``from src.agent.conversation import ...`` callers keep
working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module does not define ``__all__``.
"""

import clawcodex_ext.agent.conversation as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
