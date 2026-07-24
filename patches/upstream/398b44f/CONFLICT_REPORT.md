# 上游同步冲突报告：0b2f643 → 398b44f

## 结论

- 真实源码上游：`https://github.com/agentforce314/clawcodex.git`
- 上一个官方基线：`0b2f64362696258ee84ccc748193e3e6511ba0bc`
- 本次官方基线：`398b44f08f9de6dd36ab590d7d83799b34a28b3c`
- 本次官方基线提交时间：`2026-07-23 01:42:36 -0700`
- 团队下游原基线：`5abed79e82fe3bf646a29f2a03a0b9225beef681`
- 团队下游当前基线：`9b66bf84eeadbbd87b6b0b025db494b2cb3ae08c`
- 团队当前基线提交时间：`2026-07-23 20:08:04 +0800`
- 最终本地分支：`sync/upstream-398b44f`
- 源码整合提交：`f8c0b7faf3ce733c8bf69047db6d802cad04f42e`
- 策略：吸收官方新能力，同时保留团队分支的兼容门面、扩展实现和平台差异。

这次同步的关系可以写成：

```text
团队原基线 5abed79e
+ 官方 0b2f643 → 398b44f 的 8 个新增提交
+ 下游 clawcodex_ext 兼容实现与团队扩展
= 已完成的 398b44f 本地整合 5d330124

已完成的 398b44f 本地整合 5d330124
+ 团队 upstream 5abed79e → 9b66bf84 的 2 个提交
+ 5 个语义冲突解法与兼容修复
= 当前 sync/upstream-398b44f

官方 398b44f 的 src/ 快照
+ patches/upstream/398b44f/series 中的 583 个补丁
= 当前最终 src/（838 个过滤后文件，严格重建一致）
```

## 合并范围

官方 `0b2f643 → 398b44f` 共影响 34 个仓库文件；其中核心 `src/` 影响 18 个文件。主要变化包括：

1. Headless 工具过滤、别名规范化、非交互性能与消息持久化。
2. Query 循环的逐请求工具搜索、模型覆盖、thinking 块顺序和穷举结果审计。
3. Anthropic signed-thinking 保存与 Provider 响应结构扩展。
4. Bash 超时输出保留、独立/复合 `cd` 语义和短时 sleep 规则。
5. 消息 usage 持久化、成本估算恢复、Agent Server 与 MCP runtime 调整。

### 团队 upstream 二次刷新

官方源码基线继续固定在 `398b44f`，本次只刷新团队 upstream：

- 团队目标分支从 `5abed79e` 前移到 `9b66bf84`，新增 2 个提交。
- 主要内容提交为 `f4b4e1339`（Goal 生命周期、模型运行时与 Demo Factory），
  随后由 `9b66bf84` 合入团队目标分支。
- 团队增量涉及 90 个文件，统计为 `+9896 / -848`；与当前本地整合有
  17 个路径重叠。
- 新增团队内容没有修改 `src/`，因此官方 `398b44f` 快照及 583 个补丁的
  内容、数量和顺序均不需要重新生成。
- 本轮出现 5 个文本冲突：
  `clawcodex_ext/cli/dispatch.py`、
  `clawcodex_ext/entrypoints/headless.py`、
  `clawcodex_ext/goal/command.py`、
  `clawcodex_ext/query/agent_loop_compat.py`、
  `clawcodex_ext/query/query.py`。
- 语义合并保留了 398 集成中的消息持久化、thinking、工具过滤、
  memory/plan attachments、compaction、错误处理和 stop hooks，同时吸收了
  新团队基线的 Goal evaluator、运行时生命周期和模型目录能力。
- 额外兼容修复包括：统一 headless `/goal` 到新 CommandEngine 路径、将
  历史 `glm` 名称规范化到 `zai`（保留原生 class 直连兼容）、让 Session
  加载遵循 `CLAWCODEX_SESSIONS_DIR`，以及补齐新 Goal 工具测试要求的
  additional-properties 错误提示。

18 个核心文件中，13 个三方合并无文本冲突，5 个需要人工语义合并：

- `clawcodex_ext/entrypoints/headless.py`
- `clawcodex_ext/query/query.py`
- `clawcodex_ext/tool_system/tool_search.py`
- `clawcodex_ext/tool_system/tools/bash/bash_tool.py`
- `clawcodex_ext/types/messages.py`

## 主要冲突处理

### `src` 门面与 `clawcodex_ext` 实现

本仓库的大量 `src/*` 文件是到 `clawcodex_ext/*` 的兼容门面。官方改动不能只落到门面文件，否则真实运行路径不会生效。本次处理原则是：

- 官方实现合入真实运行的 `clawcodex_ext` 模块。
- `src` 继续提供原有导入路径和模块身份兼容。
- 不创建第二份注册表、缓存或单例状态。
- 官方仍直接实现于 `src` 的 4 个文件保持在 `src`：
  `entrypoints/agent_server_cli.py`、`query/continuation_nudge.py`、
  `server/agent_server.py`、`server/mcp_runtime.py`。

### Headless

- 吸收 `allowedTools` / `disallowedTools` 的别名规范化和 `remove_tool` 过滤。
- 保留团队分支的命令、cron、coordinator、退出持久化和 F-125 行为。
- 保存完整消息、usage 与 stream-json thinking 输出。
- 保留下游 `ToolRegistry.unregister` 兼容 API；实际新过滤路径使用 `remove_tool`。

