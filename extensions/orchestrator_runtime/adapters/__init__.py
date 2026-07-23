"""Orchestrator Runtime — 适配层（Phase 2）。

本目录提供 ``clawcodex_compat`` 透明转发层，让 ``extensions.orchestrator/``
内部 import 从 ``clawcodex_ext.*`` 切换到本模块而行为不变。Phase 3 主动
迁移后，本层将被删除。
"""

from __future__ import annotations

__all__: list[str] = []
