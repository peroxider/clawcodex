"""F-66 Trae IDE 集成 (Layer 2).

包含两个互补子特性:
  * P66-E — ``mcp_bridge``: MCP 反向桥，让 Trae IDE 通过 MCP 调用 clawcodex
  * P66-F — ``acp_cli_adapter``: 把字节开源的 trae-cli 包装为伪 ACP server

两者互为正反: P66-F 启动的 trae-cli 进程可挂载 P66-E 暴露的 MCP server,
形成双向闭环。详见 ``docs/feature_plan/06-ccb-benchmark/f-66-acp-protocol.md``。

完全在 Layer 2 解耦 — 删除本目录即可回滚，不影响 ``src/`` 与 ``clawcodex_ext/``。
"""

from __future__ import annotations

__all__ = ["mcp_bridge", "acp_cli_adapter"]
