"""Facade — memdir/memdir.py has been moved to clawcodex_ext/memdir/memdir.

The F-88 memory-dir helpers (``DIR_EXISTS_GUIDANCE``, ``ENTRYPOINT_NAME``,
``EntrypointTruncation``, ``MAX_ENTRYPOINT_BYTES``,
``MAX_ENTRYPOINT_LINES``, ``build_memory_lines``,
``build_memory_prompt``, ``ensure_memory_dir_exists``,
``load_memory_prompt``, ``load_memory_prompts``,
``truncate_entrypoint_content``) now live in
:mod:`clawcodex_ext.memdir.memdir`. This module re-exports the
public surface so existing ``from src.memdir.memdir import ...``
callers keep working without modification.

Uses ``globals().update()`` to preserve access to all public names
regardless of ``__all__`` — the source module's ``__all__`` only
covers 11 of 25 public names.
"""

import clawcodex_ext.memdir.memdir as _mod

_globals = {k: v for k, v in vars(_mod).items() if not k.startswith('_')}
globals().update(_globals)