### Query

- 吸收逐请求 Tool Search、模型覆盖、非流式 Provider 的线程卸载、thinking 块顺序和穷举审计闩锁。
- 保留 advisor、goal runtime、中间件、错误分类、watchdog、回调、成本/时长、终端状态和 skill scope。
- 官方实现位于 `src.query.query` 时可使用相对导入；迁移到
  `clawcodex_ext.query.query` 后，`continuation_nudge` 必须显式从
  `src.query.continuation_nudge` 导入，避免解析到不存在的扩展模块。

### Tool Search、Bash 与消息

- Tool Search 保留下游通用 MCP 即时加载语义，同时吸收官方的属性访问加固。
- Bash 保留 Windows 自动 PowerShell、超时后已捕获输出和团队安全策略，同时吸收官方独立/复合 `cd` 区分及 5 秒以内短等待。
- Assistant 消息吸收 usage 和 signed-thinking 持久化，同时保留 `duration_ms` 与下游 reasoning 字段。

## 补丁队列

- 修改官方文件：400
- 下游新增文件：183
- 下游删除官方文件：0
- preserve 例外：0
- 补丁总数：583
- 补丁总大小：3,947,798 bytes（约 3.8 MB）
- 实际补丁：`patches/upstream/398b44f/merged/*.patch`
- 主序列：`patches/upstream/398b44f/series`
- 兼容序列：`patches/upstream/398b44f/398b44f_series`
- `preserve.list` 有意为空，补丁队列可独立重建最终 `src/`。

补丁数量仍为 583，并不表示重复生成了 583 份源码；它表示当前下游相对官方快照存在 400 个修改文件和 183 个下游专有文件，每个文件对应一个可审计补丁。

## 验证结果

### 本次官方增量

- 30 个新增官方测试中，27 个在当前 Windows 环境直接通过。
- 2 个新增 `cd` 测试写死 POSIX `printf` / `pwd` 及 Linux 路径语义，需要在 Linux CI 验证。
- 1 个测试要求 `ToolRegistry` 不存在 `unregister`；下游有意保留该兼容 API，其他 9 个过滤、别名和 `remove_tool` 行为测试均通过。
- 官方相关测试文件复跑：221 passed；剩余 20 项均已归类为旧下游契约偏差或 Windows 不适用测试，没有未解释的新失败。

### 团队回归

- Query / Provider / Message / Cost / Parity：428 passed；19 项为未改路径的既有测试契约偏差。
- Tool Search / CLI / Bash / Server / MCP 可收集部分：586 passed，1 skipped；17 项为 Windows、测试遮蔽或既有依赖问题。
- 团队基线最后新增的 Multimodel 运行时测试：3 passed。
- 3 个 Tool Search 测试因团队最新基线缺少 `extensions.sop_converter` 的导出而在收集阶段失败，和本次官方增量无关。
- 所有 18 个变更 Python 文件均通过 `py_compile`；`git diff --check` 通过。

### 团队 upstream 二次刷新回归

- 先以纯团队 upstream `9b66bf84` 在同一 Windows 环境运行本轮 35 个变更
  测试文件，基线结果为 `532 passed, 146 failed`。
- 合并树修复前识别出 26 个稳定的集成新增失败；修复后对应重点回归为
  `93 passed`，没有剩余失败。
- 同一组 35 个测试文件最终结果为 `534 passed, 144 failed`；失败数比纯
  upstream 基线少 2，没有合并新增失败。剩余失败均属于 upstream 自身的
  Windows/既有基线问题。
- Headless 四文件回归：`76 passed`；F43 模型/供应商重点回归：
  `57 passed + 23 passed + 1 passed`；Agent loop 与 Goal runtime：
  `34 passed`。
- 冻结的官方 398 语义回归再次通过：Query loop `20 passed`，本次新增官方
  能力（排除 2 个 POSIX-only `cd` 用例和 1 个有意保留兼容 API 的用例）
  `27 passed`。
- 本轮暂存变更涉及的 89 个 Python 文件全部通过 `py_compile`；
  `git diff --check` 通过。

### 补丁不变量

- Patch Generator 专项测试：17 passed。
- `series` 与按文件名排序的 `merged/*.patch` 数量、顺序一致：583。
- `398b44f_series` 与 `merged/<series-entry>` 映射一致。
- 在仓库外的干净临时目录中，从官方 398b44f 快照依次执行 583 次
  `git apply --check` 和 `git apply`，全部成功。
- 重建结果与当前 `src/` 按生成器相同的过滤、换行归一化规则比较：
  `roundtrip OK: 838 filtered files`。

## 交付与远端

- 团队 upstream 目标为
  `upstream/dev-decoupling-refactor-398b44f@9b66bf84eeadbbd87b6b0b025db494b2cb3ae08c`。
- 官方源码按约定固定在 `398b44f`，本轮不再跟踪或合入官方后续提交。
- 本报告对应的交付分支为 `origin/sync/upstream-398b44f`。
- 本轮仅提交并推送分支，不创建 MR；Linux CI 与最终合入由远端流程完成。
