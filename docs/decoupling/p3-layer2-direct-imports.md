# P3 整改：Layer 2 清洗 `from src.*` 直接导入

> 状态: ✅ 已完成（2026-06-29）
> 章节: docs/decoupling/p3-layer2-direct-imports.md
> 最后更新: 2026-06-29

## §1 背景

`extensions/`（Layer 2）作为三方扩展层，根据 [CLAUDE.md §黄金法则 3](../CLAUDE.md#黄金法则golden-rules) 允许 `import src.` 与 `import clawcodex_ext.`。但实践中大量 Layer 2 文件直接 `from src.* import ...` 内部模块（包括上游核心如 `src.config`、`src.bootstrap.state`、`src.query.agent_loop_compat` 等），导致：

1. **上游 merge 冲突面扩大** — `extensions/` 直接依赖 `src/` 具体模块名，上游重构时频繁撞车
2. **层间契约弱化** — Layer 2 应该通过 `extensions/capabilities/` 中的 Protocol 与 Layer 1 通信，而不是直接拿 Layer 0 的具体类
3. **测试 mock 路径脆弱** — 跨边界 mock 时绕不开 `src.*` 实现细节（参见 [P3-skip mock 兼容](known-issues.md#p3-skip-公开-api--测试-mock-兼容)）

P3 整改目标：把 Layer 2 对 `src.*` 的直接依赖批量迁移到 `clawcodex_ext.*`（Layer 1）的 facade / 真实实现，让静态层间依赖更清晰。

## §2 P3 累计 6 步详情

### P3-step1 (commit `eadc9d6a`)

**范围**: `extensions/capabilities/` 自身清洗 `src.*` 导入

`extensions/capabilities/` 是 Layer 2 内部 Protocol 契约定义目录，本身应该完全无 `src.*` 依赖。本步清洗 6 个内部 import 让 capabilities 子树自给自足。

**改动文件**: `extensions/capabilities/` 内多个 Protocol stub 文件

---

### P3-step2 (commit `2258e310`)

**范围**: `orchestrator/git_sync` 清洗 `src.utils.git` 导入

`extensions/orchestrator/git_sync.py` 直接 import `src.utils.git` 拿 `FileStatus` 与 `get_file_status`。本步迁移到 `clawcodex_ext.utils.git`（Layer 1 中已有同符号 facade/实现），git_sync 的 `_status_snapshot` 行为不变（`extensions/orchestrator/git_sync.py:312` 排序按 `s.path` 不按 `str(s)` 的 Option B fix 保留）。

**改动文件**:
- `extensions/orchestrator/git_sync.py` — 1 import

---

### P3-step3 (commit `390bc86b`)

**范围**: 7 个 Layer 2 文件，每个 1 个 `from src.*` 导入迁移

7 个独立小修改，每个 import 都有对应 `clawcodex_ext.*` facade/真实现。

**改动文件**:
- `extensions/orchestrator/orchestrator.py` — `src.tool_system.context.ToolContext` → `clawcodex_ext.tool_system.context.ToolContext`
- `extensions/tool_system_ext/registration.py` — `src.tool_system.build_tool.Tool` → `clawcodex_ext.tool_system.build_tool.Tool`
- `extensions/sop_converter/agent_builder.py` — `src.skills.model.Skill` → `clawcodex_ext.skills.model.Skill`
- `extensions/skills_ext/bundled/__init__.py` — `src.skills.bundled_skills.BundledSkillDefinition/register_bundled_skill` → `clawcodex_ext.skills.bundled_skills.*`
- `extensions/agent/session_persist.py` — `src.services.session_storage.SessionStorage` → `clawcodex_ext.services.session_storage.SessionStorage`
- `extensions/ports/transports/websocket_v1.py` — `src.utils.env.is_env_truthy` → `clawcodex_ext.utils.env.is_env_truthy`
- `extensions/skills_ext/registry_ext.py` — `importlib.import_module("src.skills.loader")` → `importlib.import_module("clawcodex_ext.skills.loader")`（同时同步 docstring）

**已知 latent 风险（不影响本 step）**: `clawcodex_ext/tool_system/__init__.py` 中 `from .build_tool import build_tool` 重新导出覆盖了子模块名（`build_tool` 函数 vs `build_tool` 子模块冲突）。`from X.Y.Z import W` 模式不受影响，但 `import clawcodex_ext.tool_system.build_tool as X` 形式会拿到函数而非子模块。详见 [known-issues.md §P3-out-1](known-issues.md#p3-out-1-修复-submodule-shadowing-风险)。

---

### P3-step4 (commit `b4ed35d3`)

**范围**: `extensions/ports/bridge/` 4 文件 28 个 `src.*` 导入 + 1 新 facade

本步首次大量集中处理 bridge 子目录 4 个 Layer 2 文件。

**改动文件**:
- `extensions/ports/bridge/session_runner.py` — 2 imports
  - `src.bridge.debug_utils` → `clawcodex_ext.bridge.debug_utils`
  - `src.bridge.types` → `clawcodex_ext.bridge.types`
- `extensions/ports/bridge/bridge_main.py` — 6 module-level + 1 function-local = 7 imports
  - 5 个 `src.bridge.*` → `clawcodex_ext.bridge.*`（bridge_api, poll_config_defaults, types, work_secret, worktree）
  - 1 个 `src.bridge.session_runner` → **同包 sibling import** `extensions.ports.bridge.session_runner`（session_runner 自身是 P3-step3 改造的 Layer 2 文件）
  - 1 个 function-local `src.bridge.session_id_compat` → `clawcodex_ext.bridge.session_id_compat`
- `extensions/ports/bridge/remote_bridge_core.py` — 11 module-level imports
  - 9 个 `src.bridge.*` → `clawcodex_ext.bridge.*`（bounded_uuid_set, code_session_api, env_less_bridge_config, flush_gate, jwt_utils, messaging, messaging_handlers, session_id_compat, work_secret）
  - 1 个 `src.bridge.repl_bridge_transport` → `clawcodex_ext.bridge.repl_bridge_transport`（**用新 facade**，见下）
  - 1 个 `src.utils.message_mappers` → `clawcodex_ext.utils.message_mappers`
- `extensions/ports/bridge/repl_bridge.py` — 8 module-level imports
  - 7 个 `src.bridge.*` → `clawcodex_ext.bridge.*`（bridge_api, bridge_pointer, jwt_utils, poll_config_defaults, session_id_compat, types, work_secret）
  - 1 个 `src.bridge.session_runner` → **同包 sibling import**（同 bridge_main 处理）

**新 facade**:
- `clawcodex_ext/bridge/repl_bridge_transport.py` (2 行 `from src.bridge.repl_bridge_transport import *`)

`src.bridge.repl_bridge_transport` 是 400+ 行真实现（`ReplBridgeTransport` Protocol、`V2TransportOptions`、v1/v2 transport 类与工厂），完整迁移到 `clawcodex_ext/` 留待 P3-out-2。本步仅创建薄 facade 让 Layer 2 不再直接 import Layer 0。

---

### P3-step5 (commit `d863cfa3`)

**范围**: `remote_api/runner.py` + `hybrid_v1.py` 共 12 个 `src.*` 导入 + 7 新 facade

本步新增 7 个薄 facade（`from X import *` 模式），是 P3 整改中 facade 创建最密集的批次。

**改动文件**:
- `extensions/remote_api/runner.py` — 9 imports 中 7 个改 facade + 2 个 P3-skip
  - 7 个 `src.*` → `clawcodex_ext.*` facade（bootstrap.state, config, permissions.types, providers, tool_system.context, tool_system.defaults, utils.abort_controller）
  - 2 个保留 `from src.*`（P3-skip）: `src.outputStyles.resolve_output_style` + `src.query.agent_loop_compat.run_query_as_agent_loop`（公开 API + 测试 mock 兼容，详见 [known-issues.md §P3-skip](known-issues.md#p3-skip-公开-api--测试-mock-兼容)）
- `extensions/ports/transports/hybrid_v1.py` — 3 imports 全部改 facade
  - `src.transports.serial_batch_event_uploader` → `clawcodex_ext.transports.serial_batch_event_uploader`
  - `src.transports.websocket_transport` → `clawcodex_ext.transports.websocket_transport`
  - `src.utils.session_ingress_auth` → `clawcodex_ext.utils.session_ingress_auth`

**新 facade（7 个，每文件 2-3 行）**:
- `clawcodex_ext/bootstrap/__init__.py` (空 package marker)
- `clawcodex_ext/bootstrap/state.py` (→ `src.bootstrap.state` 1228 行真实现)
- `clawcodex_ext/outputStyles.py` (→ `src.outputStyles` package)
- `clawcodex_ext/config.py` (→ `src.config` 570 行真实现)
- `clawcodex_ext/transports/serial_batch_event_uploader.py` (→ `src.transports.serial_batch_event_uploader` 16 行)
- `clawcodex_ext/transports/websocket_transport.py` (→ `src.transports.websocket_transport` 16 行)
- `clawcodex_ext/utils/session_ingress_auth.py` (→ `src.utils.session_ingress_auth` 114 行)

---

### P3-step6 (commit `8cc3b9a8`)

**范围**: 7 个 Layer 2 文件 12 个 `from src.*` 导入

P3 整改最终步。把剩余 7 个 Layer 2 文件中的 12 个 import 全部迁移到 `clawcodex_ext.*`（对应已有 facade/真实现）。

**改动文件**:
- `extensions/orchestrator/agent_runner.py` — 4 imports
  - `src.agent.conversation` → `clawcodex_ext.agent.conversation`
  - `src.services.session_storage` → `clawcodex_ext.services.session_storage`（×2）
  - `src.bootstrap.state` → `clawcodex_ext.bootstrap.state`（P3-step5 新建 facade）
- `extensions/tool_system_ext/registry_ext.py` — 2 imports
  - `src.tool_system.build_tool` → `clawcodex_ext.tool_system.build_tool`
  - `src.tool_system.registry` → `clawcodex_ext.tool_system.registry`
- `extensions/sop_converter/skill_grouper.py` — 2 imports
  - `src.providers.base` → `clawcodex_ext.providers.base`（×2）
- `extensions/sop_converter/sop_exploration_guard.py` — 1 import
  - `src.agent.load_agents_dir` → `clawcodex_ext.agent.load_agents_dir`
- `extensions/sop_converter/bundle_skills.py` — 1 import
  - `src.skills.frontmatter` → `clawcodex_ext.skills.frontmatter`
- `extensions/orchestrator/progress_sink.py` — 1 import
  - `src.tool_system.context` → `clawcodex_ext.tool_system.context`
- `extensions/orchestrator/progress_reporter.py` — 1 import
  - `src.tool_system.context` → `clawcodex_ext.tool_system.context`

**注意**: `bundle_skills.py` 和 `sop_exploration_guard.py` 工作区原为 CRLF line ending，HEAD 是 LF。已规范化为 LF 避免污染 diff（参见 [known-issues.md §line-ending-漂移](known-issues.md#line-ending-漂移)）。

## §3 验证基线

每次 P3 step 提交前的标准验证流程：

```bash
# 1. 静态编译 + lint
python3 -m py_compile <修改文件清单>
python3 -m ruff check <修改文件清单>

# 2. 残留检查
grep -nE "^from src\.|^import src\." <修改文件清单>
# 预期：无输出（或仅 P3-skip 标注行）

# 3. 针对性单测（按 step 不同）
python3 -m pytest <相关测试目录> -q --tb=short

# 4. 稳定性门禁（vibe coding 模式必跑）
python3 -m pytest tests/stability_gate/ -q --tb=short

# 5. orchestrator 单元套件（影响 orchestrator/ 时必跑）
python3 -m pytest tests/orchestrator/ --ignore=tests/orchestrator/manual_e2e_f38.py -q
```

**P3 全量 6 步累计验证基线**：
- 每次 step: py_compile + ruff + 针对性测试 全部通过
- 每次 step: stability gate 332/332 通过
- 影响 orchestrator/ 的 step: orchestrator 1078 passed, 2 skipped
- 6 个 step 零测试回归

## §4 关联 commit 速查

```bash
# 列出所有 P3 step commits
git log --oneline | grep -E "p3-step|capabilities"
# 输出（按时间倒序）:
# 8cc3b9a8 refactor(p3-step6): 清洗 7 个 Layer 2 文件的 src.* 导入
# d863cfa3 refactor(p3-step5): 清洗 remote_api/runner.py + hybrid_v1.py 的 src.* 导入
# b4ed35d3 refactor(p3-step4): 清洗 extensions/ports/bridge/ 的 src.* 导入
# 390bc86b refactor(p3-step3): 清洗 7 个 Layer 2 文件的 src.* 导入
# 2258e310 refactor(orchestrator): 清洗 src.utils.git 导入 (P3-step2)
# eadc9d6a refactor(capabilities): 清洗 capabilities/ 自身 src.* 导入 (P3-step1)
```

## §5 后续

详见 [README.md §解耦类工作的下一阶段](../README.md#解耦类工作的下一阶段p3-out-候选) 与 [known-issues.md §P3-out 候选](known-issues.md#p3-out-候选后续解耦工作)。
