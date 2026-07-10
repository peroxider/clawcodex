# F-107: PowerShell 支持增强

> 状态: ✅ 已完成
> 章节: docs/feature_plan/03-agent-core/f-107-powershell.md
> 最后更新: 2026-07-10

## §1 设计规划

### 1.1 目标

让 ClawCodex 的 BashTool 能够感知并适配 Windows 原生 shell（PowerShell），涵盖工具级 shell 选择、PowerShell 兼容的进程启动与 CWD 追踪、命令集分类/安全/只读/语义适配，以及 Windows 平台自动检测与优雅降级。

实现已全部落在 `clawcodex_ext/`（Layer 1）补丁层，`src/` 仅保留 facade/sys.modules 交换，未侵入上游源码。

### 1.2 当前基线

| 组件 | 当前行为 |
|------|---------|
| 进程启动 | 硬编码 `["bash", "-lc", wrapped]` |
| 后台执行 | 硬编码 `["bash", "-lc", wrapped]` |
| 工具名 | `BASH_TOOL_NAME = "Bash"` |
| CWD 追踪 | `pwd > {path}` + bash 包装 |
| 搜索分类 | 仅 POSIX 命令集 |
| 只读验证 | 仅 POSIX 命令集 |
| 命令语义 | 仅 POSIX 退出码解释 |
| 安全分析 | tree-sitter-bash AST 解析器 |

### 1.3 子特性分解

| # | 子特性 | 改动文件 | 改动量 | 风险 | 状态 |
|:-:|--------|----------|:------:|:----:|:----:|
| A | 工具 schema 扩展 + shell 检测 | `clawcodex_ext/tool_system/tools/bash/bash_tool.py` | ~80 行 | 低 | ✅ 完成 |
| B | 进程启动层适配 | `clawcodex_ext/tool_system/tools/bash/bash_tool.py`, `background.py` | ~120 行 | 低 | ✅ 完成 |
| C | 工具 Prompt 适配 | `clawcodex_ext/tool_system/tools/bash/prompt.py` | ~60 行 | 低 | ✅ 完成 |
| D | 命令分类适配 | `clawcodex_ext/tool_system/tools/bash/search_classification.py`, `read_only_validation.py` | ~120 行 | 中 | ✅ 完成 |
| E | 命令语义 & 退出码适配 | `clawcodex_ext/tool_system/tools/bash/command_semantics.py` | ~40 行 | 低 | ✅ 完成 |
| F | PowerShell 安全分析 | `clawcodex_ext/permissions/bash_security.py` + `powershell_security.py` | ~200 行 | 中 | ✅ 完成 |
| G | 技能系统 shell 传播 | `clawcodex_ext/tool_system/tools/skill.py`, `clawcodex_ext/skills/runtime_substitution.py` | ~30 行 | 中 | ✅ 完成 |
| H | Shell 基础设施统一 | `clawcodex_ext/utils/shell_resolver.py` | ~80 行 | 低 | ✅ 完成 |

**实际完成日期**: 2026-07-10

## §2 进度跟踪

- [x] H: `clawcodex_ext/utils/shell_resolver.py` 统一 shell 解析入口
- [x] A: `BashTool` schema 增加 `shell: bash | powershell | auto`
- [x] B: 前台/后台 PowerShell 进程启动、CWD 追踪、退出码包装
- [x] C: BashTool prompt 追加 Shell Selection / PowerShell Tips
- [x] D: PowerShell 命令集分类与只读校验
- [x] E: PowerShell 退出码语义（`Select-String` RC=1 等）
- [x] F: `powershell_security.py` 启发式安全分析
- [x] G: Skill frontmatter `shell: powershell` 透传到 BashTool
- [x] 测试覆盖：Windows 自动 shell 选择、PowerShell 权限分派不崩溃

## §2.1 已知待完善项

1. `destructive_warnings.py` 当前只有 POSIX 正则，未针对 PowerShell cmdlet 提供额外提示（安全分析 `PWSHSafetyLevel.destructive` 已覆盖破坏性判定，此处为可选增强）。
2. PowerShell 搜索/只读/语义/安全分析的细粒度单元测试尚不完整，建议后续补充。
3. 在 POSIX 环境且 `pwsh` 不在 PATH 时，显式 `shell="powershell"` 会降级为 bash 并输出 warning；Windows 真机验证仍是最终验收步骤。

## §3 实施细节

### 3.1 验收标准

| # | 验收项 | 状态 | 关键实现 |
|:-:|--------|:----:|----------|
| 1 | `BashTool.call({"command":"...", "shell":"powershell"})` 调用 pwsh 执行 | ✅ | `clawcodex_ext/utils/shell_resolver.py:build_shell_argv` |
| 2 | `shell:"auto"` 在 win32 上自动选择 PowerShell | ✅ | `resolve_shell()` 在 `win32` 且 `find_powershell_path()` 命中时返回 `powershell` |
| 3 | PowerShell 纯 cmdlet pipeline 正确分类为 search/read | ✅ | `search_classification.py` 中 `PWSH_*_COMMANDS` |
| 4 | `Select-String` RC=1 正确解释为"无匹配" | ✅ | `command_semantics.py:PWSH_COMMAND_SEMANTICS` |
| 5 | `Remove-Item -Recurse -Force` 标记为 destructive | ✅ | `powershell_security.py:analyze_powershell_safety` |
| 6 | 技能 frontmatter `shell: powershell` 实际生效 | ✅ | `clawcodex_ext/tool_system/tools/skill.py:_make_shell_executor` 透传 `shell` |
| 7 | hooks + BashTool 共用 `shell_resolver.py` | ✅ | hooks 通过 `shell_invocation.py` re-export 引用同一实现 |

### 3.2 实现位置速查

| 能力 | 文件 |
|------|------|
| Shell 解析/argv 构造 | `clawcodex_ext/utils/shell_resolver.py` |
| BashTool schema/执行/CWD 追踪 | `clawcodex_ext/tool_system/tools/bash/bash_tool.py` |
| 后台任务 shell 支持 | `clawcodex_ext/tool_system/tools/bash/background.py` |
| Prompt | `clawcodex_ext/tool_system/tools/bash/prompt.py` |
| 命令分类 | `clawcodex_ext/tool_system/tools/bash/search_classification.py` |
| 只读校验 | `clawcodex_ext/tool_system/tools/bash/read_only_validation.py` |
| 退出码语义 | `clawcodex_ext/tool_system/tools/bash/command_semantics.py` |
| PowerShell 安全分析 | `clawcodex_ext/permissions/powershell_security.py` |
| 权限分派入口 | `clawcodex_ext/permissions/bash_security.py:check_bash_command_safety` |
| 技能 shell 传播 | `clawcodex_ext/tool_system/tools/skill.py`, `clawcodex_ext/skills/loader.py`, `clawcodex_ext/skills/model.py` |

### 3.2 不纳入范围

- cmd.exe 支持
- PowerShell 7 vs Windows PowerShell 5.1 差异
- 特有的 `-Encoding`/`-ErrorAction` 自动适配
- PowerShell 工作流（PSWorkflow）/ DSC

### 3.4 依赖与协同

- F-48: P107-H 的 `shell_resolver.py` 落在 `clawcodex_ext/utils/`
- F-43: `/shell` 运行时命令可选依赖
- 现有 `clawcodex_ext/hooks/shell_invocation.py` 代码源

## §4 变更记录

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-06-24 | 初始创建（从四源融合） | 四文档合并 |
| 2026-07-10 | 标记为完成；补充实现位置速查与待完善项 | 实际代码已全部落地，文档状态滞后更新 |
