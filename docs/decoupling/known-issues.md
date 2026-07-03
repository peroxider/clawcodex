# P3 整改已知遗留问题

> 状态: 🔄 进行中（持续更新）
> 章节: docs/decoupling/known-issues.md
> 最后更新: 2026-06-29

## §1 P3-skip 公开 API + 测试 mock 兼容

### 1.1 背景

[facade-patterns.md §4.1](../decoupling/facade-patterns.md#41-模式-a-模式-a-的-monkey-patch-失效陷阱) 描述了模式 A 的 monkey-patch 失效陷阱：当 Layer 2 用 `from clawcodex_ext.X import Y` 而测试用 `unittest.mock.patch("src.X.Y", mock_value)` 替换源模块属性时，facade 仍指向旧对象。

### 1.2 P3-skip 案例

`extensions/remote_api/runner.py:195-196`：

```python
# `src.outputStyles` + `src.query.agent_loop_compat` are public
# upstream APIs exercised by tests/remote_api/test_remote_api.py
# via ``unittest.mock.patch("src.…")`` (see :1006, :1013).
# Layer 2 may import public ``src.*`` APIs directly per CLAUDE.md
# (the prohibition is on ``src._internals``).
from src.outputStyles import resolve_output_style
from src.query.agent_loop_compat import (
    build_effective_system_prompt,
    run_query_as_agent_loop,
)
```

**为什么 P3-skip**:
1. `src.outputStyles` → `clawcodex_ext.outputStyles` 是模式 A facade，test 在 `tests/remote_api/test_remote_api.py:1006` patch `src.outputStyles.resolve_output_style` 不再命中 facade 缓存。
2. `src.query.agent_loop_compat` → `clawcodex_ext.query.agent_loop_compat` 是 Layer 1 **真实现**（非 facade），与 src 同名函数为**不同对象**。test 在 `tests/remote_api/test_remote_api.py:1013, 1070, 1120` patch `src.query.agent_loop_compat.run_query_as_agent_loop` 不影响 clawcodex_ext 实现。
3. 两处都是 Layer 2 对 `src.*` **公开 API**（非 `_internals`）的直接 import — CLAUDE.md §黄金法则 3 仅禁止 `_internals` 级别 import，公开 API 允许。

### 1.3 当前处理

**保留** `from src.*` 形式 + 在 P3-step5 commit message 中标注 P3-skip 原因 + 在本目录记录。后续若满足以下任一条件可重新评估迁移：
- 上游把 `src.query.agent_loop_compat` 收编为 Layer 1 兼容 facade
- 测试改为 patch `clawcodex_ext.*`（P3 规则不动测试，因此不会主动触发）

## §2 P3-out 候选（后续解耦工作）

### 2.1 P3-out-1: 修复 submodule shadowing 风险

**状态**: ✅ 已完成（2026-06-29）

**问题**: `clawcodex_ext/tool_system/__init__.py` 用 `from .build_tool import build_tool` 重新导出**函数 `build_tool`**，覆盖了子模块 `clawcodex_ext.tool_system.build_tool` 名。当调用方用 `import clawcodex_ext.tool_system.build_tool as M` 形式时，`M` 实际是函数而非子模块对象。

**修复方案**: 选项 A — 从 `__init__.py` 的 `from .build_tool import (...)` 块移除 `build_tool,` 项，并从 `__all__` 中移除 `"build_tool"`。docstring 说明 P3-out-1 修复理由 + 推荐路径 `from clawcodex_ext.tool_system.build_tool import build_tool`。

**完成工作**:
1. ✅ `clawcodex_ext/tool_system/__init__.py` 移除 `build_tool` 重新导出 + 更新 docstring
2. ✅ 验证 `import clawcodex_ext.tool_system.build_tool as bt_mod` 解析为 module object（`bt_mod.build_tool` 是函数）
3. ✅ 验证 `from clawcodex_ext.tool_system.build_tool import Tool, Tools, build_tool` 仍工作
4. ✅ 验证 `from clawcodex_ext.tool_system import Tool, ...` 仍工作（其他 19 个符号未受影响）

**验证基线**:
- py_compile + ruff 全通过
- 等价性探针：移除 `build_tool` re-export 不影响其他 19 个公开符号
- 18 个 pre-existing test failures 跨 HEAD/P3-out-1 两端**完全一致**（5 provider registration + 13 tool_system_tools + 1 parse_wrapper_stdout collection error），与本次改动**无关**
- 全量稳定性门禁：332/332 通过
- orchestrator 单元测试：1078 passed, 2 skipped

**调用方影响**: 暂无 P3 范围调用方需要 `from clawcodex_ext.tool_system import build_tool` 形式 — 全部走 `from clawcodex_ext.tool_system.build_tool import build_tool`。

### 2.2 P3-out-2: 完整迁移遗留 facade

**状态**: ✅ 已完成（2026-06-29）

**问题**: P3-step4 创建的 `clawcodex_ext/bridge/repl_bridge_transport.py` 是 2 行 `from X import *` 薄 facade，源是 `src.bridge.repl_bridge_transport`（392 行真实现：`ReplBridgeTransport` Protocol、`V2TransportOptions`、v1/v2 transport 类与工厂）。

**完成工作**:
1. ✅ `src.bridge.repl_bridge_transport` 392 行完整复制到 `clawcodex_ext/bridge/repl_bridge_transport.py`
2. ✅ 调整 import 链：3 个 `src.transports.*` 改为直接 Layer 1 真实现
   - `src.transports.ccr_client` → `clawcodex_ext.transports.ccr_client`
   - `src.transports.hybrid_transport` → `extensions.ports.transports.hybrid_v1`（Layer 2 真实现，无 Layer 1 facade）
   - `src.transports.sse_transport` → `clawcodex_ext.transports.sse_transport`
3. ✅ `src.bridge.repl_bridge_transport` 改为 5 行 thin forwarding seam（`from clawcodex_ext.bridge.repl_bridge_transport import *`）

**额外修复**（P3-out-2 实施时触发的 latent 循环导入问题）:

P3-step5 创建的 `clawcodex_ext/transports/serial_batch_event_uploader.py` 和 `clawcodex_ext/transports/websocket_transport.py` 走 `src.transports.*` 路径，会触发 `src.transports.__init__.py` 加载，间接循环到 `extensions.ports.transports.hybrid_v1`。改为直接走 `extensions.ports.transports.serial_uploader` / `extensions.ports.transports.websocket_v1`，跳过 `src.transports` package `__init__` 的 side effects。

**验证基线**:
- py_compile + ruff 全通过
- 等价性探针：`ReplBridgeTransport`、`V2TransportOptions`、`create_v1_repl_transport`、`create_v2_repl_transport` 4 个公开符号在 `src` 和 `clawcodex_ext` 解析为同一对象（`is` 关系 True）
- `tests/bridge/` 612 passed (2 deselected pre-existing)
- `tests/stability_gate/` 332/332 通过
- `tests/orchestrator/` 1078 passed, 2 skipped

**遗留**: `src.bridge.session_runner`（已在 P3-step3 改造但仍作为 re-export）未在 P3-out-2 处理，留待后续 P-其他批次。

### 2.3 P3-out-3: P3 文档化

**问题**: P3 整改 6 步全部 commit 后无正式文档记录，commit message 是唯一历史。

**P3 处理**: 创建 `docs/decoupling/` 目录 + 3 份文档：
- `README.md` — 整改总览 + step 累计 + 验证基线
- `p3-layer2-direct-imports.md` — 各 step 详情 + 改动文件清单
- `facade-patterns.md` — 三类 facade 模式 + 选型决策树
- `known-issues.md` — 本文件

**预计工作量**: 半天。状态: ✅ 已完成（本 step）。

### 2.4 P-其他: P4 类别方向

P3 解决 Layer 2 对 Layer 0 直接依赖。下一步可考虑：
- P4-A: 修复 Layer 1 内部对 `src._internals` 的使用模式（如果有）
- P4-B: 强化 `extensions/capabilities/` Protocol 契约层，让 Layer 2 内部互相调用走 Protocol 而非具体类
- P4-C: 收编上游未明确的 `extensions/ports/transports/hybrid_v1.py` 等"准 Layer 2"模块

## §3 Line ending 漂移

### 3.1 背景

P3-step6 编辑 `extensions/sop_converter/bundle_skills.py` 和 `sop_exploration_guard.py` 时遇到工作区 CRLF、HEAD 是 LF 的 line ending 漂移 — 若直接 staged diff，整文件被标记为改动（430 / 1226 行），污染 commit diff。

### 3.2 当前处理

提交前用 Python 脚本把工作区文件转回 LF：

```python
for p in ['extensions/sop_converter/bundle_skills.py', 'extensions/sop_converter/sop_exploration_guard.py']:
    with open(p, 'rb') as f:
        data = f.read()
    data_lf = data.replace(b'\r\n', b'\n')
    with open(p, 'wb') as f:
        f.write(data_lf)
```

### 3.3 根因

这两个文件是历史上其他 agent / 编辑器（如 Windows 编辑器、某些 git 配置 `core.autocrlf=true`）引入 CRLF，未规范化。

### 3.4 后续

**未计划批量修复** — 仅 P3 step 涉及的文件在 commit 前归一化。其他工作区 CRLF 文件保持原样，避免无关改动。

## §4 测试 mock 兼容性总览

P3 整改中**未**触发的测试失败案例（前 2 步中遇到、已确认与本次改动无关）：

| 测试 | 状态 | 根因 |
|------|------|------|
| `tests/bridge/test_debug_utils.py::test_log_bridge_skip_emits_info_log` | ✅ 已修（2026-06-30） | logger name `src.bridge.debug_utils` 不匹配实际 `clawcodex_ext.bridge.debug_utils`（src facade 用 `sys.modules[__name__] = _module` 模式） |
| `tests/bridge/test_messaging_router.py::TestNormalizeControlControlMessageKeys::test_unknown_camel_case_passes_through_with_debug_log` | ✅ 已修（2026-06-30） | 同上，logger name 改为 `clawcodex_ext.bridge.messaging` |

### 4.1 2026-06-30 P3 遗留问题批量修复（commit `a20ffc7c`）

P3 整改完成后识别出 21 个 pre-existing test failures（与 P3 改动无关，但 F-decouple 上游迁移未配套更新测试）。本次按根因分组修复：

| 测试文件 | 修复数 | 根因 |
|----------|-------|------|
| `tests/tool/test_tool_system_tools.py` | 13 | F-decouple 把 `src/tool_system/tools/tasks_v2.py` 改为 3 行 facade 不再导出 `_format_task_*`（私有 helper）；5 个 web_search 测试 mock 已被 Tavily 替换的 `_ddg_package_search` |
| `tests/clawcodex_ext/providers/test_f99_provider_registration.py` | 5 | F-99 fix 假设 `import clawcodex_ext.providers` 触发 register side-effect，但 P3-cold-start 优化改为 deferred init |
| `tests/clawcodex_ext/agent/tool_authoring/test_parse_wrapper_stdout.py` | 2 | 测试 typo: `parse_pos_wrapper_stdout` → `parse_sop_wrapper_stdout` |
| `tests/bridge/test_debug_utils.py` + `test_messaging_router.py` | 1 + 1 | caplog `logger=` 参数不匹配实际 logger name |

**修复方案**：
- tasks_v2 测试改用 `clawcodex_ext.tool_system.tools.tasks_v2` 直接 import
- web_search 测试改用 `_tavily_search` mock 路径（DDG→Tavily 迁移在 commit `a1e1faf4`）
- provider 测试改用 `_init_provider_extensions()` 显式调用（模拟 `ensure_eager_extensions_installed()` 生产路径）
- 测试 typo 修正
- logger name 同步到 `clawcodex_ext.bridge.*`

**验证基线**：
- 21 个修复点全部 PASS
- stability_gate 332/332 通过
- orchestrator 单元测试 1078 passed, 2 skipped

### 4.2 P3-skip（永久保留）

`extensions/remote_api/runner.py:195-196` 仍保留 `from src.outputStyles` / `from src.query.agent_loop_compat`（函数局部 from-imports）。

**根因（最终验证）**：runner 用**函数局部** `from src.X import Y`（非模块顶层 import），函数在 `with patch("src.X.Y")` 上下文中被调用 — Python 此时捕获的本地绑定是 mock 而非原函数。实验验证：

- 用 `clawcodex_ext.*` 路径的 from-import 在 patch `src.*` 上下文中：本地绑定**保持原函数**（mock 不命中）→ 会破坏现有 4 个测试的 mock 契约
- 用 `src.*` 路径的 from-import 在 patch `src.*` 上下文中：本地绑定**变成 mock**（命中）→ 测试按设计工作

**解决方案候选**：
- 选项 A：把 runner 的 from-import 改为 `import src.X` + `src.X.Y(...)` qualified access — 改动 + 测试已锁定 src.* 路径
- 选项 B：把测试 mock 路径改为 `clawcodex_ext.X.Y`（**不可行**：见实验，claude_ext.* 路径下 from-import 不命中）
- 选项 C：保持现状 + 文档化

**结论**：选项 C。修改 P3-skip 会破坏现有测试，且无生产代码改进（CLAUDE.md 允许公开 `src.*` API 在 Layer 2 直接 import）。

### 4.3 累计回归统计

- P3 6 步累计测试回归数：0（提交前每次都跑相关测试套件）
- 2026-06-30 批量修复：21 个 pre-existing failures → 0 个剩余
- P3-skip：1 处保留（永久有效）
